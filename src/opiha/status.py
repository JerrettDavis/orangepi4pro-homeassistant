from __future__ import annotations
import json
import os
from pathlib import Path
import platform
import shutil
import socket
import time
import urllib.error
import urllib.request
from .common import ApplianceError, read_json


def responding(url: str) -> bool:
    # Do not weaken TLS verification for a restored HTTPS installation.
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/", timeout=2) as r:
            return 200 <= r.status < 500
    except urllib.error.HTTPError as e:
        return e.code in (401, 403)
    except (OSError, ValueError):
        return False


def vision_status(directory: Path, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    try:
        v = read_json(directory / "vision.json")
    except ApplianceError:
        return {"available": False, "person": False, "reason": "not_running"}
    age = now - float(v.get("timestamp", 0))
    available = bool(v.get("available")) and 0 <= age < 15
    return {"available": available, "person": bool(v.get("person")) if available else False,
            "age_seconds": round(max(0, age), 1), "backend": "opencv-hog-cpu",
            "detections": v.get("detections", 0) if available else 0,
            "inference_ms": v.get("inference_ms")}


def snapshot(cfg: dict) -> dict:
    stat = shutil.disk_usage(cfg["data_dir"])
    return {"schema": 1, "homeassistant": {"responding": responding(cfg["ha_url"])},
            "mode": cfg["mode"], "vision": vision_status(Path(cfg["status_dir"])),
            "storage": {"free_bytes": stat.free, "total_bytes": stat.total}}


def doctor(cfg: dict) -> dict:
    tools = {name: shutil.which(name) is not None for name in ("docker", "age", "openssl", "systemctl", "v4l2-ctl", "ffmpeg")}
    return {"architecture": platform.machine(), "kernel": platform.release(), "mode": cfg["mode"],
            "tools": tools, "usb_serial_candidates": [str(p) for p in Path("/dev/serial/by-id").glob("*")],
            "video_candidates": [str(p) for p in Path("/dev/v4l/by-id").glob("*")],
            "npu_device_present": Path("/dev/galcore").exists(),
            "npu_backend_implemented": False,
            "warnings": ["Hardware detection is not a driver or inference validation",
                         "Local reports may contain device serial identifiers; do not publish them"]}


def live_check(url: str, token_file: Path) -> dict:
    token = token_file.read_text().strip()
    if not token or any(x in token for x in "\r\n"):
        raise ApplianceError("Invalid token file")
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = urllib.request.build_opener(NoRedirect())
    def get(path: str):
        req = urllib.request.Request(url.rstrip("/") + path,
                                     headers={"Authorization": "Bearer " + token})
        try:
            with opener.open(req, timeout=20) as response:
                return json.load(response)
        except (OSError, ValueError) as exc:
            raise ApplianceError("HA API request failed; check URL, TLS and private token file") from exc
    config = get("/api/config")
    states = get("/api/states")
    return {"version": config.get("version"), "state_count": len(states),
            "unavailable": sorted(s["entity_id"] for s in states if s["state"] == "unavailable"),
            "unknown": sorted(s["entity_id"] for s in states if s["state"] == "unknown"),
            "note": "Unavailable sleeping/disabled devices may be expected; compare before and after cutover"}
