"""Private state, filesystem and configuration boundaries for the native manager."""
from __future__ import annotations
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import tempfile
import time


class AppError(RuntimeError):
    """An expected, non-secret operational failure."""


def checked_path(value: str | Path, *, directory: bool = False) -> Path:
    p = Path(value)
    if not p.is_absolute() or ".." in p.parts or any(c in str(p) for c in "\x00\r\n,"):
        raise AppError("An absolute, non-traversing filesystem path is required")
    for part in (p, *p.parents):
        if part.is_symlink():
            raise AppError("Managed paths cannot contain symlinks")
    if directory and (len(p.parts) < 3 or str(p) in {"/var/lib", "/usr/local", "/home", "/root"}):
        raise AppError("Use a dedicated state directory, not a system directory")
    return p


def atomic(path: Path, content: bytes, mode: int = 0o600) -> None:
    checked_path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix=".apps-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(content)
            out.flush()
            os.fsync(out.fileno())
        os.chmod(name, mode)
        os.replace(name, path)
        parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def write_json(path: Path, value: object, mode: int = 0o600) -> None:
    atomic(path, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode(), mode)


def read_json(path: Path, limit: int = 2 * 1024 * 1024) -> dict:
    checked_path(path)
    try:
        if path.stat().st_size > limit:
            raise AppError("JSON file exceeds its size limit")
        value = json.loads(path.read_text())
        if not isinstance(value, dict):
            raise AppError("JSON document must be an object")
        return value
    except (OSError, ValueError) as exc:
        raise AppError("Cannot read the requested JSON document") from exc


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for part in iter(lambda: f.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def stamp() -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + secrets.token_hex(4)


@contextlib.contextmanager
def operation_lock(root: Path):
    checked_path(root / "operation.lock")
    with (root / "operation.lock").open("a+b") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise AppError("Another native-app operation is active") from exc
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def defaults() -> dict:
    return {"schema": 1, "data_dir": "/srv/orangepi-apps", "port": 8098,
            "docker_socket": "/var/run/docker.sock", "architecture": "arm64",
            "reserve_mib": 2048, "minimum_available_mib": 384,
            "token_file": "/etc/orangepi-apps/token", "network": "opiha-apps",
            "appliance_config": "/etc/orangepi-homeassistant/appliance.json"}


# Added after the first release: absent from older config.json files, which stay valid.
OPTIONAL = {"host_terminal": False, "host_user": "orangepi"}


def validate_config(c: dict) -> dict:
    c = {**OPTIONAL, **c}
    if set(c) != set(defaults()) | set(OPTIONAL) or c.get("schema") != 1:
        raise AppError("Unknown or missing native-manager configuration fields")
    for key in ("data_dir", "token_file", "appliance_config"):
        checked_path(c[key], directory=key == "data_dir")
    if c["docker_socket"] != "/var/run/docker.sock" or c["network"] != "opiha-apps":
        raise AppError("Only the local Docker engine and dedicated app network are supported")
    if c["architecture"] not in {"arm64", "amd64"}:
        raise AppError("Only native ARM64/AMD64 execution is supported")
    for key, lo, hi in (("port", 1024, 65535), ("reserve_mib", 1024, 65536),
                        ("minimum_available_mib", 128, 65536)):
        if type(c[key]) is not int or not lo <= c[key] <= hi:
            raise AppError("Invalid host port or memory budget")
    if type(c["host_terminal"]) is not bool or not isinstance(c["host_user"], str) or not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", c["host_user"]):
        raise AppError("Invalid host terminal settings")
    return c


def initialize(c: dict) -> str:
    validate_config(c)
    root = checked_path(c["data_dir"], directory=True)
    marker = root / ".opiha-apps.json"
    if root.exists() and any(root.iterdir()) and not marker.exists():
        raise AppError("Refusing a populated, unowned native-app state directory")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    if not marker.exists():
        write_json(marker, {"schema": 1, "owner": secrets.token_hex(16)})
    for name in ("apps", "jobs", "rollbacks", "backups"):
        p = checked_path(root / name)
        p.mkdir(mode=0o700, exist_ok=True)
    token = checked_path(c["token_file"])
    if not token.exists():
        atomic(token, (secrets.token_urlsafe(48) + "\n").encode())
    metadata = read_json(marker)
    if set(metadata) != {"schema", "owner"} or metadata["schema"] != 1 or not isinstance(metadata["owner"], str) or not re.fullmatch(r"[0-9a-f]{32}", metadata["owner"]):
        raise AppError("Invalid native-app ownership marker")
    return metadata["owner"]


def read_token(c: dict) -> str:
    p = checked_path(c["token_file"])
    info = p.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
        raise AppError("The manager token must be a private regular file (mode 0600)")
    token = p.read_text().strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{48,128}", token):
        raise AppError("Invalid native-manager token")
    return token
