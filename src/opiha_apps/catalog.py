"""Reviewed native-container adapters. This is NOT a Supervisor manifest translator.

Repositories and host capabilities are code-reviewed here, never supplied by a browser.
The reviewed release is pinned to its multi-arch index digest (ARM64 and AMD64 verified); an
explicitly selected other tag is pulled for the native architecture and then locked to its
resolved content digest before container creation. See docs/native-apps/COMPATIBILITY.md.
"""
from __future__ import annotations
import contextlib
import copy
import re
import threading
from .common import AppError

PREFIX = "/api/opiha_apps/ingress/"
CATALOG = {
    "nodered": {
        "name": "Node-RED", "summary": "Flow-based automation, with its editor inside Home Assistant.",
        "repository": "nodered/node-red", "version": "5.0.7", "digest": "sha256:a649dd711d55490151a2c39a8e48ad0c44325488fbc0e66315f2d2e19e5e1ace", "memory_mib": 768,
        "container_port": 1880, "port": 21880, "uid": 1000, "mount": "/data",
        "icon": "mdi:source-branch", "category": "Automation", "ingress": True,
        "source": "https://nodered.org/docs/getting-started/docker",
        "notes": "Install the Home Assistant WebSocket nodes through Manage palette, then configure HA explicitly. No Supervisor token is fabricated.",
    },
    "esphome": {
        "name": "ESPHome", "summary": "Build, edit and wirelessly deploy ESP firmware.",
        "repository": "ghcr.io/esphome/esphome", "version": "2026.9.0", "digest": "sha256:f6509fcf917a732fd80058567b237d5b9286b9dc6c8dde1b655fbb69ebd600ad", "memory_mib": 1536,
        "container_port": 6052, "port": 26052, "uid": 0, "mount": "/config",
        "icon": "mdi:chip", "category": "Devices", "ingress": True,
        "source": "https://esphome.io/guides/getting_started_command_line/",
        "notes": "Compile parallelism is requested at one process; measure the selected builder release under load. Bridged networking uses ping/manual IP rather than multicast discovery. Initial USB flashing remains a separately reviewed hardware step.",
    },
    "go2rtc": {
        "name": "go2rtc", "summary": "On-demand camera restreaming without requiring a working local CSI driver.",
        "repository": "alexxit/go2rtc", "version": "1.9.14", "digest": "sha256:675c318b23c06fd862a61d262240c9a63436b4050d177ffc68a32710d9e05bae", "memory_mib": 256,
        "container_port": 1984, "port": 21984, "uid": 0, "mount": "/config",
        "icon": "mdi:cctv", "category": "Camera", "ingress": True,
        "source": "https://github.com/AlexxIT/go2rtc",
        "notes": "Starts with no streams. RTSP is loopback-only on port 28554. No camera device, encoder or NPU is assumed. Browser WebRTC transport is not enabled by this adapter.",
    },
    "mosquitto": {
        "name": "Mosquitto", "summary": "Authenticated MQTT broker for HA and native apps.",
        "repository": "eclipse-mosquitto", "version": "2.0.22", "digest": "sha256:199ea8ef2e35ec2b1b37e59cfd1dbae538ed4dfa4a2251a121a52215a6248a21", "memory_mib": 128,
        "container_port": 1883, "port": 21883, "uid": 1883, "mount": "/mosquitto",
        "icon": "mdi:hub-outline", "category": "Infrastructure", "ingress": False,
        "source": "https://hub.docker.com/_/eclipse-mosquitto",
        "notes": "Local clients connect to 127.0.0.1:21883; apps on the managed Docker network use opiha-apps-mosquitto:1883. No unauthenticated LAN listener.",
    },
    "zwave": {
        "name": "Z-Wave JS UI", "summary": "Native USB radio ownership and the Z-Wave JS server.",
        "repository": "zwavejs/zwave-js-ui", "version": "11.24.1", "digest": "sha256:00abebce88205b47c3b611e983bbc692753170e3603c691bc5765f82265cafa4", "memory_mib": 768,
        "container_port": 8091, "port": 28091, "uid": 1000, "mount": "/usr/src/app/store",
        "icon": "mdi:z-wave", "category": "Devices", "ingress": False, "radio": True,
        "source": "https://zwave-js.github.io/zwave-js-ui/#/getting-started/docker",
        "notes": "Existing opiha Z-Wave stays externally managed. New managed instance is start-gated until the stopped store, original keys and controller have been reviewed. UI uses a separately secured reverse proxy/SSH tunnel, not generic ingress rewriting.",
    },
}

COMMON_OPTIONS = {"version", "memory_mib", "cpu_shares", "autostart", "port", "device", "radio_reviewed"}
ADDON_OPTIONS = COMMON_OPTIONS | {"config", "grants", "host_ports", "lan", "devices"}

# Add-ons from administrator-added repositories, registered from their frozen manifests.
# The reviewed CATALOG above always wins and cannot be shadowed.
DYNAMIC: dict[str, dict] = {}
_LOCK = threading.Lock()  # guards DYNAMIC mutation/snapshots only; never held across a yield or I/O
_LOCAL = threading.local()  # per-thread plan/job overrides, invisible to other threads


