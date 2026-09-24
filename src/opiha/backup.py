from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import stat
import tarfile
import tempfile
from typing import Iterator

from .common import (ApplianceError, COMPONENTS, atomic_json, guarded_root, private_mkdir,
                     read_json, run, safe_relative, sha256, timestamp)
from .config import create_state, ensure_state, portable_settings

MAX_FILES = 200_000
MAX_BYTES = 128 * 1024 ** 3
FORMAT = "opiha-state-v1"
SKIP_DIRS = {"__pycache__", ".cache", "deps", "Cache", "Code Cache", "GPUCache", "DawnCache"}
SKIP_NAMES = {"SingletonLock", "SingletonCookie", "SingletonSocket", "DevToolsActivePort"}


def state_files(data: Path) -> Iterator[tuple[Path, str]]:
    for component in COMPONENTS:
        root = data / component
        if root.is_symlink():
            raise ApplianceError("State component is a symlink")
        if not root.exists():
            continue
        for directory, dirs, files in os.walk(root, followlinks=False):
            parent = Path(directory)
            for child in dirs:
                if (parent / child).is_symlink():
                    raise ApplianceError("State contains a directory symlink; replace it with a supported mount")
            dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
            for name in sorted(files):
                if name in SKIP_NAMES or name.endswith((".pyc", ".pyo")):
                    continue
                path = parent / name
                if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
                    raise ApplianceError("State contains a symlink or special file")
                # Log files add private details and volume without recovery value.
                if name.startswith("home-assistant.log"):
                    continue
                yield path, path.relative_to(data).as_posix()


def create_tar(data: Path, target: Path, settings: dict) -> dict:
    """Call only with all state writers stopped. No live SQLite copying."""
    if target.exists():
        raise ApplianceError("Backup destination already exists")
    if data.resolve() in target.resolve().parents:
        raise ApplianceError("Store backups outside the state directory")
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    files = sorted(state_files(data), key=lambda x: x[1])
    if len(files) > MAX_FILES or sum(p.stat().st_size for p, _ in files) > MAX_BYTES:
        raise ApplianceError("State exceeds backup limits")
    manifest = {"format": FORMAT, "created": timestamp(), "settings": settings, "files": {}}
    version_file = data / "ha/.HA_VERSION"
    manifest["homeassistant_version"] = version_file.read_text().strip() if version_file.exists() else None
    partial = target.with_name(target.name + ".partial")
    if partial.exists():
        raise ApplianceError("Partial output already exists; inspect it before retrying")
    try:
        with partial.open("xb") as output:
            os.chmod(partial, 0o600)
            with tarfile.open(fileobj=output, mode="w:gz") as archive:
                for path, name in files:
                    before = path.stat()
                    digest = sha256(path)
                    manifest["files"][name] = {"sha256": digest, "size": before.st_size}
                    info = archive.gettarinfo(str(path), arcname=name)
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    info.mode = 0o600
                    with path.open("rb") as stream:
                        archive.addfile(info, stream)
                    after = path.stat()
                    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
                        raise ApplianceError("A state file changed during backup; stop all writers")
                content = json.dumps(manifest, sort_keys=True).encode()
                info = tarfile.TarInfo("manifest.json")
                info.size = len(content)
                info.mode = 0o600
                archive.addfile(info, io.BytesIO(content))
            output.flush()
            os.fsync(output.fileno())
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)
    return manifest


