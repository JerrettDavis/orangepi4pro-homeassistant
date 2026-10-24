"""Home Assistant WebSocket relay and MQTT discovery for add-ons.

Add-ons talk to `ws://supervisor/core/websocket` with their SUPERVISOR_TOKEN as the access token. The relay
authenticates the add-on itself, then authenticates to Home Assistant with the administrator-provided
long-lived token and forwards frames both ways. The add-on never sees the Home Assistant token.

Discovery cannot use the Supervisor integration (a Container install has none). For MQTT the broker is
registered through Home Assistant's own config-flow REST API using that same token.
"""
from __future__ import annotations
import base64
import hashlib
import json
import os
import re
import socket
import struct
import threading
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from .common import AppError

GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
MAX_FRAME = 8 * 1024 * 1024
MAX_RELAYS = 16
_active = threading.BoundedSemaphore(MAX_RELAYS)


class Prefixed:
    """A socket whose first recv() returns bytes already read past the HTTP handshake."""
    def __init__(self, sock: socket.socket, prefix: bytes):
        self.sock, self.prefix = sock, prefix

    def recv(self, n: int) -> bytes:
        if self.prefix:
            out, self.prefix = self.prefix[:n], self.prefix[n:]
            return out
        return self.sock.recv(n)

    def __getattr__(self, name):
        return getattr(self.sock, name)


def read_exact(sock: socket.socket, n: int) -> bytes:
    chunks, got = [], 0
    while got < n:
        part = sock.recv(min(65536, n - got))
        if not part:
            raise ConnectionError("peer closed")
        chunks.append(part)
        got += len(part)
    return b"".join(chunks)


