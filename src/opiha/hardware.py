from __future__ import annotations

from dataclasses import dataclass
import glob
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any

from .common import ApplianceError, REPO, atomic_json


@dataclass(frozen=True)
class CommandResult:
    argv: tuple[str, ...]
    returncode: int | None
    stdout: str
    status: str


_SENSITIVE_KEYS = {
    "address",
    "credential",
    "hostname",
    "home_id",
    "key",
    "mac",
    "password",
    "secret",
    "serial",
    "ssid",
    "token",
    "username",
    "uuid",
}
_TEXT_PATTERNS = (
    re.compile(r"(?i)\b(?:token|password|secret|key)\s*[=:]\s*[^\s,;]+"),
    re.compile(r"(?i)(?<=\bhost\s)[a-z0-9][a-z0-9.-]*"),
    re.compile(r"\b(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}\b"),
    re.compile(r"\b[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\b"),
    re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])"),
    re.compile(r"(?<![\w:])(?:[0-9a-fA-F]{1,4}:){2,}[0-9a-fA-F:]{1,}(?![\w:])"),
)


def _sensitive_key(key: object) -> bool:
    normalized = str(key).lower().replace("-", "_")
    return normalized in _SENSITIVE_KEYS or any(
        normalized.endswith("_" + part) for part in _SENSITIVE_KEYS
    )


def _redact_text(value: str) -> str:
    result = value
    for pattern in _TEXT_PATTERNS:
        result = pattern.sub("[redacted]", result)
    return result