def extract_verified(source: Path, target: Path, max_bytes: int = MAX_BYTES) -> dict:
    """Never tar.extractall. Reject links, duplicate members, extras, traversal and bombs."""
    if target.exists() and any(target.iterdir()):
        raise ApplianceError("Extraction target is not empty")
    private_mkdir(target)
    seen: set[str] = set()
    actual = {}
    total = 0
    manifest = None
    try:
        with tarfile.open(source, mode="r:*") as archive:
            for member in archive:
                path = safe_relative(member.name)
                canonical = path.as_posix()
                if canonical in seen:
                    raise ApplianceError("Duplicate archive member")
                seen.add(canonical)
                if len(seen) > MAX_FILES:
                    raise ApplianceError("Archive contains too many members")
                if not member.isfile():
                    raise ApplianceError("Only regular files are allowed in an appliance bundle")
                if canonical != "manifest.json" and path.parts[0] not in COMPONENTS:
                    if path.parts[0] in ("backup.json", "homeassistant.tar.gz"):
                        raise ApplianceError("This is a Home Assistant backup, not an appliance bundle. Restore it in HA onboarding.")
                    raise ApplianceError("Unexpected archive root")
                if len(path.parts) < 2 and canonical != "manifest.json":
                    raise ApplianceError("Invalid component member")
                total += member.size
                if member.size < 0 or total > max_bytes:
                    raise ApplianceError("Archive exceeds extraction size limit")
                stream = archive.extractfile(member)
                if stream is None:
                    raise ApplianceError("Cannot read archive member")
                if canonical == "manifest.json":
                    if member.size > 64 * 1024 * 1024:
                        raise ApplianceError("Manifest too large")
                    manifest = json.load(stream)
                    continue
                destination = target.joinpath(*path.parts)
                private_mkdir(destination.parent)
                with destination.open("xb") as output:
                    os.chmod(destination, 0o600)
                    shutil.copyfileobj(stream, output)
                actual[canonical] = {"sha256": sha256(destination), "size": destination.stat().st_size}
    except (tarfile.TarError, ValueError, OSError) as exc:
        raise ApplianceError("Invalid, incomplete or unreadable archive") from exc
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        raise ApplianceError("Not an OPIHA bundle. Use HA's UI for official encrypted .tar backups.")
    if manifest.get("files") != actual:
        raise ApplianceError("Archive integrity mismatch")
    create_state(target)
    return manifest


def encrypt(source: Path, target: Path, recipient: str) -> None:
    if not recipient.startswith("age1"):
        raise ApplianceError("Use an age X25519 public recipient (age1...)")
    if target.exists():
        raise ApplianceError("Encrypted destination already exists")
    partial = target.with_name(target.name + ".partial")
    if partial.exists():
        raise ApplianceError("Partial output already exists; inspect it before retrying")
    try:
        # age does authenticated encryption; no secret in argv and no in-house crypto.
        run(["age", "--encrypt", "--recipient", recipient, "--output", str(partial), str(source)])
        os.chmod(partial, 0o600)
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)


def decrypt(source: Path, target: Path, identity: Path) -> None:
    if not identity.is_file():
        raise ApplianceError("Missing external age identity")
    run(["age", "--decrypt", "--identity", str(identity), "--output", str(target), str(source)])
    os.chmod(target, 0o600)


def signature_payload(source: Path) -> bytes:
    # Ed25519/OpenSSL signs in one shot. Sign a domain-separated SHA256 instead of
    # loading a multi-gigabyte backup into RAM.
    return ("opiha-backup-sha256-v1\n" + sha256(source) + "\n").encode()


def sign(source: Path, signature: Path, key: Path) -> None:
    if signature.exists():
        raise ApplianceError("Signature already exists")
    with tempfile.TemporaryDirectory(prefix="opiha-sign-") as tmp:
        digest = Path(tmp) / "digest"
        digest.write_bytes(signature_payload(source))
        run(["openssl", "pkeyutl", "-sign", "-rawin", "-inkey", str(key), "-in", str(digest), "-out", str(signature)])


def verify_signature(source: Path, signature: Path, public_key: Path) -> None:
    # Age recipients are public. Encryption alone does not authenticate the sender.
    with tempfile.TemporaryDirectory(prefix="opiha-verify-") as tmp:
        digest = Path(tmp) / "digest"
        digest.write_bytes(signature_payload(source))
        run(["openssl", "pkeyutl", "-verify", "-rawin", "-pubin", "-inkey", str(public_key),
             "-in", str(digest), "-sigfile", str(signature)], capture=True)


