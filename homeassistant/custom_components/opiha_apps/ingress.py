"""Narrow, admin-authenticated in-HA UI proxy for the three reviewed adapters.

No arbitrary URL proxy, static public token, blanket cookie/header forwarding,
or Supervisor-token emulation. App code still shares the HA browser origin;
only install trusted app publishers and trusted Node-RED palette packages.
"""
from __future__ import annotations
import asyncio
from http.cookies import SimpleCookie
import re
import secrets
import time
from urllib.parse import quote, unquote, urlsplit
from yarl import URL
import aiohttp
from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from .client import NativeError

PREFIX = "/api/opiha_apps/ingress/"
APPS = {"nodered", "esphome", "go2rtc"}
COOKIE_PREFIX = "opiha_auth_"
BODY_LIMIT = 8 * 1024 * 1024
RESPONSE_LIMIT = 128 * 1024 * 1024
SESSION_SECONDS = 300
REQUEST_HEADERS = {"accept", "accept-language", "content-type", "if-none-match", "if-modified-since", "cache-control", "range",
                   # Node-RED editor API negotiation; without it the editor receives the legacy /flows format.
                   "node-red-api-version", "node-red-deployment-type"}
RESPONSE_HEADERS = {"content-type", "content-disposition", "etag", "last-modified", "cache-control", "content-range", "accept-ranges"}


def safe_tail(tail: str) -> str:
    value = tail
    for _ in range(5):
        if any(c in value for c in "\\\x00\r\n") or any(p in {".", ".."} for p in value.split("/")) or value.startswith("/"):
            raise web.HTTPBadRequest(text="Invalid application path")
        decoded = unquote(value)
        if decoded == value:
            return quote(value, safe="/!$&'()*+,;=:@-._~")
        value = decoded
    raise web.HTTPBadRequest(text="Excessively encoded application path")


def same_origin(request) -> bool:
    raw = request.headers.get("Origin")
    if raw is None:
        return request.method in {"GET", "HEAD"}
    try:
        incoming = urlsplit(raw)
        expected = urlsplit(f"{request.scheme}://{request.host}")
        return (incoming.scheme, incoming.netloc) == (expected.scheme, expected.netloc) and incoming.path in {"", "/"}
    except ValueError:
        return False


def rewrite_location(value: str, prefix: str, port: int) -> str:
    if any(x in value for x in ("\r", "\n", "\\")) or value.startswith("//"):
        raise web.HTTPBadGateway(text="Unsafe application redirect")
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc:
        if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.port != port or parsed.username:
            raise web.HTTPBadGateway(text="Cross-origin application redirect is not supported")
        value = parsed.path + ("?" + parsed.query if parsed.query else "")
    safe_tail(parsed.path.lstrip("/"))
    if value.startswith("/") and not value.startswith(prefix):
        value = prefix + value.lstrip("/")
    return value


class SessionView(HomeAssistantView):
    url = "/api/opiha_apps/session"
    name = "api:opiha_apps:session"
    requires_auth = True

    def __init__(self, ingress):
        self.ingress = ingress

    async def post(self, request):
        user = request.get("hass_user")
        refresh_id = request.get("hass_refresh_token_id")
        if not user or not user.is_admin or not user.is_active or not refresh_id:
            raise web.HTTPForbidden(text="An active administrator login is required")
        if request.content_length is None or request.content_length > 1024:
            raise web.HTTPRequestEntityTooLarge(max_size=1024, actual_size=request.content_length or 0)
        try:
            data = await request.json()
            if not isinstance(data, dict) or set(data) != {"app"} or data["app"] not in APPS:
                raise web.HTTPBadRequest(text="Unknown application route")
            descriptor = await self.ingress.client.request("GET", "/v1/apps/" + data["app"] + "/ingress")
            app = data["app"]
            prefix = PREFIX + app + "/"
            if descriptor.get("prefix") != prefix or type(descriptor.get("port")) is not int or not 1024 <= descriptor["port"] <= 65535:
                raise web.HTTPBadGateway(text="Invalid application route descriptor")
            self.ingress.expire()
            token = next((key for key, row in self.ingress.sessions.items()
                          if row["app"] == app and row["refresh_id"] == refresh_id and row["user_id"] == user.id), None)
            if token:
                self.ingress.sessions[token]["expires"] = time.monotonic() + SESSION_SECONDS
                self.ingress.sessions[token]["port"] = descriptor["port"]
            else:
                if len(self.ingress.sessions) >= 128:
                    raise web.HTTPServiceUnavailable(text="Too many active app sessions")
                token = secrets.token_urlsafe(32)
                self.ingress.sessions[token] = {"app": app, "refresh_id": refresh_id, "user_id": user.id,
                                           "expires": time.monotonic() + SESSION_SECONDS,
                                           "port": descriptor["port"], "cookies": set()}
            response = web.json_response({"url": prefix, "expires_in": SESSION_SECONDS}, headers={"Cache-Control": "no-store"})
            response.set_cookie(COOKIE_PREFIX + app, token, httponly=True, secure=request.secure,
                                samesite="Strict", max_age=SESSION_SECONDS, path=prefix)
            return response
        except NativeError as exc:
            raise web.HTTPServiceUnavailable(text=str(exc)) from exc
        except (ValueError, KeyError, TypeError) as exc:
            raise web.HTTPBadRequest(text="Invalid app-session request") from exc