def redact(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: "redacted" if _sensitive_key(key) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    if isinstance(value, str):
        return _redact_text(value)
    return value


def parse_lsblk(text: str) -> list[dict[str, Any]]:
    try:
        document = json.loads(text)
        devices = document["blockdevices"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ApplianceError("Invalid lsblk JSON") from exc
    if not isinstance(devices, list):
        raise ApplianceError("Invalid lsblk device list")

    rows: list[dict[str, Any]] = []

    def visit(raw: object, inherited_parent: str | None = None) -> None:
        if not isinstance(raw, dict):
            raise ApplianceError("Invalid lsblk device row")
        row = dict(raw)
        children = row.pop("children", []) or []
        path = row.get("path") or ("/dev/" + str(row.get("name", "")))
        parent_name = row.pop("pkname", None)
        parent = "/dev/" + str(parent_name) if parent_name else inherited_parent
        mountpoints = row.get("mountpoints")
        if mountpoints is None:
            single = row.pop("mountpoint", None)
            mountpoints = [single] if single else []
        elif isinstance(mountpoints, str):
            mountpoints = [mountpoints]
        elif not isinstance(mountpoints, list):
            raise ApplianceError("Invalid lsblk mountpoints")
        row.update(path=path, parent=parent, mountpoints=[m for m in mountpoints if m])
        rows.append(row)
        if not isinstance(children, list):
            raise ApplianceError("Invalid lsblk children")
        for child in children:
            visit(child, str(path))

    for device in devices:
        visit(device)
    return rows


def parse_findmnt(text: str) -> dict[str, str]:
    mounts: dict[str, str] = {}
    for raw in text.splitlines():
        parts = raw.split(None, 1)
        if len(parts) == 2 and parts[0].startswith("/") and parts[1].startswith("/dev/"):
            mounts[parts[0]] = parts[1]
    return mounts


def parse_devices(text: str) -> list[str]:
    devices = {
        line.strip()
        for line in text.splitlines()
        if line.strip().startswith("/dev/") and "*" not in line
    }
    return sorted(devices)


def _parse_key_values(text: str, separator: str = "=") -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        if separator not in line:
            continue
        key, value = line.split(separator, 1)
        values[key.strip()] = value.strip().strip('"')
    return values


def _integer_field(text: str, name: str) -> int | None:
    match = re.search(rf"^{re.escape(name)}:\s+(\d+)", text, re.MULTILINE)
    return int(match.group(1)) if match else None


def _df_bytes(text: str) -> tuple[int | None, int | None]:
    rows = [line.split() for line in text.splitlines() if line.split()]
    if len(rows) < 2 or len(rows[-1]) < 2:
        return None, None
    try:
        return int(rows[-1][0]), int(rows[-1][1])
    except ValueError:
        return None, None


def _row_index(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        path = row.get("path")
        if isinstance(path, str):
            index.setdefault(path, []).append(row)
    return index


def _parent_disk(
    source: str, index: dict[str, list[dict[str, Any]]]
) -> str | None:
    current = source
    visited: set[str] = set()
    while current not in visited:
        visited.add(current)
        matches = index.get(current, [])
        if len(matches) != 1:
            return None
        row = matches[0]
        if row.get("type") == "disk":
            return current
        parent = row.get("parent")
        if not isinstance(parent, str) or not parent:
            return None
        current = parent
    return None


def protected_disks(
    rows: list[dict[str, Any]], mounts: dict[str, str]
) -> set[str]:
    index = _row_index(rows)
    protected: set[str] = set()
    for target in ("/", "/boot", "/boot/efi"):
        source = mounts.get(target)
        if source:
            disk = _parent_disk(source, index)
            if disk:
                protected.add(disk)
    return protected


def classify_flash_target(
    path: str, rows: list[dict[str, Any]], mounts: dict[str, str]
) -> dict[str, object]:
    result: dict[str, object] = {"path": path, "safe": False, "reasons": []}
    reasons: set[str] = set()
    index = _row_index(rows)
    matches = index.get(path, [])
    if not matches:
        reasons.add("unknown-device")
    elif len(matches) != 1:
        reasons.add("ambiguous")
    elif matches[0].get("type") != "disk":
        reasons.add("not-whole-disk")
    elif not matches[0].get("size") or not matches[0].get("model"):
        reasons.add("missing-identification")

    role_targets = {"/": "root", "/boot": "boot", "/boot/efi": "efi"}
    for target, role in role_targets.items():
        source = mounts.get(target)
        if not source:
            continue
        disk = _parent_disk(source, index)
        if disk is None:
            reasons.add("ambiguous")
        elif disk == path:
            reasons.add(role)

    if len(matches) == 1 and matches[0].get("type") == "disk":
        for row in rows:
            row_path = row.get("path")
            if not isinstance(row_path, str):
                continue
            if row_path == path or _parent_disk(row_path, index) == path:
                if row.get("mountpoints"):
                    reasons.add("mounted")

    ordered = sorted(reasons)
    result["reasons"] = ordered
    result["safe"] = not ordered
    return result


def run_command(argv: list[str]) -> CommandResult:
    try:
        completed = subprocess.run(argv, check=False, text=True, capture_output=True, timeout=20)
    except FileNotFoundError:
        return CommandResult(tuple(argv), None, "", "unavailable")
    except subprocess.TimeoutExpired:
        return CommandResult(tuple(argv), None, "", "timeout")
    stderr = completed.stderr.lower()
    if completed.returncode == 0:
        status = "ok"
    elif "permission denied" in stderr or "a password is required" in stderr:
        status = "permission-denied"
    else:
        status = "error"
    return CommandResult(tuple(argv), completed.returncode, completed.stdout, status)


def _probe(runner, argv: list[str]) -> CommandResult:
    result = runner(argv)
    if not isinstance(result, CommandResult):
        raise ApplianceError("Hardware command runner returned an invalid result")
    return result


def _tool_status(name: str) -> str:
    return "available" if shutil.which(name) else "unavailable"


def collect_inventory(private: bool = False, runner=run_command) -> dict[str, Any]:
    arch = _probe(runner, ["uname", "-m"])
    kernel = _probe(runner, ["uname", "-r"])
    hostname = _probe(runner, ["hostname"])
    lsblk = _probe(runner, ["lsblk", "--json", "-o", "NAME,PATH,TYPE,PKNAME,SIZE,FSTYPE,MOUNTPOINTS,MODEL"])
    findmnt = _probe(runner, ["findmnt", "-rn", "-o", "TARGET,SOURCE"])
    docker = _probe(runner, ["docker", "version", "--format", "{{.Client.Version}}|{{.Server.Version}}"])
    compose = _probe(runner, ["docker", "compose", "version", "--short"])
    display = _probe(runner, ["systemctl", "show", "display-manager", "-p", "Id", "-p", "ActiveState"])
    failed = _probe(runner, ["systemctl", "--failed", "--no-legend", "--plain"])
    network = _probe(runner, ["ip", "-brief", "link"])
    camera = _probe(runner, ["v4l2-ctl", "--list-devices"])
    input_devices = _probe(runner, ["cat", "/proc/bus/input/devices"])
    modules = _probe(runner, ["cat", "/proc/modules"])
    os_release = _probe(runner, ["cat", "/etc/os-release"])
    dt_model = _probe(runner, ["cat", "/proc/device-tree/model"])
    meminfo = _probe(runner, ["cat", "/proc/meminfo"])
    cpuinfo = _probe(runner, ["cat", "/proc/cpuinfo"])
    root_space = _probe(runner, ["df", "-B1", "--output=size,avail", "/"])

    rows = parse_lsblk(lsblk.stdout) if lsblk.status == "ok" else []
    mounts = parse_findmnt(findmnt.stdout) if findmnt.status == "ok" else {}
    mount_roles = {target: source for target, source in mounts.items() if target in {"/", "/boot", "/boot/efi"}}
    serial_devices = sorted(glob.glob("/dev/serial/by-id/*"))
    input_names = re.findall(r'^N:\s+Name="([^"]+)"', input_devices.stdout, re.MULTILINE)
    loaded_modules = {line.split()[0] for line in modules.stdout.splitlines() if line.split()}
    os_values = _parse_key_values(os_release.stdout) if os_release.status == "ok" else {}
    root_total, root_available = _df_bytes(root_space.stdout)
    cpu_features = next(
        (line.split(":", 1)[1].strip().split() for line in cpuinfo.stdout.splitlines() if line.lower().startswith(("features", "flags")) and ":" in line),
        [],
    )
    result: dict[str, Any] = {
        "schema": 1,
        "privacy": "private" if private else "public-sanitized",
        "system": {
            "architecture": arch.stdout.strip() if arch.status == "ok" else "unknown",
            "kernel": kernel.stdout.strip() if kernel.status == "ok" else "unknown",
            "hostname": hostname.stdout.strip() if hostname.status == "ok" else "unknown",
            "os": {
                "id": os_values.get("ID", "unknown"),
                "version_id": os_values.get("VERSION_ID", "unknown"),
            },
            "device_tree_model": dt_model.stdout.rstrip("\x00\n") if dt_model.status == "ok" else "unknown",
        },
        "resources": {
            "memory_total_kib": _integer_field(meminfo.stdout, "MemTotal"),
            "memory_available_kib": _integer_field(meminfo.stdout, "MemAvailable"),
            "cpu_count": len(re.findall(r"^processor\s*:", cpuinfo.stdout, re.MULTILINE)),
            "cpu_features": sorted(set(cpu_features)),
            "root_total_bytes": root_total,
            "root_available_bytes": root_available,
            "thermal_zones": sorted(glob.glob("/sys/class/thermal/thermal_zone*")),
        },
        "storage": {
            "devices": rows,
            "mount_roles": mount_roles,
            "protected_disks": sorted(protected_disks(rows, mount_roles)),
            "status": lsblk.status if lsblk.status != "ok" else findmnt.status,
        },
        "docker": {
            "engine": docker.status,
            "version": docker.stdout.strip() if docker.status == "ok" else "unavailable",
            "compose": compose.status,
            "compose_version": compose.stdout.strip() if compose.status == "ok" else "unavailable",
        },
        "display": {
            "status": display.status,
            "summary": display.stdout.strip(),
            "drm_nodes": sorted(glob.glob("/dev/dri/card*")),
            "framebuffers": sorted(glob.glob("/dev/fb[0-9]*")),
        },
        "input": {
            "devices": sorted(set(input_names)),
            "native_touch_modules": sorted(
                loaded_modules.intersection({"hid_multitouch", "uhid", "uinput"})
            ),
        },
        "camera": {
            "status": camera.status,
            "video_devices": sorted(glob.glob("/dev/video[0-9]*")),
            "media_devices": sorted(glob.glob("/dev/media[0-9]*")),
            "v4l2_summary": camera.stdout.strip(),
        },
        "zwave": {"serial_by_id_present": bool(serial_devices), "devices": serial_devices if private else []},
        "network": {"status": network.status, "summary": network.stdout.strip()},
        "services": {"failed_status": failed.status, "failed": failed.stdout.splitlines()},
        "tools": {name: _tool_status(name) for name in ("age", "age-keygen", "openssl", "ffmpeg", "gst-launch-1.0", "v4l2-ctl", "docker", "jq", "rsync")},
    }
    try:
        import cv2  # type: ignore

        result["tools"]["opencv"] = "available"
    except ImportError:
        result["tools"]["opencv"] = "unavailable"
    if private:
        return result
    public = redact(result)
    assert isinstance(public, dict)
    storage = public.get("storage", {})
    if isinstance(storage, dict):
        devices = storage.get("devices", [])
        if isinstance(devices, list):
            safe_mounts = {"/", "/boot", "/boot/efi", "/tmp", "/var/log", "[SWAP]"}
            for device in devices:
                if isinstance(device, dict) and isinstance(device.get("mountpoints"), list):
                    device["mountpoints"] = [
                        mount if mount in safe_mounts else "other-mounted"
                        for mount in device["mountpoints"]
                    ]
    return public


def collect_section(section: str) -> dict[str, Any]:
    if section not in {"camera", "zwave", "storage"}:
        raise ApplianceError("Unknown hardware section")
    value = collect_inventory()[section]
    if not isinstance(value, dict):
        raise ApplianceError("Invalid hardware inventory section")
    return {"section": section, **value}


def _has_symlink_ancestor(path: Path) -> bool:
    raw = path.absolute()
    return any(part.is_symlink() for part in (raw, *raw.parents))


def write_inventory(result: dict, output: Path, private: bool) -> None:
    raw = output.absolute()
    if _has_symlink_ancestor(raw):
        raise ApplianceError("Inventory output path contains a symlink")
    resolved = raw.resolve()
    repo = REPO.resolve()
    if private and (resolved == repo or repo in resolved.parents):
        raise ApplianceError("Private inventory must be written outside the repository")
    atomic_json(resolved, result if private else redact(result), mode=0o600)
    if os.name == "posix":
        os.chmod(resolved, 0o600)
