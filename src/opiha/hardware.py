from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any

from .common import ApplianceError


@dataclass(frozen=True)
class CommandResult:
    argv: tuple[str, ...]
    returncode: int | None
    stdout: str
    status: str


_SENSITIVE_KEYS = (
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
)
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
    return any(part in normalized for part in _SENSITIVE_KEYS)


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
