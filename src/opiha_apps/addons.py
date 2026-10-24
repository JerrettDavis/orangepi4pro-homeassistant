"""Home Assistant add-on manifests without the Supervisor.

Pure parsing and judgement: nothing here touches Docker, the network or the filesystem
except reading a manifest file. A manifest comes from a repository the administrator added,
so every field is validated and nothing is trusted to be well formed.
"""
from __future__ import annotations
import ipaddress
import json
from pathlib import Path
import re
from .common import AppError

MANIFEST_NAMES = ("config.yaml", "config.yml", "config.json")
MAX_MANIFEST = 256 * 1024
ARCH = "aarch64"
SLUG = re.compile(r"[A-Za-z0-9_-]{1,64}")
MAPS = {"config", "ssl", "addons", "backup", "share", "media", "homeassistant_config",
        "all_addon_configs", "addon_config", "data"}
# Home Assistant renamed add-ons to "apps" and the map types with them; both spellings are in the wild.
MAP_ALIASES = {"app_config": "addon_config", "all_app_configs": "all_addon_configs", "local_apps": "addons"}
ROLES = {"default", "homeassistant", "backup", "manager", "admin"}
DANGEROUS_PRIVILEGES = {"NET_ADMIN", "SYS_ADMIN", "SYS_RAWIO", "SYS_PTRACE", "SYS_RESOURCE",
                        "IPC_LOCK", "DAC_READ_SEARCH", "SYS_MODULE", "SYS_TIME", "NET_RAW", "NET_BIND_SERVICE", "SYS_NICE"}


def _load_yaml(text: str):
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - the appliance image ships python3-yaml
        raise AppError("PyYAML is required to read add-on manifests") from exc
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise AppError("Add-on manifest is not valid YAML") from exc


def read_document(path: Path) -> dict:
    """Read one YAML/JSON file as a mapping, bounded in size."""
    try:
        if path.is_symlink() or path.stat().st_size > MAX_MANIFEST:
            raise AppError("Add-on file is a symlink or exceeds its size limit")
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise AppError("Cannot read the add-on file") from exc
    value = json.loads(text) if path.suffix == ".json" else _load_yaml(text)
    if not isinstance(value, dict):
        raise AppError("Add-on file must contain a mapping")
    return value


def find_manifest(directory: Path) -> Path | None:
    return next((directory / n for n in MANIFEST_NAMES if (directory / n).is_file()), None)


def _text(value, field: str, limit: int = 500) -> str:
    if not isinstance(value, str) or not value or len(value) > limit or "\x00" in value:
        raise AppError(f"Add-on field '{field}' must be a short string")
    return value


def _port(value) -> int:
    if type(value) is not int or not 1 <= value <= 65535:
        raise AppError("Add-on declares an invalid port")
    return value


def parse_ports(raw) -> list[dict]:
    """`ports: {"8080/tcp": 8080}` — a null host port means the add-on does not publish it."""
    if raw is None:
        return []
    if not isinstance(raw, dict) or len(raw) > 32:
        raise AppError("Add-on 'ports' must be a mapping")
    result = []
    for key, host in raw.items():
        match = re.fullmatch(r"(\d{1,5})/(tcp|udp)", str(key))
        if not match:
            raise AppError("Add-on port keys must look like 8080/tcp")
        result.append({"container": _port(int(match[1])), "protocol": match[2],
                       "default_host": None if host is None else _port(host)})
    return result


