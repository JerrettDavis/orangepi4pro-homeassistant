"""Install and configure the pinned OIDC integration without changing HA auth storage."""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .common import ApplianceError, REPO, read_json


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _validate_url(value: str, *, loopback_http: bool = False) -> str:
    parts = urlsplit(value)
    if (parts.scheme != "https" and not (
        loopback_http and parts.scheme == "http" and parts.hostname in ("127.0.0.1", "localhost", "::1")
    )) or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ApplianceError("OIDC URLs must use HTTPS, without credentials, query, or fragment")
    return value.rstrip("/")


def _request(opener, base: str, token: str, method: str, path: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    request = Request(base + path, data=data, method=method, headers={
        "Authorization": "Bearer " + token, "Content-Type": "application/json",
    })
    try:
        with opener.open(request, timeout=30) as response:
            if response.status == 204:
                return None
            return json.load(response)
    except HTTPError as exc:
        raise ApplianceError(f"Home Assistant configuration API returned HTTP {exc.code}") from exc
    except (URLError, TimeoutError, ValueError) as exc:
        raise ApplianceError("Home Assistant configuration API request failed") from exc


def configure(token_file: Path, ha_url: str | None = None) -> dict:
    settings = read_json(REPO / "config/authentik-sso.json")
    base = _validate_url(ha_url or settings["homeassistant_url"], loopback_http=True)
    discovery = _validate_url(settings["discovery_url"])
    if os.name == "posix" and stat.S_IMODE(token_file.stat().st_mode) & 0o077:
        raise ApplianceError("Home Assistant administrator token file must not be accessible to group or others")
    token = token_file.read_text(encoding="utf-8").strip()
    if not token:
        raise ApplianceError("Home Assistant administrator token file is empty")
    opener = build_opener(_NoRedirect())

    def request(method, path, body=None):
        return _request(opener, base, token, method, path, body)

    entries = request("GET", "/api/config/config_entries/entry")
    if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
        raise ApplianceError("Unexpected Home Assistant configuration entry response")
    if any(entry.get("domain") == "auth_oidc" for entry in entries):
        return {"configured": False, "reason": "existing_entry_preserved"}
    flow = request("POST", "/api/config/config_entries/flow", {
        "handler": "auth_oidc", "show_advanced_options": False,
    })
    if not isinstance(flow, dict):
        raise ApplianceError("Unexpected Home Assistant configuration flow response")
    flow_id = flow.get("flow_id")
    if not isinstance(flow_id, str) or not flow_id.isalnum():
        raise ApplianceError("Home Assistant did not start an OIDC configuration flow")
    path = "/api/config/config_entries/flow/" + flow_id
    try:
        steps = (
            ("user", {"provider": settings["provider"]}),
            ("discovery_url", {"discovery_url": discovery}),
            ("validate_connection", {"action": "continue"}),
            ("client_config", {"client_id": settings["client_id"]}),
            ("groups_config", {"enable_groups": False}),
            ("user_linking", {"enable_user_linking": False, "require_existing_user": True}),
        )
        for expected, payload in steps:
            if not isinstance(flow, dict) or flow.get("type") != "form" or flow.get("step_id") != expected or flow.get("errors"):
                raise ApplianceError(f"OIDC setup stopped at {expected}; inspect the HA integration UI")
            flow = request("POST", path, payload)
        if not isinstance(flow, dict) or flow.get("type") != "create_entry":
            raise ApplianceError("Home Assistant did not create the OIDC configuration entry")
        return {"configured": True, "automatic_linking": False, "require_existing_user": True}
    except ApplianceError as exc:
        try:
            request("DELETE", path)
        except ApplianceError as cleanup:
            raise ApplianceError(f"{exc}; could not remove the unfinished configuration flow: {cleanup}") from exc
        raise