class Ingress(HomeAssistantView):
    url = PREFIX + "{app}/{tail:.*}"
    name = "api:opiha_apps:ingress"
    requires_auth = False  # Auth below is a short-lived, admin/refresh-token-bound HttpOnly cookie.

    def __init__(self, hass, client):
        self.hass, self.client = hass, client
        self.sessions = {}
        self.http = aiohttp.ClientSession(cookie_jar=aiohttp.DummyCookieJar(), auto_decompress=False,
                  timeout=aiohttp.ClientTimeout(total=120, connect=10, sock_read=90))
        self.sockets = set()
        self.active_websockets = 0

    async def close(self):
        for socket in list(self.sockets):
            await socket.close()
        self.sessions.clear()
        await self.http.close()

    def expire(self):
        for key in list(self.sessions):
            if self.sessions[key]["expires"] <= time.monotonic():
                del self.sessions[key]

    def valid(self, session: dict) -> bool:
        if session["expires"] <= time.monotonic():
            return False
        refresh = self.hass.auth.async_get_refresh_token(session["refresh_id"])
        return bool(refresh and refresh.user.id == session["user_id"] and refresh.user.is_admin and refresh.user.is_active)

    def authorize(self, request, app):
        if app not in APPS or not same_origin(request):
            raise web.HTTPForbidden(text="Invalid application origin or route")
        session = self.sessions.get(request.cookies.get(COOKIE_PREFIX + app, ""))
        if not session or session["app"] != app or not self.valid(session):
            raise web.HTTPUnauthorized(text="Open this app again from Orange Pi Apps")
        # Reapply HA's local-user restriction on cookie-authenticated requests.
        from homeassistant.components.http.auth import async_user_not_allowed_do_auth
        refresh = self.hass.auth.async_get_refresh_token(session["refresh_id"])
        if async_user_not_allowed_do_auth(self.hass, refresh.user, request):
            raise web.HTTPForbidden(text="This HA user cannot authenticate from this location")
        return session

    def upstream_headers(self, request, app: str, session: dict) -> dict:
        headers = {k: v for k, v in request.headers.items() if k.lower() in REQUEST_HEADERS}
        # Ask for identity bytes; do not silently decompress while retaining upstream lengths.
        headers["Accept-Encoding"] = "identity"
        headers["Origin"] = f"http://127.0.0.1:{session['port']}"
        headers["X-Ingress-Path"] = PREFIX + app
        headers["X-Forwarded-Prefix"] = PREFIX + app
        jar = SimpleCookie()
        for key in session["cookies"]:
            value = request.cookies.get("opiha_backend_" + app + "_" + key)
            if value is not None:
                jar[key] = value
        if jar:
            headers["Cookie"] = "; ".join(m.OutputString() for m in jar.values())
        # Authorization, HA cookies, x-forwarded-* and the manager token are not forwarded.
        return headers

    def copy_cookies(self, upstream, response, request, app: str, session: dict):
        prefix = PREFIX + app + "/"
        for line in upstream.headers.getall("Set-Cookie", []):
            jar = SimpleCookie()
            try:
                jar.load(line)
            except Exception:
                continue
            for name, morsel in jar.items():
                if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name) or len(morsel.value) > 4096:
                    continue
                if len(session["cookies"]) >= 32 and name not in session["cookies"]:
                    continue
                session["cookies"].add(name)
                response.set_cookie("opiha_backend_" + app + "_" + name, morsel.value,
                     path=prefix, secure=request.secure, httponly=bool(morsel["httponly"]), samesite="Strict",
                     max_age=0 if morsel["max-age"] == "0" else SESSION_SECONDS)

    async def get(self, request, app, tail=""):
        return await self.proxy(request, app, tail)

    async def head(self, request, app, tail=""):
        return await self.proxy(request, app, tail)

    async def post(self, request, app, tail=""):
        return await self.proxy(request, app, tail)

    async def put(self, request, app, tail=""):
        return await self.proxy(request, app, tail)

    async def patch(self, request, app, tail=""):
        return await self.proxy(request, app, tail)

    async def delete(self, request, app, tail=""):
        return await self.proxy(request, app, tail)

    async def proxy(self, request, app: str, tail: str):
        session = self.authorize(request, app)
        path = safe_tail(tail)
        prefix = PREFIX + app + "/"
        upstream_path = "/" + path if app == "esphome" else prefix + path
        url = URL(f"http://127.0.0.1:{session['port']}" + upstream_path, encoded=True)
        if request.query_string:
            if len(request.query_string) > 8192:
                raise web.HTTPBadRequest(text="Application query is too long")
            url = url.with_query(request.query)
        headers = self.upstream_headers(request, app, session)
        if request.headers.get("Upgrade", "").lower() == "websocket":
            return await self.websocket(request, url, headers, session)
        if request.content_length is not None and request.content_length > BODY_LIMIT:
            raise web.HTTPRequestEntityTooLarge(max_size=BODY_LIMIT, actual_size=request.content_length)
        body = bytearray()
        async for chunk in request.content.iter_chunked(65536):
            body.extend(chunk)
            if len(body) > BODY_LIMIT:
                raise web.HTTPRequestEntityTooLarge(max_size=BODY_LIMIT, actual_size=len(body))
        try:
            async with self.http.request(request.method, url, headers=headers, data=bytes(body), allow_redirects=False) as upstream:
                output_headers = {k: v for k, v in upstream.headers.items() if k.lower() in RESPONSE_HEADERS}
                if "Content-Encoding" in upstream.headers:
                    output_headers["Content-Encoding"] = upstream.headers["Content-Encoding"]
                output_headers.setdefault("Cache-Control", "no-store")
                output_headers["X-Content-Type-Options"] = "nosniff"
                output_headers["X-Frame-Options"] = "SAMEORIGIN"
                output_headers["Content-Security-Policy"] = "frame-ancestors 'self'"
                if "Location" in upstream.headers:
                    output_headers["Location"] = rewrite_location(upstream.headers["Location"], prefix, session["port"])
                response = web.StreamResponse(status=upstream.status, headers=output_headers)
                self.copy_cookies(upstream, response, request, app, session)
                await response.prepare(request)
                size = 0
                async for chunk in upstream.content.iter_chunked(65536):
                    if not self.valid(session):
                        break
                    size += len(chunk)
                    if size > RESPONSE_LIMIT:
                        break
                    await response.write(chunk)
                await response.write_eof()
                return response
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise web.HTTPBadGateway(text="The native application's web service is unavailable") from exc

    async def websocket(self, request, url, headers, session):
        if self.active_websockets >= 8:
            raise web.HTTPServiceUnavailable(text="App WebSocket connection limit reached")
        protocols = request.headers.get("Sec-WebSocket-Protocol", "").split(",")
        protocols = [p.strip() for p in protocols if p.strip()]
        if len(protocols) > 8 or any(not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", p) for p in protocols):
            raise web.HTTPBadRequest(text="Unsupported WebSocket subprotocol")
        self.active_websockets += 1
        frontend = web.WebSocketResponse(protocols=protocols, max_msg_size=BODY_LIMIT, heartbeat=30)
        tasks = []
        try:
            async with self.http.ws_connect(url, headers=headers, protocols=protocols,
                                            max_msg_size=BODY_LIMIT, heartbeat=30) as backend:
                await frontend.prepare(request)
                self.sockets.add(frontend)

                async def transfer(source, target):
                    async for message in source:
                        if not self.valid(session):
                            break
                        if message.type == aiohttp.WSMsgType.TEXT:
                            await target.send_str(message.data)
                        elif message.type == aiohttp.WSMsgType.BINARY:
                            await target.send_bytes(message.data)
                        elif message.type in {aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR}:
                            break

                async def authorization_watch():
                    while self.valid(session):
                        await asyncio.sleep(5)

                tasks = [asyncio.create_task(transfer(frontend, backend)), asyncio.create_task(transfer(backend, frontend)),
                         asyncio.create_task(authorization_watch())]
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                await frontend.close()
                return frontend
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise web.HTTPBadGateway(text="The application WebSocket is unavailable") from exc
        finally:
            for task in tasks:
                task.cancel()
            self.sockets.discard(frontend)
            self.active_websockets -= 1