def _xor(data: bytes, key: bytes) -> bytes:
    if not data:
        return data
    pad = (key * (len(data) // 4 + 1))[:len(data)]
    return (int.from_bytes(data, "big") ^ int.from_bytes(pad, "big")).to_bytes(len(data), "big")


def read_frame(sock: socket.socket) -> tuple[bool, int, bytes]:
    b1, b2 = read_exact(sock, 2)
    length = b2 & 0x7F
    if length == 126:
        length = struct.unpack(">H", read_exact(sock, 2))[0]
    elif length == 127:
        length = struct.unpack(">Q", read_exact(sock, 8))[0]
    if length > MAX_FRAME:
        raise ConnectionError("frame too large")
    key = read_exact(sock, 4) if b2 & 0x80 else None
    data = read_exact(sock, length)
    return bool(b1 & 0x80), b1 & 0x0F, _xor(data, key) if key else data


def write_frame(sock: socket.socket, fin: bool, opcode: int, data: bytes, mask: bool) -> None:
    header = bytes([(0x80 if fin else 0) | opcode])
    n = len(data)
    flag = 0x80 if mask else 0
    header += bytes([flag | n]) if n < 126 else bytes([flag | 126]) + struct.pack(">H", n) if n < 65536 else bytes([flag | 127]) + struct.pack(">Q", n)
    if mask:
        key = os.urandom(4)
        header += key
        data = _xor(data, key)
    sock.sendall(header + data)


def send_json(sock, value: dict, mask: bool):
    write_frame(sock, True, 0x1, json.dumps(value).encode(), mask)


def read_json(sock) -> dict:
    """Next text message from a peer, answering control frames; JSON object or raises."""
    while True:
        fin, op, data = read_frame(sock)
        if op == 0x8:
            raise ConnectionError("closed")
        if op in (0x9, 0xA):
            continue
        if op == 0x1 and fin:
            value = json.loads(data)
            if not isinstance(value, dict):
                raise ValueError("not an object")
            return value
        raise ConnectionError("unexpected frame during authentication")


def close_politely(sock: socket.socket, code: int = 1000) -> None:
    """Send a Close frame and give the peer a moment to read everything before the TCP close."""
    try:
        write_frame(sock, True, 0x8, struct.pack(">H", code), False)
        sock.shutdown(socket.SHUT_WR)
        sock.settimeout(2)
        while sock.recv(4096):
            pass
    except OSError:
        pass


def connect_ha(ha_url: str) -> socket.socket:
    parts = urlsplit(ha_url)
    if parts.scheme != "http" or parts.hostname not in {"127.0.0.1", "localhost"}:
        raise AppError("Home Assistant must be reached on loopback over http")
    sock = socket.create_connection((parts.hostname, parts.port or 80), timeout=10)
    key = base64.b64encode(os.urandom(16)).decode()
    sock.sendall((f"GET /api/websocket HTTP/1.1\r\nHost: {parts.hostname}:{parts.port or 80}\r\nUpgrade: websocket\r\n"
                  f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
    head = b""
    while b"\r\n\r\n" not in head:
        part = sock.recv(4096)
        if not part or len(head) > 16384:
            raise AppError("Home Assistant refused the WebSocket handshake")
        head += part
    header, _, rest = head.partition(b"\r\n\r\n")
    expect = base64.b64encode(hashlib.sha1(key.encode() + GUID).digest())
    if b" 101 " not in header.split(b"\r\n")[0] or expect not in header:
        raise AppError("Home Assistant refused the WebSocket handshake")
    sock.settimeout(None)
    return Prefixed(sock, rest) if rest else sock


def accept_key(key: str) -> str:
    return base64.b64encode(hashlib.sha1(key.encode() + GUID).digest()).decode()


def relay(client: socket.socket, ha_token: str, ha_url: str, valid_token) -> None:
    """Authenticate the add-on, authenticate to HA, then pump frames both ways until either side closes."""
    if not _active.acquire(blocking=False):
        send_json(client, {"type": "auth_invalid", "message": "Too many add-on WebSocket sessions"}, False)
        close_politely(client, 1013)
        return
    upstream = None
    try:
        upstream = connect_ha(ha_url)
        hello = read_json(upstream)
        if hello.get("type") != "auth_required":
            raise AppError("Unexpected Home Assistant greeting")
        send_json(client, {"type": "auth_required", "ha_version": hello.get("ha_version")}, False)
        client.settimeout(30)
        auth = read_json(client)
        client.settimeout(None)
        if auth.get("type") != "auth" or not valid_token(str(auth.get("access_token", ""))):
            send_json(client, {"type": "auth_invalid", "message": "Invalid add-on token"}, False)
            close_politely(client, 1008)
            return
        send_json(upstream, {"type": "auth", "access_token": ha_token}, True)
        reply = read_json(upstream)
        if reply.get("type") != "auth_ok":
            send_json(client, {"type": "auth_invalid", "message": "Home Assistant rejected the configured access token"}, False)
            close_politely(client, 1008)
            return
        send_json(client, {"type": "auth_ok", "ha_version": reply.get("ha_version")}, False)

        def pump(src, dst, mask_out):
            try:
                while True:
                    fin, op, data = read_frame(src)
                    write_frame(dst, fin, op, data, mask_out)
                    if op == 0x8:
                        break
            except (OSError, ConnectionError):
                pass
            finally:
                for s in (src, dst):
                    try:
                        s.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
        a = threading.Thread(target=pump, args=(client, upstream, True), daemon=True)
        b = threading.Thread(target=pump, args=(upstream, client, False), daemon=True)
        a.start()
        b.start()
        a.join()
        b.join()
    except (OSError, ConnectionError, ValueError, AppError):
        try:
            send_json(client, {"type": "auth_invalid", "message": "Home Assistant WebSocket is unavailable"}, False)
            close_politely(client, 1011)
        except OSError:
            pass
    finally:
        _active.release()
        if upstream:
            upstream.close()


# --- MQTT discovery through the config-flow API ----------------------------------------------

def _rest(base: str, token: str, path: str, body: dict | None = None):
    request = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                     method="POST" if body is not None else "GET",
                                     headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read(2 * 1024 * 1024))
    except urllib.error.HTTPError as exc:
        raise AppError(f"Home Assistant answered {exc.code} for {path}") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise AppError("Home Assistant is not reachable") from exc


def fill_form(schema: list, supplied: dict) -> dict:
    """Build a config-flow submission from Home Assistant's own serialized form: our values where we have them,
    otherwise the form's default, otherwise a neutral value for required fields (False / first option / minimum / "")."""
    out: dict = {}
    for item in schema:
        name = item.get("name")
        if item.get("type") == "expandable":
            out[name] = fill_form(item.get("schema", []), {})
            continue
        selector = item.get("selector") or {}
        if name in supplied and supplied[name] is not None:
            out[name] = supplied[name]
        elif "default" in item:
            out[name] = item["default"]
        elif item.get("required"):
            if "boolean" in selector:
                out[name] = False
            elif "select" in selector:
                options = selector["select"].get("options") or [""]
                first = options[0]
                out[name] = first["value"] if isinstance(first, dict) else first
            elif "number" in selector:
                out[name] = selector["number"].get("min", 0)
            else:
                out[name] = ""
    return out


def discover_flow(ha_url: str, token: str, handler: str, supplied: dict, menu_step: str | None = None) -> str:
    """Drive one Home Assistant config flow to completion with the form filled from HA's own schema.
    Returns "created" or the abort reason (for example already_configured)."""
    base = ha_url.rstrip("/")
    flow = _rest(base, token, "/api/config/config_entries/flow", {"handler": handler, "show_advanced_options": False})
    if flow.get("type") == "abort":
        return flow.get("reason", "aborted")
    if flow.get("type") == "menu" and menu_step:
        flow = _rest(base, token, "/api/config/config_entries/flow/" + flow["flow_id"], {"next_step_id": menu_step})
    if flow.get("type") != "form":
        raise AppError(f"Unexpected Home Assistant {handler} setup step")
    data = fill_form(flow.get("data_schema") or [], supplied)
    for key, value in supplied.items():
        if value is not None:
            data.setdefault(key, value)
    done = _rest(base, token, "/api/config/config_entries/flow/" + flow["flow_id"], data)
    if done.get("type") == "create_entry":
        return "created"
    if done.get("type") == "abort":
        return done.get("reason", "aborted")
    raise AppError(f"Home Assistant did not accept the {handler} service: " + str(done.get("errors") or done.get("reason") or done.get("type")))


def _address(host: str, port) -> None:
    if not re.fullmatch(r"[A-Za-z0-9.:-]{1,100}", host) or type(port) is not int or not 1 <= port <= 65535:
        raise AppError("Invalid service address")


def discover_mqtt(ha_url: str, token: str, host: str, port: int, username: str | None, password: str | None,
                  protocol: str | None = None) -> str:
    """Register a broker with Home Assistant's MQTT integration. Returns a short outcome string."""
    _address(host, port)
    supplied = {"broker": host, "port": port, "protocol": protocol if protocol in {"5", "3.1.1", "3.1"} else None}
    if username:
        supplied.update(username=username, password=password or "")
    return discover_flow(ha_url, token, "mqtt", supplied, menu_step="broker")


def discover_wyoming(ha_url: str, token: str, host: str, port: int) -> str:
    """Register a Wyoming voice service (Piper, Whisper, openWakeWord, ...) with Home Assistant."""
    _address(host, port)
    return discover_flow(ha_url, token, "wyoming", {"host": host, "port": port})


# Services whose Home Assistant setup form asks for one URL: (handler, URL template, default port).
URL_SERVICES = {"zwave_js": ("zwave_js", "ws://{host}:{port}", 3000),
                "matter": ("matter", "ws://{host}:{port}/ws", 5580),
                "otbr": ("otbr", "http://{host}:{port}", 8081)}


def discover_url_service(ha_url: str, token: str, service: str, host: str, port) -> str:
    """Register Z-Wave JS, Matter Server or the OpenThread Border Router by the URL Home Assistant's form asks for."""
    handler, template, default = URL_SERVICES[service]
    port = default if port is None else port
    _address(host, port)
    return discover_flow(ha_url, token, handler, {"url": template.format(host=host, port=port)})
