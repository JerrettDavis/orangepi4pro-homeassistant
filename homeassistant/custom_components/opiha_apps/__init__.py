"""Admin-only Orange Pi host and native app management for Home Assistant Container.

This integration neither impersonates Supervisor nor mounts the Docker socket. Host control, Docker and the terminal
are performed by the separate root manager on loopback; its credential never reaches browser JavaScript.
API compatibility target: Home Assistant 2026.9.3.
"""
from __future__ import annotations
from pathlib import Path
import re
from aiohttp import web
import voluptuous as vol
from homeassistant.components import panel_custom, websocket_api
from homeassistant.components.http import HomeAssistantView
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant
from .client import Client, NativeError, read_connection

DOMAIN = "opiha_apps"
# Kept in step with opiha_apps.hostctl.OPERATIONS (a test compares them); the manager validates every field.
HOST_OPERATIONS = ["overview", "stats", "hardware", "services", "service", "logs", "power", "docker", "container", "container_logs",
                   "images", "image", "docker_prune", "updates", "update_start", "update_job", "desktop", "desktop_mode", "display",
                   "term_open", "term_io", "term_close"]
HOST_TIMEOUT = 60
TERMINAL_TIMEOUT = 10
CONFIG_SCHEMA = vol.Schema({vol.Optional(DOMAIN): vol.Any(None, vol.Schema({}))}, extra=vol.ALLOW_EXTRA)


def _admin(connection):
    user = connection.user
    return user is not None and user.is_active and user.is_admin


@websocket_api.websocket_command({vol.Required("type"): "opiha_apps/request",
                                 vol.Required("operation"): vol.In(["overview", "metrics", "plan", "apply", "job", "logs", "credentials", "backups"]),
                                 vol.Optional("data", default={}): dict})
@websocket_api.async_response
async def ws_request(hass, connection, msg):
    if not _admin(connection):
        connection.send_error(msg["id"], "unauthorized", "An active Home Assistant administrator is required")
        return
    op, data = msg["operation"], msg["data"]
    try:
        if op in {"overview", "metrics"}:
            if data:
                raise NativeError("This operation takes no parameters")
            method, path, body = "GET", "/v1/" + op, None
        elif op == "plan":
            if set(data) - {"app", "action", "options", "backup"}:
                raise NativeError("Unknown plan fields")
            method, path, body = "POST", "/v1/plan", data
        elif op == "apply":
            if set(data) != {"id", "confirm"}:
                raise NativeError("Invalid plan approval")
            method, path, body = "POST", "/v1/apply", data
        elif op in {"job", "logs", "backups"}:
            key = "id" if op == "job" else "app"
            value = data.get(key)
            if set(data) != {key} or not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value):
                raise NativeError("Invalid request identifier")
            method, path, body = "GET", "/v1/jobs/" + value if op == "job" else "/v1/apps/" + value + "/" + op, None
        else:
            if data != {"confirm": True}:
                raise NativeError("Confirm before revealing the private broker account")
            method, path, body = "POST", "/v1/apps/mosquitto/credentials", data
        result = await hass.data[DOMAIN]["client"].request(method, path, body)
        connection.send_result(msg["id"], result)
    except NativeError as exc:
        connection.send_error(msg["id"], "native_apps_error", str(exc))


@websocket_api.websocket_command({vol.Required("type"): "opiha_apps/host",
                                 vol.Required("operation"): vol.In(HOST_OPERATIONS),
                                 vol.Optional("data", default={}): dict})
@websocket_api.async_response
async def ws_host(hass, connection, msg):
    if not _admin(connection):
        connection.send_error(msg["id"], "unauthorized", "An active Home Assistant administrator is required")
        return
    op = msg["operation"]
    try:
        result = await hass.data[DOMAIN]["client"].request(
            "POST", "/v1/host/" + op, msg["data"], TERMINAL_TIMEOUT if op.startswith("term_") else HOST_TIMEOUT)
        connection.send_result(msg["id"], result)
    except NativeError as exc:
        connection.send_error(msg["id"], "host_error", str(exc))


STORE_OPERATIONS = ["repos", "repo_add", "repo_refresh", "repo_remove", "repo_addons", "addon_plan", "ha_token"]
STORE_TIMEOUT = 330  # a shallow clone of a large repository can take minutes


