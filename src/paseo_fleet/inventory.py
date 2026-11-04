"""Fleet inventory: which machines run a Paseo daemon and how to reach them."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re

PLATFORMS = ("linux", "macos", "windows", "docker")
TRANSPORTS = ("local", "ssh")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
SSH_RE = re.compile(r"^[A-Za-z0-9._-]+@[A-Za-z0-9][A-Za-z0-9.-]*$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(-[A-Za-z0-9.]+)?$")
PKG_RE = re.compile(r"^(@[a-z0-9._-]+/)?[a-z0-9._-]+@\d+\.\d+\.\d+(-[A-Za-z0-9.]+)?$")
LABEL_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,30}$")
UNSAFE_PATH_RE = re.compile(r"[\"'`$;&|<>\n]")


class InventoryError(ValueError):
    pass


@dataclass(frozen=True)
class Host:
    id: str
    platform: str
    transport: str
    daemon_port: int
    ssh: str | None = None
    ssh_port: int | None = None
    labels: tuple[str, ...] = ()
    workspace_root: str | None = None
    workspace_mount: str | None = None
    limits: dict = field(default_factory=dict)
    env_file: str | None = None
    hub: bool = False
    enabled: bool = True

    @property
    def is_docker(self) -> bool:
        return self.platform == "docker"

    @property
    def is_windows(self) -> bool:
        return self.platform == "windows"


@dataclass(frozen=True)
class Inventory:
    paseo_version: str
    node_version: str
    agents: tuple[str, ...]
    hosts: tuple[Host, ...]
    source: Path | None = None

    def select(self, ids: list[str] | None = None, labels: list[str] | None = None) -> list[Host]:
        chosen = [h for h in self.hosts if h.enabled]
        if ids:
            unknown = set(ids) - {h.id for h in self.hosts}
            if unknown:
                raise InventoryError(f"unknown host id(s): {', '.join(sorted(unknown))}")
            chosen = [h for h in self.hosts if h.id in ids]
        if labels:
            chosen = [h for h in chosen if set(labels) <= set(h.labels)]
        return chosen

    @property
    def hub(self) -> Host:
        return next(h for h in self.hosts if h.hub)


def _int_in(value, low: int, high: int, where: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
        raise InventoryError(f"{where} must be an integer {low}-{high}")
    return value


def _host(raw: dict, defaults: dict) -> Host:
    hid = raw.get("id", "")
    if not isinstance(hid, str) or not ID_RE.match(hid):
        raise InventoryError(f"invalid host id {hid!r} (lowercase letters, digits, hyphen)")
    platform = raw.get("platform")
    if platform not in PLATFORMS:
        raise InventoryError(f"{hid}: platform must be one of {PLATFORMS}")
    transport = raw.get("transport", "local")
    if transport not in TRANSPORTS:
        raise InventoryError(f"{hid}: transport must be one of {TRANSPORTS}")
    ssh = raw.get("ssh")
    if transport == "ssh" and not (isinstance(ssh, str) and SSH_RE.match(ssh)):
        raise InventoryError(f"{hid}: ssh must look like user@host")
    if transport == "local" and ssh:
        raise InventoryError(f"{hid}: local hosts must not set ssh")
    ssh_port = raw.get("ssh_port")
    if ssh_port is not None:
        ssh_port = _int_in(ssh_port, 1, 65535, f"{hid}.ssh_port")
    labels = tuple(raw.get("labels", ()))
    for label in labels:
        if not isinstance(label, str) or not LABEL_RE.match(label):
            raise InventoryError(f"{hid}: invalid label {label!r}")
    limits = raw.get("limits", {})
    allowed = {"memory", "cpus", "nice"}
    if not isinstance(limits, dict) or set(limits) - allowed:
        raise InventoryError(f"{hid}: limits keys must be within {sorted(allowed)}")
    if "memory" in limits and not re.match(r"^\d+[MG]$", str(limits["memory"])):
        raise InventoryError(f"{hid}: limits.memory must look like 1536M or 2G")
    if "cpus" in limits and not (isinstance(limits["cpus"], (int, float)) and 0 < limits["cpus"] <= 256):
        raise InventoryError(f"{hid}: limits.cpus must be a positive number")
    if "nice" in limits:
        _int_in(limits["nice"], 0, 19, f"{hid}.limits.nice")
    root = raw.get("workspace_root", defaults.get("workspace_root"))
    if root is not None and (not isinstance(root, str) or UNSAFE_PATH_RE.search(root)):
        raise InventoryError(f"{hid}: workspace_root contains unsafe characters")
    mount = raw.get("workspace_mount")
    if mount is not None and (platform != "docker" or not isinstance(mount, str) or UNSAFE_PATH_RE.search(mount)):
        raise InventoryError(f"{hid}: workspace_mount is only for docker hosts and must be a safe host path")
    return Host(
        id=hid, platform=platform, transport=transport,
        daemon_port=_int_in(raw.get("daemon_port", 6767), 1024, 65535, f"{hid}.daemon_port"),
        ssh=ssh, ssh_port=ssh_port, labels=labels,         workspace_root=root, workspace_mount=mount,
        limits=limits, env_file=raw.get("env_file"),
        hub=bool(raw.get("hub", False)), enabled=bool(raw.get("enabled", True)),
    )


def parse(document: dict, source: Path | None = None) -> Inventory:
    if document.get("version") != 1:
        raise InventoryError("inventory version must be 1")
    paseo_version = document.get("paseo_version", "")
    node_version = document.get("node_version", "")
    if not VERSION_RE.match(str(paseo_version)):
        raise InventoryError("paseo_version must be an exact version such as 0.15.0")
    if not VERSION_RE.match(str(node_version)):
        raise InventoryError("node_version must be an exact version such as 22.22.0")
    agents = tuple(document.get("agents", ()))
    for pkg in agents:
        if not isinstance(pkg, str) or not PKG_RE.match(pkg):
            raise InventoryError(f"agent package {pkg!r} must be pinned as name@x.y.z")
    defaults = document.get("defaults", {})
    hosts = tuple(_host(raw, defaults) for raw in document.get("hosts", ()))
    if not hosts:
        raise InventoryError("inventory has no hosts")
    ids = [h.id for h in hosts]
    if len(set(ids)) != len(ids):
        raise InventoryError("duplicate host ids")
    hubs = [h for h in hosts if h.hub]
    if len(hubs) != 1:
        raise InventoryError("exactly one host must set hub: true")
    if hubs[0].transport != "local" or hubs[0].is_docker:
        raise InventoryError("the hub must be a local, non-docker host")
    seen: set[tuple[str, int]] = set()
    for h in hosts:
        key = (h.ssh.split("@", 1)[1] if h.ssh else "local", h.daemon_port)
        if key in seen:
            raise InventoryError(f"{h.id}: daemon_port {h.daemon_port} already used on that machine")
        seen.add(key)
    return Inventory(str(paseo_version), str(node_version), agents, hosts, source)


def load(path: Path) -> Inventory:
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise InventoryError(f"inventory not found: {path}") from None
    except json.JSONDecodeError as exc:
        raise InventoryError(f"inventory is not valid JSON: {exc}") from None
    return parse(document, Path(path))