def commit_state(cfg: dict, staging: Path) -> Path:
    """Atomic directory exchange with a durable journal and retained prior tree."""
    data = ensure_state(cfg)
    work = Path(cfg["work_dir"])
    journal = work / "restore-journal.json"
    if journal.exists():
        raise ApplianceError("Unfinished restore; run repair-restore")
    if staging.parent != data.parent or staging.is_symlink():
        raise ApplianceError("Restore staging must be on the same filesystem as state")
    if not (staging / ".opiha-state.json").exists():
        raise ApplianceError("Unverified staging directory")
    old = data.with_name(data.name + ".rollback-" + timestamp())
    record = {"data": str(data), "staging": str(staging), "previous": str(old), "phase": "prepared"}
    atomic_json(journal, record)
    try:
        os.replace(data, old)
        record["phase"] = "previous_moved"
        atomic_json(journal, record)
        os.replace(staging, data)
        record["phase"] = "activated"
        atomic_json(journal, record)
        # New state must never auto-run before the operator chooses a cutover.
        (work / "activated.json").unlink(missing_ok=True)
        atomic_json(work / "restored.json", {"at": timestamp(), "previous": str(old)})
        journal.unlink()
        return old
    except BaseException:
        # Best-effort immediate rollback; power-loss recovery uses the persisted journal.
        if old.exists() and not data.exists():
            os.replace(old, data)
            journal.unlink(missing_ok=True)
        raise


def repair_restore(cfg: dict) -> None:
    journal = Path(cfg["work_dir"]) / "restore-journal.json"
    record = read_json(journal)
    data = guarded_root(Path(cfg["data_dir"]))
    old = guarded_root(Path(record["previous"]))
    if str(data) != record["data"] or old.parent != data.parent or not old.name.startswith(data.name + ".rollback-"):
        raise ApplianceError("Restore journal has invalid paths")
    if old.exists():
        if data.exists():
            os.replace(data, data.with_name(data.name + ".failed-" + timestamp()))
        os.replace(old, data)
    elif not data.exists():
        raise ApplianceError("Neither previous nor active state exists; manual recovery required")
    journal.unlink()
    (Path(cfg["work_dir"]) / "activated.json").unlink(missing_ok=True)


def copy_config(source: Path, staging: Path) -> None:
    if not (source / "configuration.yaml").is_file():
        raise ApplianceError("Source must be the HA /config directory, including hidden .storage")
    if source.is_symlink():
        raise ApplianceError("Source cannot be a symlink")
    # Reuse the same bounded allowlist traversal as appliance snapshots.
    for directory, dirs, files in os.walk(source, followlinks=False):
        root = Path(directory)
        for name in dirs:
            if (root / name).is_symlink():
                raise ApplianceError("Config contains a directory symlink")
        dirs[:] = [name for name in dirs if name not in SKIP_DIRS]
        relative = root.relative_to(source)
        target = staging / relative
        private_mkdir(target)
        for name in files:
            if name in SKIP_NAMES or name.endswith((".pyc", ".pyo")) or name.startswith("home-assistant.log"):
                continue
            path = root / name
            if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
                raise ApplianceError("Config contains a link/special file")
            shutil.copyfile(path, target / name)
            os.chmod(target / name, 0o600)


@contextlib.contextmanager
def quiesced(cfg: dict, *, offline: bool = False, source_stopped: bool = False):
    """Down removes containers so Docker restart policies cannot revive writers mid-restore."""
    from . import compose
    if offline:
        if not source_stopped:
            raise ApplianceError("Offline operations require --source-stopped to acknowledge all writers are stopped")
        yield []
        return
    active = compose.running(cfg)
    native = []
    if cfg["mode"] == "appliance" and shutil.which("systemctl"):
        for unit in ("opiha-kiosk.service", "opiha-vision.service"):
            check = __import__("subprocess").run(["systemctl", "is-active", "--quiet", unit])
            if check.returncode == 0:
                run(["systemctl", "stop", unit])
                native.append(unit)
    try:
        compose.command(cfg, "down", "--timeout", "120")
        yield active
    finally:
        # Caller explicitly decides whether restored application containers should start.
        # Native services can safely resume: they do not execute household automations.
        for unit in native:
            run(["systemctl", "start", unit])
