from __future__ import annotations
import copy
import os
from pathlib import Path
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from .common import ApplianceError, COMPONENTS, REPO, atomic_json, guarded_root, private_mkdir, read_json

DEFAULT_IMAGES = {
    "homeassistant": "ghcr.io/home-assistant/home-assistant:2026.9.3",
    "zwave": "zwavejs/zwave-js-ui:11.24.1",
    "mqtt": "eclipse-mosquitto:2.0.22",
    "camera": "alexxit/go2rtc:1.9.14",
}


def default_config(mode: str, directory: Path) -> dict:
    directory = directory.resolve()
    return {
        "schema": 1, "mode": mode,
        "data_dir": str(directory / "state") if mode == "lab" else "/srv/opiha",
        "work_dir": str(directory / "runtime") if mode == "lab" else "/var/lib/opiha",
        "status_dir": str(directory / "status") if mode == "lab" else "/run/opiha/status",
        "timezone": "Etc/UTC", "ha_version": "2026.9.3", "images": copy.deepcopy(DEFAULT_IMAGES),
        "features": {"zwave": False, "mqtt": False, "camera": False},
        "zwave_device": "", "camera_device": "",
        "ha_url": "http://127.0.0.1:18123" if mode == "lab" else "http://127.0.0.1:8123",
        "dashboard_path": "/lovelace", "lab_port": 18123,
        "camera": {"width": 640, "height": 480, "fps": 5, "input_format": "mjpeg"},
        "vision": {"fps": 1, "hold_seconds": 20, "hit_count": 2, "threshold": 0.6},
    }


def validate(cfg: dict) -> dict:
    if cfg.get("schema") != 1 or cfg.get("mode") not in ("lab", "appliance"):
        raise ApplianceError("Unsupported configuration schema/mode")
    for key in ("data_dir", "work_dir", "status_dir"):
        if any(c in cfg[key] for c in "$\n\r"):
            raise ApplianceError(f"{key} contains unsafe Compose interpolation/control characters")
        if not Path(cfg[key]).is_absolute():
            raise ApplianceError(f"{key} must be absolute")
        guarded_root(Path(cfg[key]))
    roots = [Path(cfg[x]).resolve() for x in ("data_dir", "work_dir", "status_dir")]
    for a in roots:
        for b in roots:
            if a != b and a in b.parents:
                raise ApplianceError("Data, work and status directories must not contain one another")
    if len(set(roots)) != 3:
        raise ApplianceError("Data, work and status directories must be distinct")
    try:
        ZoneInfo(cfg["timezone"])
    except (ZoneInfoNotFoundError, ValueError):
        raise ApplianceError("Unknown timezone (install tzdata on Windows or use WSL)")
    if not re.fullmatch(r"[0-9]{4}\.[0-9]{1,2}\.[0-9]+", cfg.get("ha_version", "")):
        raise ApplianceError("ha_version must be an explicit stable release such as 2026.9.3")
    if set(cfg.get("images", {})) != set(DEFAULT_IMAGES):
        raise ApplianceError("Expected four named container image references")
    for value in cfg["images"].values():
        if not re.fullmatch(r"[a-zA-Z0-9_./:@-]+", value) or not (":" in value):
            raise ApplianceError("Invalid image reference")
        if value.endswith((":latest", ":stable", ":master")):
            raise ApplianceError("Floating image tags are not allowed; use a release tag or digest")
    if set(cfg.get("features", {})) != {"zwave", "mqtt", "camera"}:
        raise ApplianceError("Unknown/missing feature")
    if any(type(v) is not bool for v in cfg["features"].values()):
        raise ApplianceError("Feature switches must be booleans")
    for key in ("zwave_device", "camera_device"):
        value = cfg.get(key, "")
        if value and (not value.startswith("/dev/") or ".." in Path(value).parts or any(c in value for c in "\n\r:$")):
            raise ApplianceError(f"Invalid {key}")
    if cfg["features"]["zwave"] and not cfg["zwave_device"].startswith("/dev/serial/by-id/"):
        raise ApplianceError("Z-Wave requires a persistent /dev/serial/by-id path")
    if cfg["features"]["camera"] and not cfg["camera_device"]:
        raise ApplianceError("Select a camera device before enabling camera")
    parsed = urlsplit(cfg["ha_url"])
    if parsed.scheme not in ("http", "https") or parsed.hostname not in ("127.0.0.1", "localhost", "::1") or parsed.username or parsed.password:
        raise ApplianceError("ha_url must be a credential-free loopback HTTP(S) URL")
    if not cfg["dashboard_path"].startswith("/") or cfg["dashboard_path"].startswith("//"):
        raise ApplianceError("Dashboard path must be local")
    if not 1024 <= cfg["lab_port"] <= 65535:
        raise ApplianceError("Lab port must be between 1024 and 65535")
    camera = cfg["camera"]
    if camera["input_format"] not in ("mjpeg", "yuyv422", "h264"):
        raise ApplianceError("Unsupported camera input format")
    if not (160 <= camera["width"] <= 1920 and 128 <= camera["height"] <= 1080 and 1 <= camera["fps"] <= 30):
        raise ApplianceError("Camera dimensions/rate are outside supported limits")
    v = cfg["vision"]
    if not (0.1 <= v["fps"] <= 5 and 1 <= v["hold_seconds"] <= 300 and 1 <= v["hit_count"] <= 10 and 0 <= v["threshold"] <= 5):
        raise ApplianceError("Invalid vision parameters")
    return cfg


def load(path: Path) -> dict:
    return validate(read_json(path))


def initialize(path: Path, mode: str, data_dir: str | None = None) -> dict:
    if path.exists():
        raise ApplianceError("Configuration already exists; use configure instead")
    cfg = default_config(mode, path.parent)
    if data_dir:
        cfg["data_dir"] = str(Path(data_dir).resolve())
    validate(cfg)
    data = Path(cfg["data_dir"])
    if data.exists() and any(data.iterdir()):
        raise ApplianceError("Initialization requires an empty data directory")
    private_mkdir(path.parent)
    create_state(data)
    private_mkdir(Path(cfg["work_dir"]))
    atomic_json(path, cfg)
    return cfg


def create_state(data: Path) -> None:
    guarded_root(data)
    private_mkdir(data)
    for component in COMPONENTS:
        private_mkdir(data / component)
    atomic_json(data / ".opiha-state.json", {"schema": 1})


def ensure_state(cfg: dict) -> Path:
    data = guarded_root(Path(cfg["data_dir"]))
    if not (data / ".opiha-state.json").is_file():
        raise ApplianceError("Not an initialized OPIHA state directory")
    for name in COMPONENTS:
        if (data / name).is_symlink():
            raise ApplianceError("Managed component is a symlink")
    return data


def seed(cfg: dict) -> None:
    data = ensure_state(cfg)
    if (data / "ha/configuration.yaml").exists() or (data / "ha/.storage").exists():
        return
    import shutil
    shutil.copytree(REPO / "homeassistant", data / "ha", dirs_exist_ok=True)
    # Optional HACS software is only seeded into a fresh configuration.
    from .vendor import seed_hacs
    seed_hacs(data / "ha")


def portable_settings(cfg: dict) -> dict:
    return {k: copy.deepcopy(cfg[k]) for k in ("timezone", "ha_version", "images", "features", "zwave_device", "camera_device", "camera", "vision", "dashboard_path")}