def parse_map(raw) -> list[dict]:
    """Both `["config:rw", "ssl"]` and `[{"type": "config", "read_only": false, "path": "/x"}]` appear upstream."""
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > 16:
        raise AppError("Add-on 'map' must be a list")
    result = []
    for item in raw:
        if isinstance(item, str):
            name, _, mode = item.partition(":")
            row = {"type": name, "read_only": mode != "rw" if mode else True, "path": None}
            if mode not in {"", "ro", "rw"}:
                raise AppError("Add-on map mode must be ro or rw")
        elif isinstance(item, dict):
            row = {"type": item.get("type"), "read_only": item.get("read_only", True), "path": item.get("path")}
        else:
            raise AppError("Add-on map entry is malformed")
        row["type"] = MAP_ALIASES.get(row["type"], row["type"])
        if row["type"] not in MAPS or type(row["read_only"]) is not bool:
            raise AppError("Add-on maps an unknown directory")
        if row["path"] is not None and (not isinstance(row["path"], str) or not re.fullmatch(r"/[A-Za-z0-9_./-]{1,200}", row["path"]) or ".." in row["path"].split("/")):
            raise AppError("Add-on map target path is not acceptable")
        result.append(row)
    return result


def parse(raw: dict, *, repository: str = "") -> dict:
    """Validate a raw manifest and return the fields this project acts on."""
    if not isinstance(raw, dict):
        raise AppError("Add-on manifest must be a mapping")
    slug = raw.get("slug")
    if not isinstance(slug, str) or not SLUG.fullmatch(slug):
        raise AppError("Add-on slug is missing or invalid")
    arch = raw.get("arch", ["aarch64", "amd64", "armv7", "armhf", "i386"])
    if not isinstance(arch, list) or not all(isinstance(a, str) for a in arch):
        raise AppError("Add-on 'arch' must be a list")
    image = raw.get("image")
    if image is not None and (not isinstance(image, str) or not re.fullmatch(r"[a-z0-9][A-Za-z0-9._/{}:-]{0,200}", image)):
        raise AppError("Add-on image reference is not acceptable")
    version = raw.get("version")
    if not isinstance(version, (str, int, float)) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.+-]{0,63}", str(version)):
        raise AppError("Add-on version is missing or invalid")
    for flag in ("ingress", "privileged_flag", "host_network", "full_access", "docker_api", "host_pid", "host_ipc",
                 "host_dbus", "auth_api", "homeassistant_api", "hassio_api", "init", "stdin", "kernel_modules",
                 "gpio", "usb", "uart", "audio", "video", "udev", "devicetree", "advanced", "ingress_stream",
                 "backup_exclude_flag", "watchdog_flag", "legacy", "journald", "realtime", "tmpfs"):
        if flag in raw and flag not in {"watchdog", "tmpfs"} and type(raw[flag]) is not bool:
            raise AppError(f"Add-on field '{flag}' must be a boolean")
    privileges = raw.get("privileged", [])
    if not isinstance(privileges, list) or not all(isinstance(p, str) and re.fullmatch(r"[A-Z_]{3,24}", p) for p in privileges):
        raise AppError("Add-on 'privileged' must be a list of capability names")
    devices = raw.get("devices", [])
    if not isinstance(devices, list) or len(devices) > 16 or not all(isinstance(d, str) and re.fullmatch(r"/dev/[A-Za-z0-9_./:+-]{1,200}", d) and ".." not in d for d in devices):
        raise AppError("Add-on 'devices' must list /dev paths")
    role = raw.get("hassio_role", "default")
    if role not in ROLES:
        raise AppError("Add-on declares an unknown API role")
    ingress_port = raw.get("ingress_port", 8099)
    if raw.get("ingress"):
        if ingress_port != 0:
            _port(ingress_port)
    options = raw.get("options", {})
    schema = raw.get("schema", {})
    if not isinstance(options, dict) or (schema is not False and not isinstance(schema, dict)):
        raise AppError("Add-on options/schema must be mappings")
    env = raw.get("environment", {})
    if not isinstance(env, dict) or not all(isinstance(k, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", k) and isinstance(v, (str, int, float, bool)) for k, v in env.items()):
        raise AppError("Add-on environment must be simple name/value pairs")
    discovery = raw.get("discovery", [])
    if not isinstance(discovery, list) or not all(isinstance(d, str) and re.fullmatch(r"[a-z0-9_]{1,40}", d) for d in discovery):
        raise AppError("Add-on 'discovery' is malformed")
    services = raw.get("services", [])
    if not isinstance(services, list) or not all(isinstance(s, str) and re.fullmatch(r"(mqtt|mysql)(:(provide|want|need))?", s) for s in services):
        raise AppError("Add-on 'services' is malformed")
    return {
        "slug": slug, "name": _text(raw.get("name"), "name", 120), "version": str(version),
        "description": _text(raw.get("description", raw.get("name")), "description", 1000),
        "url": raw.get("url") if isinstance(raw.get("url"), str) and raw["url"].startswith("https://") else None,
        "arch": arch, "image": image, "repository": repository,
        "startup": raw.get("startup", "application"), "boot": raw.get("boot", "auto"),
        "ports": parse_ports(raw.get("ports")), "map": parse_map(raw.get("map")),
        "devices": devices, "privileged": privileges, "host_network": bool(raw.get("host_network")),
        "full_access": bool(raw.get("full_access")), "docker_api": bool(raw.get("docker_api")),
        "host_pid": bool(raw.get("host_pid")), "host_dbus": bool(raw.get("host_dbus")),
        "kernel_modules": bool(raw.get("kernel_modules")), "audio": bool(raw.get("audio")),
        "video": bool(raw.get("video")), "usb": bool(raw.get("usb")), "uart": bool(raw.get("uart")),
        "gpio": bool(raw.get("gpio")), "udev": bool(raw.get("udev")), "devicetree": bool(raw.get("devicetree")),
        "homeassistant_api": bool(raw.get("homeassistant_api")), "hassio_api": bool(raw.get("hassio_api")),
        "hassio_role": role, "auth_api": bool(raw.get("auth_api")), "init": raw.get("init", True),
        "apparmor": raw.get("apparmor", True), "ingress": bool(raw.get("ingress")),
        "ingress_port": ingress_port, "ingress_entry": raw.get("ingress_entry", ""),
        "ingress_stream": bool(raw.get("ingress_stream")),
        "panel_icon": raw.get("panel_icon"), "panel_title": raw.get("panel_title"),
        "webui": raw.get("webui") if isinstance(raw.get("webui"), str) else None,
        "options": options, "schema": schema, "environment": {k: str(v) for k, v in env.items()},
        "services": services, "discovery": discovery, "tmpfs": bool(raw.get("tmpfs")), "stdin": bool(raw.get("stdin")),
        "backup": raw.get("backup", "hot"), "stage": raw.get("stage", "stable"),
    }


def report(manifest: dict) -> dict:
    """Judge a parsed manifest before anything is downloaded.

    `unsupported` blocks install; `reduced` installs but names what will not work;
    `privileges` are the things the administrator has to approve on this install.
    """
    blocked, reduced, privileges, notes = [], [], [], []
    if ARCH not in manifest["arch"]:
        blocked.append("Not built for aarch64 (this host's architecture)")
    if manifest["host_dbus"]:
        notes.append("The Supervisor's own D-Bus services (NetworkManager/rauc) are not here; the host's system bus is")
    if manifest["hassio_role"] in {"manager", "admin"}:
        reduced.append("Asks for Supervisor " + manifest["hassio_role"] + " API access; only the endpoints this project emulates answer")
    if manifest["apparmor"] not in (False, "false"):
        notes.append("The add-on's own AppArmor profile is not applied (Docker's default profile still is)")
    if manifest["audio"]:
        notes.append("Audio uses the host's ALSA sound devices directly; there is no PulseAudio server")
    if manifest["video"]:
        reduced.append("Host video devices are not passed through automatically")
    if manifest["udev"]:
        reduced.append("Host udev data is not mounted")
    if manifest["gpio"] or manifest["uart"] or manifest["usb"] or manifest["devicetree"]:
        reduced.append("Hardware access is only granted for devices the administrator selects")
    if manifest["discovery"]:
        reduced.append("Announces itself to Home Assistant through Supervisor discovery, which a Container install cannot receive; add its Home Assistant integration by hand")
    if manifest["homeassistant_api"] or manifest["hassio_api"]:
        reduced.append("Only the REST part of the Supervisor/Home Assistant API is available (no WebSocket proxy), and Home Assistant calls need the access token from the Add-ons tab")
    if manifest["auth_api"]:
        reduced.append("Home Assistant user authentication API is not provided")
    if not manifest["image"]:
        reduced.append("Has no prebuilt image; it must be built on this device (slow, needs free disk)")
    if manifest["host_network"]:
        privileges.append({"id": "host_network", "label": "Host networking: the add-on shares the Pi's network stack", "risk": "high"})
    if manifest["full_access"]:
        privileges.append({"id": "full_access", "label": "Full hardware access to every host device", "risk": "high"})
    if any(manifest["privileged"]):
        privileges.append({"id": "capabilities", "label": "Extra Linux capabilities: " + ", ".join(manifest["privileged"]), "risk": "high" if set(manifest["privileged"]) & {"SYS_ADMIN", "SYS_MODULE", "SYS_RAWIO", "SYS_PTRACE", "DAC_READ_SEARCH"} else "medium"})
    if manifest["audio"]:
        privileges.append({"id": "audio", "label": "Use the host's sound devices (ALSA)", "risk": "medium"})
    if manifest["host_dbus"]:
        privileges.append({"id": "host_dbus", "label": "Talk to the host's system D-Bus (it can manage services, network and Bluetooth)", "risk": "high"})
    if manifest["docker_api"]:
        privileges.append({"id": "docker_api", "label": "Control Docker on this host (equivalent to root; it can start, stop and replace any container, including this manager's)", "risk": "high"})
    if manifest["host_pid"]:
        privileges.append({"id": "host_pid", "label": "See and signal every process on this host (host PID namespace)", "risk": "high"})
    if manifest["kernel_modules"]:
        privileges.append({"id": "kernel_modules", "label": "Load kernel modules", "risk": "high"})
    if manifest["devices"]:
        privileges.append({"id": "devices", "label": "Host devices: " + ", ".join(manifest["devices"]), "risk": "medium"})
    for entry in manifest["map"]:
        if entry["type"] in {"config", "homeassistant_config"}:
            # Even read-only, this directory holds secrets.yaml and .storage (auth tokens, credentials).
            verb = "Read" if entry["read_only"] else "Write"
            privileges.append({"id": verb.lower() + "_" + entry["type"], "risk": "high",
                               "label": f"{verb} access to Home Assistant's configuration directory, including secrets and stored credentials"})
        elif entry["type"] in {"ssl", "addons", "backup"} and not entry["read_only"]:
            privileges.append({"id": "write_" + entry["type"], "label": "Write access to Home Assistant's " + entry["type"] + " directory", "risk": "medium"})
    if manifest["homeassistant_api"] or manifest["hassio_api"]:
        privileges.append({"id": "ha_api", "label": "Act as a Home Assistant client through the Supervisor-style API", "risk": "medium"})
    status = "unsupported" if blocked else "reduced" if reduced else "works"
    return {"status": status, "blocked": blocked, "reduced": reduced, "privileges": privileges, "notes": notes}


# --- options schema -------------------------------------------------------------------

_SIMPLE = {"bool", "email", "url", "port", "str", "password", "int", "float", "match", "list", "device", "dict"}


def _check_scalar(rule: str, value, path: str):
    rule = rule.strip()  # YAML block scalars (`|`) leave a trailing newline on long rules such as Piper's voice list
    optional = rule.endswith("?")
    rule = rule.rstrip("?")
    if value is None:
        if optional:
            return None
        raise AppError(f"Option '{path}' is required")
    name, _, arg = rule.partition("(")
    arg = arg[:-1] if arg.endswith(")") else None
    if name == "bool":
        if type(value) is not bool:
            raise AppError(f"Option '{path}' must be true or false")
    elif name in {"str", "password"}:
        if not isinstance(value, str):
            raise AppError(f"Option '{path}' must be text")
        if arg:
            lo, _, hi = arg.partition(",")
            if (lo and len(value) < int(lo)) or (hi and len(value) > int(hi)):
                raise AppError(f"Option '{path}' has an unacceptable length")
    elif name in {"int", "float"}:
        kind = int if name == "int" else (int, float)
        if isinstance(value, bool) or not isinstance(value, kind):
            raise AppError(f"Option '{path}' must be a number")
        if arg:
            lo, _, hi = arg.partition(",")
            if (lo and value < float(lo)) or (hi and value > float(hi)):
                raise AppError(f"Option '{path}' is out of range")
    elif name == "port":
        _port_value(value, path)
    elif name == "email":
        if not isinstance(value, str) or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
            raise AppError(f"Option '{path}' must be an email address")
    elif name == "url":
        if not isinstance(value, str) or not re.fullmatch(r"https?://\S+", value):
            raise AppError(f"Option '{path}' must be an http(s) URL")
    elif name == "match":
        if not isinstance(value, str) or arg is None or not re.search(arg, value):
            raise AppError(f"Option '{path}' does not match the required format")
    elif name == "list":
        if value not in (arg or "").split("|"):
            raise AppError(f"Option '{path}' must be one of: " + ", ".join((arg or "").split("|")))
    elif name == "device":
        if not isinstance(value, str) or not re.fullmatch(r"/dev/[A-Za-z0-9_./:+-]{1,200}", value) or ".." in value:
            raise AppError(f"Option '{path}' must be a /dev path")
    elif name == "ip":
        try:
            ipaddress.ip_address(value)
        except ValueError as exc:
            raise AppError(f"Option '{path}' must be an IP address") from exc
    else:
        raise AppError(f"Option '{path}' uses an unsupported schema type")
    return value


def _port_value(value, path):
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
        raise AppError(f"Option '{path}' must be a port number")


def validate_options(schema, supplied: dict, *, path: str = "") -> dict:
    """Validate supplied options against an add-on `schema`; unknown keys are rejected."""
    if schema is False or schema is None:
        return {} if not supplied else (_ for _ in ()).throw(AppError("This add-on takes no options"))
    if not isinstance(supplied, dict):
        raise AppError("Options must be an object")
    unknown = set(supplied) - set(schema)
    if unknown:
        raise AppError("Unknown option: " + sorted(unknown)[0])
    result = {}
    for key, rule in schema.items():
        value = supplied.get(key)
        where = path + key
        if isinstance(rule, str):
            checked = _check_scalar(rule, value, where)
            if checked is not None:
                result[key] = checked
        elif isinstance(rule, dict):
            if value is None:
                raise AppError(f"Option '{where}' is required")
            result[key] = validate_options(rule, value, path=where + ".")
        elif isinstance(rule, list):
            if value is None and len(rule) == 1 and isinstance(rule[0], str) and rule[0].strip().endswith("?"):
                continue  # a list of optional items may be left out entirely (Matter Server's matter_server_args)
            if value is None:
                raise AppError(f"Option '{where}' is required")
            if not isinstance(value, list) or len(value) > 512:
                raise AppError(f"Option '{where}' must be a list")
            inner = rule[0] if rule else "str"
            if isinstance(inner, dict):
                result[key] = [validate_options(inner, v, path=where + "[].") for v in value]
            else:
                result[key] = [_check_scalar(inner, v, where + "[]") for v in value]
        else:
            raise AppError(f"Option '{where}' has a malformed schema rule")
    return result


def default_options(manifest: dict) -> dict:
    return json.loads(json.dumps(manifest["options"]))
