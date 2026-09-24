from __future__ import annotations

import contextlib
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tempfile
import time
from typing import Any, Iterator

REPO = Path(__file__).resolve().parents[2]
COMPONENTS = ("ha", "zwave", "mqtt", "camera", "proxy", "ssl", "media", "share", "private", "kiosk")


class ApplianceError(RuntimeError):
    """Expected operational error suitable for a short CLI message."""


def atomic_bytes(path: Path, data: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ApplianceError(f"Refusing symlink destination: {path}")
    fd, name = tempfile.mkstemp(prefix=".opiha-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, mode)
        os.replace(name, path)
        # Persist the rename as well as the contents on Linux.
        if os.name == "posix":
            dfd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def atomic_json(path: Path, value: Any, mode: int = 0o600) -> None:
    atomic_bytes(path, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode(), mode)


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ApplianceError(f"Cannot read JSON: {path}") from exc


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(part)
    return digest.hexdigest()


def run(args: list[str], *, capture: bool = False, **kwargs: Any) -> subprocess.CompletedProcess:
    """No shell expansion. Never log arguments: some callers handle credentials."""
    try:
        return subprocess.run(args, check=True, text=True, capture_output=capture, **kwargs)
    except FileNotFoundError as exc:
        raise ApplianceError(f"Required executable not found: {args[0]}") from exc
    except subprocess.CalledProcessError as exc:
        raise ApplianceError(f"{args[0]} failed with exit code {exc.returncode}") from exc


def safe_relative(name: str) -> PurePosixPath:
    if not name or "\\" in name or "\x00" in name:
        raise ApplianceError("Unsafe archive path")
    p = PurePosixPath(name)
    if p.is_absolute() or any(x in ("..", ".") for x in name.split("/")) or ":" in name:
        raise ApplianceError("Unsafe archive path")
    if not p.parts:
        raise ApplianceError("Empty archive path")
    return p


def guarded_root(path: Path) -> Path:
    raw = path.absolute()
    # Check every existing ancestor before resolve() erases evidence of symlinks.
    for part in (raw, *raw.parents):
        if part.is_symlink():
            raise ApplianceError(f"Symlink in managed path: {part}")
    p = raw.resolve()
    forbidden = {Path(x) for x in ("/", "/etc", "/srv", "/var", "/var/lib", "/home", "/root", "/tmp", "/mnt", "/media", "/usr", "/opt")}
    if p in forbidden or p == Path.home().resolve() or p == REPO or p in REPO.parents:
        raise ApplianceError(f"Refusing unsafe managed root: {p}")
    if len(p.parts) < 3:
        raise ApplianceError("Managed root must be a dedicated subdirectory")
    return p


@contextlib.contextmanager
def exclusive_lock(work: Path) -> Iterator[None]:
    work.mkdir(parents=True, exist_ok=True)
    path = work / "operation.lock"
    with path.open("a+b") as stream:
        if os.name == "posix":
            import fcntl
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ApplianceError("Another appliance operation is running") from exc
        else:
            import msvcrt
            stream.seek(0)
            if not stream.read(1):
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise ApplianceError("Another appliance operation is running") from exc
        try:
            yield
        finally:
            if os.name == "posix":
                fcntl.flock(stream, fcntl.LOCK_UN)
            else:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def private_mkdir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)


def timestamp() -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + f"-{time.time_ns() % 1_000_000:06d}"