@websocket_api.websocket_command({vol.Required("type"): "opiha_apps/store",
                                 vol.Required("operation"): vol.In(STORE_OPERATIONS),
                                 vol.Optional("data", default={}): dict})
@websocket_api.async_response
async def ws_store(hass, connection, msg):
    """Add-on repositories and install planning. Applying a plan uses the ordinary opiha_apps/request apply."""
    if not _admin(connection):
        connection.send_error(msg["id"], "unauthorized", "An active Home Assistant administrator is required")
        return
    op, data = msg["operation"], msg["data"]
    try:
        timeout = None
        if op == "repos":
            if data:
                raise NativeError("This operation takes no parameters")
            method, path, body = "GET", "/v1/repos", None
        elif op == "repo_addons":
            value = data.get("id")
            if set(data) != {"id"} or not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{8}", value):
                raise NativeError("Invalid repository identifier")
            method, path, body = "GET", "/v1/repos/" + value + "/addons", None
        elif op in {"repo_add", "repo_refresh", "repo_remove"}:
            key = "url" if op == "repo_add" else "id"
            if set(data) != {key} or not isinstance(data[key], str) or len(data[key]) > 200:
                raise NativeError("Invalid repository request")
            method, path, body = "POST", "/v1/repos/" + op.removeprefix("repo_"), data
            timeout = STORE_TIMEOUT if op != "repo_remove" else None
        elif op == "addon_plan":
            if set(data) - {"repository", "folder", "options"} or not {"repository", "folder"} <= set(data):
                raise NativeError("Unknown add-on planning fields")
            method, path, body = "POST", "/v1/addon/plan", data
        else:
            if set(data) != {"token"}:
                raise NativeError("Send only the access token")
            method, path, body = "POST", "/v1/addons/ha-token", data
        connection.send_result(msg["id"], await hass.data[DOMAIN]["client"].request(method, path, body, timeout))
    except NativeError as exc:
        connection.send_error(msg["id"], "native_apps_error", str(exc))


ASSET_TYPES = {".js": "application/javascript", ".css": "text/css"}


class PanelAsset(HomeAssistantView):
    """The panel's own code and vendored terminal library. Public source only; every data call is authenticated."""
    url = r"/api/opiha_apps/{name:[A-Za-z0-9._-]+\.(?:js|css)}"
    name = "api:opiha_apps:panel"
    requires_auth = False

    def __init__(self, assets: dict[str, bytes]):
        self.assets = assets

    async def get(self, request, name):
        body = self.assets.get(name)
        if body is None:
            raise web.HTTPNotFound()
        return web.Response(body=body, content_type=ASSET_TYPES[Path(name).suffix],
                            headers={"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"})


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    if DOMAIN not in config:
        return True
    if DOMAIN in hass.data:
        return True
    import logging
    logger = logging.getLogger(__name__)
    try:
        connection = await hass.async_add_executor_job(read_connection, Path(hass.config.path("opiha-apps-connection.json")))
    except (OSError, ValueError, NativeError):
        logger.error("Native Apps has no valid private connection file; run opiha-apps install-host on the host")
        return False
    client = Client(connection)
    from .ingress import Ingress, SessionView
    ingress = Ingress(hass, client)
    hass.data[DOMAIN] = {"client": client, "ingress": ingress}
    assets = await hass.async_add_executor_job(
        lambda: {p.name: p.read_bytes() for p in sorted(Path(__file__).parent.iterdir()) if p.suffix in ASSET_TYPES})
    hass.http.register_view(PanelAsset(assets))
    hass.http.register_view(SessionView(ingress))
    hass.http.register_view(ingress)
    websocket_api.async_register_command(hass, ws_request)
    websocket_api.async_register_command(hass, ws_host)
    websocket_api.async_register_command(hass, ws_store)
    await panel_custom.async_register_panel(hass, frontend_url_path="opiha-apps",
        webcomponent_name="opiha-apps-panel", sidebar_title="Orange Pi", sidebar_icon="mdi:chip",
        module_url="/api/opiha_apps/panel.js?v=0.3.0-alpha.11", require_admin=True)

    async def stop(_event):
        await ingress.close()
        await client.close()
    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, stop)
    return True
