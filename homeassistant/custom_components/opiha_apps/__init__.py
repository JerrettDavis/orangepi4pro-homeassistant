"""Admin-only native app management for Home Assistant Container.

This integration neither impersonates Supervisor nor mounts the Docker socket.
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
CONFIG_SCHEMA = vol.Schema({vol.Optional(DOMAIN): vol.Any(None, vol.Schema({}))}, extra=vol.ALLOW_EXTRA)


def _admin(connection):
    user = connection.user
    return user is not None and user.is_active and user.is_admin


@websocket_api.websocket_command({vol.Required("type"): "opiha_apps/request",
                                 vol.Required("operation"): vol.In(["overview", "metrics", "plan", "apply", "job", "logs", "credentials"]),
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
            if set(data) - {"app", "action", "options"}:
                raise NativeError("Unknown plan fields")
            method, path, body = "POST", "/v1/plan", data
        elif op == "apply":
            if set(data) != {"id", "confirm"}:
                raise NativeError("Invalid plan approval")
            method, path, body = "POST", "/v1/apply", data
        elif op in {"job", "logs"}:
            key = "id" if op == "job" else "app"
            value = data.get(key)
            if set(data) != {key} or not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value):
                raise NativeError("Invalid request identifier")
            method, path, body = "GET", "/v1/jobs/" + value if op == "job" else "/v1/apps/" + value + "/logs", None
        else:
            if data != {"confirm": True}:
                raise NativeError("Confirm before revealing the private broker account")
            method, path, body = "POST", "/v1/apps/mosquitto/credentials", data
        result = await hass.data[DOMAIN]["client"].request(method, path, body)
        connection.send_result(msg["id"], result)
    except NativeError as exc:
        connection.send_error(msg["id"], "native_apps_error", str(exc))


class PanelAsset(HomeAssistantView):
    url = "/api/opiha_apps/panel.js"
    name = "api:opiha_apps:panel"
    requires_auth = False

    def __init__(self, source: bytes):
        self.source = source

    async def get(self, request):
        return web.Response(body=self.source, content_type="application/javascript", headers={"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"})


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
    source = await hass.async_add_executor_job((Path(__file__).parent / "panel.js").read_bytes)
    hass.http.register_view(PanelAsset(source))
    hass.http.register_view(SessionView(ingress))
    hass.http.register_view(ingress)
    websocket_api.async_register_command(hass, ws_request)
    await panel_custom.async_register_panel(hass, frontend_url_path="opiha-apps",
        webcomponent_name="opiha-apps-panel", sidebar_title="Orange Pi Apps", sidebar_icon="mdi:apps",
        module_url="/api/opiha_apps/panel.js?v=0.2.0-alpha.6", require_admin=True)

    async def stop(_event):
        await ingress.close()
        await client.close()
    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, stop)
    return True