def register(slug: str, app: dict) -> None:
    if slug in CATALOG:
        raise AppError("Add-on slug collides with a reviewed application")
    with _LOCK:
        DYNAMIC[slug] = copy.deepcopy(app)


@contextlib.contextmanager
def override(slug: str, app: dict):
    """Resolve `slug` to `app` for the calling thread only, without installing it or blocking anyone."""
    if slug in CATALOG:
        raise AppError("Add-on slug collides with a reviewed application")
    table = getattr(_LOCAL, "table", None)
    if table is None:
        table = _LOCAL.table = {}
    previous = table.get(slug)
    table[slug] = copy.deepcopy(app)
    try:
        yield
    finally:
        if previous is None:
            table.pop(slug, None)
        else:
            table[slug] = previous


def _dynamic(slug) -> dict | None:
    if not isinstance(slug, str):
        return None
    local = getattr(_LOCAL, "table", None)
    if local and slug in local:
        return local[slug]
    with _LOCK:
        return DYNAMIC.get(slug)


def forget(slug: str) -> None:
    with _LOCK:
        DYNAMIC.pop(slug, None)


def clear_dynamic() -> None:
    with _LOCK:
        DYNAMIC.clear()


def is_addon(slug: str) -> bool:
    return _dynamic(slug) is not None


def _snapshot() -> dict[str, dict]:
    with _LOCK:
        return dict(DYNAMIC)


def all_slugs() -> list[str]:
    return [*CATALOG, *_snapshot()]


def entry(slug: str) -> dict:
    if isinstance(slug, str) and slug in CATALOG:
        return copy.deepcopy(CATALOG[slug])
    app = _dynamic(slug)
    if app is not None:
        return copy.deepcopy(app)
    raise AppError("Unknown application; only the reviewed catalog and added repositories are accepted")


def wanted_ports(slug: str, opts: dict) -> set[int]:
    """Host ports an app will bind, for conflict checks."""
    if is_addon(slug):
        extra = set(opts["host_ports"].values())
        app = _dynamic(slug)
        return {opts["port"]} | extra if app.get("container_port") and not app.get("ingress") else extra
    return {opts["port"]} | ({28554} if slug == "go2rtc" else {23000} if slug == "zwave" else set())


def options(slug: str, supplied: dict | None = None) -> dict:
    if is_addon(slug):
        from . import addon_runtime
        return addon_runtime.options(entry(slug), supplied)
    app = entry(slug)
    supplied = {} if supplied is None else supplied
    if not isinstance(supplied, dict) or set(supplied) - COMMON_OPTIONS:
        raise AppError("Unsupported app options (no arbitrary images, mounts, commands or environment)")
    result = {"version": app["version"], "memory_mib": app["memory_mib"],
              "cpu_shares": 512, "autostart": False, "port": app["port"],
              "device": "", "radio_reviewed": False, **supplied}
    if not isinstance(result["version"], str) or not re.fullmatch(r"[0-9][A-Za-z0-9_.-]{0,79}", result["version"]):
        raise AppError("Select an explicit release tag from the adapter's fixed upstream repository")
    for key, lo, hi in (("memory_mib", 128, 32768), ("cpu_shares", 64, 1024), ("port", 20000, 29999)):
        if type(result[key]) is not int or not lo <= result[key] <= hi:
            raise AppError("Invalid app memory, CPU weight or port")
    for key in ("autostart", "radio_reviewed"):
        if type(result[key]) is not bool:
            raise AppError("App switches must be booleans")
    device = result["device"]
    if not isinstance(device, str) or (device and not re.fullmatch(r"/dev/serial/by-id/[A-Za-z0-9_.:+-]{1,240}", device)):
        raise AppError("Only a persistent serial-by-id device can be selected")
    if device and not app.get("radio"):
        raise AppError("This app adapter has no hardware-device capability")
    if result["radio_reviewed"] and not app.get("radio"):
        raise AppError("Radio review is only meaningful for a radio adapter")
    if result["memory_mib"] < app["memory_mib"]:
        raise AppError("Memory ceiling is below the adapter's starting budget")
    return result


def public_catalog() -> list[dict]:
    rows = [{"id": slug, **copy.deepcopy(app), "defaults": options(slug), "kind": "reviewed",
             "compatibility": "native-container-adapter", "hardware_validated": False}
            for slug, app in CATALOG.items()]
    from . import addon_runtime
    rows += [{"id": slug, **copy.deepcopy(app), "defaults": addon_runtime.defaults(app), "kind": "addon",
              "compatibility": "unreviewed-addon", "hardware_validated": False}
             for slug, app in _snapshot().items()]
    return rows


def image(slug: str, opts: dict) -> str:
    """The reviewed release is pulled by its multi-arch index digest; other tags remain tag-only until locked."""
    app, version = entry(slug), options(slug, opts)["version"]
    if app.get("build"):
        return "local-build:" + slug
    reference = app["repository"] + ":" + version
    return reference + "@" + app["digest"] if app["digest"] and version == app["version"] else reference
