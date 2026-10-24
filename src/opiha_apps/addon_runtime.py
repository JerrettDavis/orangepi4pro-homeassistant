"""Turn a frozen add-on manifest into a catalog entry, validated options and a container spec.

The manifest is administrator-added repository content. Every privilege it asks for is listed by
`addons.report` and must be named in the install's `grants`; nothing is granted implicitly.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
from . import addons
from .common import AppError, atomic, checked_path, write_json

ARCH_NAME = "aarch64"
# Same addressing as the Supervisor: the host side of the bridge is 172.30.32.2, so add-ons that allow only
# that address (their ingress nginx configs do) accept the traffic, and `supervisor` resolves where they expect.
NETWORK = "opiha-addons"
SUPERVISOR_IP = "172.30.32.2"
NETWORK_ARGS = ["--subnet", "172.30.32.0/23", "--gateway", SUPERVISOR_IP, "--ip-range", "172.30.33.0/24",
                "-o", "com.docker.network.bridge.name=opihaadd0"]
DEFAULT_BASE = "ghcr.io/home-assistant/{arch}-base:latest"
# Docker's default capability set minus NET_RAW. Root add-ons need these to start their services.
BASE_CAPS = ["CHOWN", "DAC_OVERRIDE", "FOWNER", "FSETID", "KILL", "SETGID", "SETUID", "SETPCAP",
             "SYS_CHROOT", "MKNOD", "AUDIT_WRITE", "SETFCAP", "NET_BIND_SERVICE"]
RESERVED_LAN_PORTS = {22, 80, 443, 3389, 5900, 8098, 8123, 18123}
SHARED = {"share": "/share", "media": "/media", "ssl": "/ssl", "backup": "/backup", "addons": "/addons"}
CONFIG_TYPES = {"config", "homeassistant_config"}
MAX_SOURCE_BYTES = 150 * 1024 * 1024


def slug_for(repo_id: str, manifest_slug: str) -> str:
    return ("x" + repo_id[:6] + "-" + re.sub(r"[^a-z0-9-]", "-", manifest_slug.lower()))[:32].rstrip("-")


# Loopback ports the reviewed apps and the manager already use.
RESERVED_UI_PORTS = {21880, 26052, 21984, 21883, 28091, 28554, 23000}


def _ui_port(slug: str) -> int:
    port = 22000 + int(hashlib.sha256(slug.encode()).hexdigest(), 16) % 7000
    while port in RESERVED_UI_PORTS:
        port += 1
    return port


def image_repository(manifest: dict) -> str | None:
    if not manifest["image"]:
        return None
    return manifest["image"].replace("{arch}", ARCH_NAME).split(":", 1)[0]


def hostname(repo_url: str, manifest_slug: str) -> str:
    """The name other add-ons use for this one, spelled as the Supervisor spells it."""
    official = repo_url.rstrip("/") in {"https://github.com/home-assistant/addons", ""}
    prefix = "core" if official else hashlib.sha1(repo_url.lower().encode()).hexdigest()[:8]
    return (prefix + "-" + manifest_slug).replace("_", "-").lower()[:63]


def entry_from(manifest: dict, repo_id: str, folder: str, repo_url: str = "") -> dict:
    slug = slug_for(repo_id, manifest["slug"])
    dynamic = bool(manifest["ingress"] and manifest["ingress_port"] == 0)
    container_port = _ui_port(slug) if dynamic else manifest["ingress_port"] if manifest["ingress"] else 0
    if not container_port and manifest["webui"]:
        match = re.search(r"\[PORT:(\d+)\]", manifest["webui"])
        container_port = int(match[1]) if match else 0
    return {
        "name": manifest["name"], "summary": manifest["description"][:300],
        "repository": image_repository(manifest) or "local-build/" + slug, "version": manifest["version"],
        "digest": None, "memory_mib": 512, "container_port": container_port, "port": _ui_port(slug),
        "uid": 0, "mount": "/data", "icon": manifest["panel_icon"] if isinstance(manifest["panel_icon"], str) else "mdi:puzzle",
        "category": "Add-on", "ingress": bool(manifest["ingress"] and container_port), "source": manifest["url"],
        "notes": "Unreviewed add-on from a repository you added. Its code, image and web UI must be trusted.",
        "addon": True, "build": not manifest["image"], "repo": repo_id, "folder": folder, "manifest": manifest,
        "radio": False, "slug": slug, "dynamic_ingress": dynamic, "hostname": hostname(repo_url, manifest["slug"]),
        "repo_url": repo_url,
    }


def _default_host_ports(manifest: dict) -> dict:
    return {f"{p['container']}/{p['protocol']}": p["default_host"] if p["default_host"] is not None else None
            for p in manifest["ports"] if p["default_host"] is not None}


def defaults(app: dict) -> dict:
    m = app["manifest"]
    host_ports = {k: 20000 + (v % 10000) for k, v in _default_host_ports(m).items()}
    return {"version": app["version"], "memory_mib": app["memory_mib"], "cpu_shares": 512, "autostart": False,
            "port": app["port"], "device": "", "radio_reviewed": False, "config": addons.default_options(m),
            "grants": [], "host_ports": host_ports, "lan": False, "devices": list(m["devices"])}


def required_grants(manifest: dict) -> list[str]:
    return [p["id"] for p in addons.report(manifest)["privileges"]]


def options(app: dict, supplied: dict | None) -> dict:
    from .catalog import ADDON_OPTIONS
    m = app["manifest"]
    supplied = {} if supplied is None else supplied
    if not isinstance(supplied, dict) or set(supplied) - ADDON_OPTIONS:
        raise AppError("Unsupported add-on options (no arbitrary images, mounts, commands or environment)")
    result = {**defaults(app), **supplied}
    if not isinstance(result["version"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.+-]{0,63}", result["version"]):
        raise AppError("Invalid add-on version")
    for key, lo, hi in (("memory_mib", 128, 32768), ("cpu_shares", 64, 1024), ("port", 20000, 29999)):
        if type(result[key]) is not int or not lo <= result[key] <= hi:
            raise AppError("Invalid add-on memory, CPU weight or port")
    for key in ("autostart", "lan"):
        if type(result[key]) is not bool:
            raise AppError("Add-on switches must be booleans")
    if result["device"] != "" or result["radio_reviewed"] is not False:
        raise AppError("Add-ons select hardware through 'devices' and 'grants'")
    if result["memory_mib"] < app["memory_mib"]:
        raise AppError("Memory ceiling is below the add-on's starting budget")
    grants, known = result["grants"], set(required_grants(m))
    if not isinstance(grants, list) or not all(isinstance(g, str) for g in grants) or set(grants) - known:
        raise AppError("Unknown privilege grant")
    result["grants"] = sorted(set(grants))
    ports = result["host_ports"]
    published = {k for k in _default_host_ports(m)}
    if not isinstance(ports, dict) or set(ports) - published:
        raise AppError("Unknown add-on port mapping")
    for key, host in ports.items():
        low, high = (1024, 65535) if result["lan"] else (20000, 29999)
        if type(host) is not int or not low <= host <= high or (result["lan"] and host in RESERVED_LAN_PORTS):
            raise AppError("Add-on host port is out of range or reserved" + ("" if result["lan"] else " (loopback ports use 20000-29999)"))
    if len(set(ports.values())) != len(ports):
        raise AppError("Two add-on ports map to the same host port")
    devices = result["devices"]
    if not isinstance(devices, list) or len(devices) > 16 or not all(
            isinstance(d, str) and (d in m["devices"] or re.fullmatch(r"/dev/serial/by-id/[A-Za-z0-9_.:+-]{1,240}", d)) for d in devices):
        raise AppError("Devices must be ones the add-on declares or a persistent serial-by-id path")
    result["devices"] = sorted(set(devices))
    if m["schema"] is False:
        if result["config"] not in ({}, None):
            raise AppError("This add-on takes no options")
        result["config"] = {}
    else:
        result["config"] = addons.validate_options(m["schema"], result["config"])
    return result


def check_grants(app: dict, opts: dict) -> None:
    missing = [p["label"] for p in addons.report(app["manifest"])["privileges"] if p["id"] not in opts["grants"]]
    if missing:
        raise AppError("Approve these privileges to continue: " + "; ".join(missing))
    blocked = addons.report(app["manifest"])["blocked"]
    if blocked:
        raise AppError("Unsupported on this appliance: " + "; ".join(blocked))


def build_args(manifest: dict, source: Path) -> dict:
    base = DEFAULT_BASE
    for name in ("build.yaml", "build.yml", "build.json"):
        if (source / name).is_file():
            doc = addons.read_document(source / name)
            table = doc.get("build_from")
            if isinstance(table, dict) and isinstance(table.get(ARCH_NAME), str):
                base = table[ARCH_NAME]
            args = doc.get("args") if isinstance(doc.get("args"), dict) else {}
            break
    else:
        args = {}
    base = base.replace("{arch}", ARCH_NAME)
    if not re.fullmatch(r"[a-z0-9][A-Za-z0-9._/:@-]{0,200}", base):
        raise AppError("The add-on's base image reference is not acceptable")
    result = {"BUILD_FROM": base, "BUILD_VERSION": manifest["version"], "BUILD_ARCH": ARCH_NAME}
    for key, value in args.items():
        if isinstance(key, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,40}", key) and isinstance(value, (str, int, float)) and re.fullmatch(r"[A-Za-z0-9._:/@+-]{0,200}", str(value)):
            result.setdefault(key, str(value))
    return result


def copy_source(src: Path, dest: Path) -> None:
    """Copy an add-on directory as inert build input: regular files only, size bounded."""
    total = 0
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d != ".git"]
        for name in files:
            p = Path(root) / name
            info = p.lstat()
            if p.is_symlink() or not p.is_file():
                continue
            total += info.st_size
            if total > MAX_SOURCE_BYTES:
                raise AppError("Add-on source is larger than 150 MiB")
            target = checked_path(dest / p.relative_to(src))
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            atomic(target, p.read_bytes(), 0o644)


def tree_hash(path: Path) -> str:
    """Content hash of an add-on directory so an approved plan builds exactly what was reviewed."""
    h, total = hashlib.sha256(), 0
    for root, dirs, files in os.walk(path):
        dirs[:] = sorted(d for d in dirs if d != ".git")
        for name in sorted(files):
            p = Path(root) / name
            if p.is_symlink() or not p.is_file():
                continue
            total += p.stat().st_size
            if total > MAX_SOURCE_BYTES:
                raise AppError("Add-on source is larger than 150 MiB")
            h.update(p.relative_to(path).as_posix().encode() + b"\x00")
            h.update(hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()


def map_host(mgr, slug: str, kind: str) -> Path:
    root = mgr.app_dir(slug)
    if kind in CONFIG_TYPES:
        if mgr.ha_config is None:
            raise AppError("The Home Assistant configuration directory is not known to the manager")
        return checked_path(mgr.ha_config)
    if kind == "addon_config":
        return checked_path(root / "addon_config")
    if kind == "all_addon_configs":
        return checked_path(mgr.root / "shared" / "addon_configs")
    return checked_path(mgr.root / "shared" / kind)


def default_target(kind: str) -> str:
    if kind == "homeassistant_config":
        return "/homeassistant"
    if kind in {"config", "addon_config"}:
        return "/config"
    if kind == "all_addon_configs":
        return "/addon_configs"
    return SHARED[kind]


def spec(mgr, slug: str, record: dict) -> dict:
    from . import catalog
    app = catalog.entry(slug)
    m, opts = app["manifest"], catalog.options(slug, record["options"])
    check_grants(app, opts)
    root = mgr.app_dir(slug)
    mounts, seen = [(str(checked_path(root / "data")), "/data", False)], {"/data"}
    for e in m["map"]:
        if e["type"] == "data":
            continue
        host = map_host(mgr, slug, e["type"])
        host.mkdir(parents=True, exist_ok=True, mode=0o700)
        target = e["path"] or default_target(e["type"])
        if target in seen:
            raise AppError("Two directory maps use the same container path " + target)
        seen.add(target)
        mounts.append((str(host), target, e["read_only"]))
    host_net = "host_network" in opts["grants"]
    published = {int(k.split("/")[0]) for k in opts["host_ports"] if k.endswith("/tcp")}
    ports = [] if host_net else [(h, int(k.split("/")[0])) for k, h in sorted(opts["host_ports"].items()) if k.endswith("/tcp")]
    udp = [] if host_net else [(h, int(k.split("/")[0])) for k, h in sorted(opts["host_ports"].items()) if k.endswith("/udp")]
    loopback = [] if host_net or app["ingress"] or not app["container_port"] or app["container_port"] in published else [(opts["port"], app["container_port"])]
    environment = dict(m["environment"])
    caps = list(BASE_CAPS) + (m["privileged"] if "capabilities" in opts["grants"] else [])
    result = {**opts, "uid": 0, "user": "0:0", "image": record["image"],
              "network": "host" if host_net else NETWORK, "ports": ports, "udp_ports": udp,
              "aliases": [] if host_net else [app["hostname"]],
              "loopback_ports": loopback, "bind": "0.0.0.0" if opts["lan"] else "127.0.0.1",
              "mounts": mounts, "environment": environment, "command": [], "cap_add": sorted(set(caps)),
              "privileged_mode": "full_access" in opts["grants"], "init": m["init"] is not False,
              "tmpfs": m["tmpfs"], "env_file": str(checked_path(root / "private.env")),
              "devices": [d for d in opts["devices"] if os.path.exists(d)] if "devices" in opts["grants"] else [],
              "extra_hosts": [("supervisor", SUPERVISOR_IP)]}
    return result


def write_options(mgr, slug: str, opts: dict) -> None:
    data = checked_path(mgr.app_dir(slug) / "data")
    data.mkdir(mode=0o700, exist_ok=True)
    atomic(data / "options.json", (json.dumps(opts["config"], indent=2) + "\n").encode(), 0o600)


def seed(mgr, slug: str, opts: dict) -> None:
    root = mgr.app_dir(slug)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    (root / "data").mkdir(mode=0o700, exist_ok=True)
    (root / "addon_config").mkdir(mode=0o700, exist_ok=True)
    if not (root / "private.env").exists():
        token = secrets.token_hex(32)
        atomic(root / "private.env", f"SUPERVISOR_TOKEN={token}\nHASSIO_TOKEN={token}\n".encode())
    write_options(mgr, slug, opts)


def token(mgr, slug: str) -> str | None:
    p = mgr.app_dir(slug) / "private.env"
    if not p.is_file():
        return None
    match = re.search(r"(?m)^SUPERVISOR_TOKEN=([0-9a-f]{64})$", p.read_text())
    return match[1] if match else None


def save_addon(mgr, slug: str, raw: dict, repo_id: str, folder: str, repo_url: str = "") -> None:
    """Freeze the manifest the administrator approved; it, not the live repository, drives later starts."""
    write_json(mgr.app_dir(slug) / "addon.json", {"schema": 1, "raw": raw, "repo": repo_id, "folder": folder, "url": repo_url})


def load_addon(path: Path) -> dict:
    from .common import read_json
    doc = read_json(path)
    if set(doc) != {"schema", "raw", "repo", "folder", "url"} or doc["schema"] != 1 or not isinstance(doc["raw"], dict) or not isinstance(doc["url"], str):
        raise AppError("Invalid add-on record")
    return entry_from(addons.parse(doc["raw"], repository=doc["repo"]), doc["repo"], doc["folder"], doc["url"])
