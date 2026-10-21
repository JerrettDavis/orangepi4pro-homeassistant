"""Native-app cold bundles. Kept distinct from Home Assistant's own backup format."""
from __future__ import annotations
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile
import tempfile
from .common import AppError, atomic, checked_path, digest, operation_lock, read_json, stamp, write_json
from .filesystem import copy_tree, inventory

LIMIT = 64 * 1024**3
MAX_FILES = 250000
DOMAIN = b"opiha-native-apps-v1\x00"


def run(argv, *, input=None):
    try:
        p = subprocess.run(argv, input=input, capture_output=True, check=False, timeout=3600)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AppError("A required archive/cryptography tool failed or is unavailable") from exc
    if p.returncode:
        raise AppError("Archive encryption or signature operation failed; no successful result is claimed")
    return p.stdout


def sign(bundle: Path, key: Path, destination: Path):
    if destination.exists():
        raise AppError("Signature destination exists")
    with tempfile.TemporaryDirectory(prefix=".opiha-sign-", dir=bundle.parent) as temp:
        message = Path(temp) / "digest"
        atomic(message, DOMAIN + bytes.fromhex(digest(bundle)))
        # -rawin uses Ed25519 one-shot signing; only the digest, never private state, enters the signature API.
        out = run(["openssl", "pkeyutl", "-sign", "-rawin", "-inkey", str(key), "-in", str(message)])
        atomic(destination, out)


def verify(bundle: Path, signature: Path, trust_key: Path):
    with tempfile.TemporaryDirectory(prefix="opiha-verify-") as temp:
        message = Path(temp) / "digest"
        atomic(message, DOMAIN + bytes.fromhex(digest(bundle)))
        run(["openssl", "pkeyutl", "-verify", "-pubin", "-rawin", "-inkey", str(trust_key),
             "-in", str(message), "-sigfile", str(signature)])


class BoundedTarInfo(tarfile.TarInfo):
    def _proc_member(self, tar):
        if self.type in {tarfile.XHDTYPE, tarfile.XGLTYPE, tarfile.GNUTYPE_LONGNAME, tarfile.GNUTYPE_LONGLINK} and self.size > 65536:
            raise AppError("Oversized archive extension header")
        if self.type == tarfile.GNUTYPE_SPARSE:
            raise AppError("Sparse extension members are not supported in app bundles")
        return super()._proc_member(tar)


def path_name(name: str) -> str:
    p = PurePosixPath(name)
    if p.is_absolute() or not name or any(x in name for x in "\\\x00\r\n") or any(x in {".", "..", ""} for x in name.split("/")):
        raise AppError("Unsafe archive path")
    if name != ".opiha-apps.json" and not name.startswith("apps/"):
        raise AppError("Archive file is outside the native-app state boundary")
    return name


def pack(root: Path, destination: Path) -> dict:
    rows = []
    for base in [root / ".opiha-apps.json", root / "apps"]:
        paths = [base] if base.is_file() else sorted(base.rglob("*"))
        if base.is_dir():
            inventory(base)  # Includes internal-link and special-file checks.
        for p in paths:
            if p.is_dir() and not p.is_symlink():
                continue
            name = path_name(p.relative_to(root).as_posix())
            if p.is_symlink():
                rows.append({"path": name, "type": "link", "target": os.readlink(p)})
            elif p.is_file():
                rows.append({"path": name, "type": "file", "size": p.stat().st_size,
                             "sha256": digest(p), "mode": p.stat().st_mode & 0o777})
            else:
                raise AppError("Unsupported archive entry")
    if len(rows) > MAX_FILES or sum(r.get("size", 0) for r in rows) > LIMIT:
        raise AppError("Native-app bundle exceeds file/size limits")
    manifest = {"format": "opiha-native-apps-v1", "files": rows, "created": stamp(), "contains_private_state": True}
    with tarfile.open(destination, "w:gz", dereference=False) as tar:
        content = json.dumps(manifest, sort_keys=True).encode()
        info = tarfile.TarInfo("manifest.json"); info.size = len(content); info.mode = 0o600
        tar.addfile(info, io.BytesIO(content))
        for row in rows:
            source = root / row["path"]
            info = tarfile.TarInfo(row["path"])
            info.mode = row.get("mode", 0o700)
            if row["type"] == "link":
                info.type = tarfile.SYMTYPE; info.linkname = row["target"]
                tar.addfile(info)
            else:
                info.size = row["size"]
                with source.open("rb") as f:
                    tar.addfile(info, f)
    os.chmod(destination, 0o600)
    return manifest


def extract(source: Path, destination: Path) -> dict:
    checked_path(destination, directory=True)
    if destination.exists():
        raise AppError("Recovery stages into a new directory only; live state is never overwritten")
    destination.mkdir(mode=0o700, parents=True)
    try:
        with tarfile.open(source, "r:gz", tarinfo=BoundedTarInfo) as tar:
            first = tar.next()
            if not first or first.name != "manifest.json" or not first.isfile() or first.size > 64 * 1024**2:
                raise AppError("Missing/oversized native-app manifest")
            manifest = json.load(tar.extractfile(first))
            if manifest.get("format") != "opiha-native-apps-v1" or not isinstance(manifest.get("files"), list):
                raise AppError("This is not a native-app bundle; use HA's UI for native HA backups")
            rows = manifest["files"]
            if len(rows) > MAX_FILES:
                raise AppError("Too many archive files")
            index = {}
            total = 0
            for row in rows:
                name = path_name(row["path"])
                if name in index or row.get("type") not in {"file", "link"}:
                    raise AppError("Duplicate/invalid manifest entry")
                if row["type"] == "file":
                    if type(row.get("size")) is not int or row["size"] < 0:
                        raise AppError("Invalid file size")
                    total += row["size"]
                    if type(row.get("mode")) is not int or row["mode"] & ~0o777:
                        raise AppError("Unsafe file mode")
                else:
                    target = row.get("target")
                    if not isinstance(target, str) or target.startswith("/") or any(c in target for c in "\\\x00\r\n"):
                        raise AppError("Unsafe archive symlink")
                    resolved = (destination / name).parent.joinpath(target).resolve()
                    if destination.resolve() not in resolved.parents:
                        raise AppError("Archive symlink escapes recovery directory")
                index[name] = row
            if total > LIMIT or shutil.disk_usage(destination).free < total + 256 * 1024**2:
                raise AppError("Recovery exceeds capacity/size limits")
            # Never write regular files through a link ancestor; reject them before extracting.
            link_paths = {PurePosixPath(n) for n, r in index.items() if r["type"] == "link"}
            for name in index:
                if any(parent in link_paths for parent in PurePosixPath(name).parents):
                    raise AppError("An archive link is also a file parent")
            seen = set()
            initial_seen = False
            for info in tar:
                if info.name == "manifest.json":
                    if initial_seen:
                        raise AppError("Duplicate manifest")
                    initial_seen = True
                    continue  # tarfile iteration includes the first member already read with next().
                name = path_name(info.name)
                row = index.get(name)
                if name in seen or row is None:
                    raise AppError("Duplicate or unlisted archive entry")
                seen.add(name)
                target = destination / name
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                if row["type"] == "link":
                    if not info.issym() or info.linkname != row["target"]:
                        raise AppError("Archive link differs from manifest")
                else:
                    if not info.isfile() or info.size != row["size"]:
                        raise AppError("Archive file differs from manifest")
                    h = hashlib.sha256()
                    with tar.extractfile(info) as src, target.open("xb") as out:
                        for chunk in iter(lambda: src.read(1024**2), b""):
                            h.update(chunk); out.write(chunk)
                    os.chmod(target, row["mode"])
                    if h.hexdigest() != row["sha256"]:
                        raise AppError("Archive file checksum failed")
            if seen != set(index) or ".opiha-apps.json" not in seen:
                raise AppError("Native-app archive is incomplete")
            for name, row in index.items():
                if row["type"] == "link":
                    (destination / name).symlink_to(row["target"])
            (destination / "apps").mkdir(mode=0o700, exist_ok=True)
            inventory(destination / "apps")
            from .manager import Manager
            from .catalog import entry
            for slug in (destination / "apps").iterdir():
                entry(slug.name)
                if (slug / "record.json").is_file():
                    Manager.validate_record(slug.name, read_json(slug / "record.json"))
                if (slug / "transaction.json").exists():
                    raise AppError("Recovery bundle contains an unfinished replacement")
            return manifest
    except Exception:
        shutil.rmtree(destination)
        raise


def create(manager, output: Path, *, recipient=None, signing_key=None, plaintext=False) -> dict:
    output = checked_path(output)
    if manager.root == output or manager.root in output.parents:
        raise AppError("Backups must be outside native-app state")
    if output.exists() or Path(str(output) + ".sig").exists():
        raise AppError("Backup output already exists")
    if plaintext == bool(recipient):
        raise AppError("Choose an age recipient or explicitly --plaintext for a private local rehearsal")
    if recipient and not shutil.which("age"):
        raise AppError("age is required for encrypted backups")
    output.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    previous = []
    with operation_lock(manager.root), tempfile.TemporaryDirectory(prefix=".opiha-backup-", dir=output.parent) as tmp:
        try:
            for slug in manager.records():
                manager._assert_no_journal(slug)
                row = manager.engine.owned(slug)
                if row:
                    running = bool(row.get("State", {}).get("Running"))
                    previous.append((slug, row["Id"], running, manager.record(slug)["options"]["autostart"]))
                    manager.engine.restart_policy(row["Id"], slug, False)
                    if running:
                        manager.engine.action(row["Id"], slug, "stop")
            staging = Path(tmp) / "state"; staging.mkdir(mode=0o700)
            atomic(staging / ".opiha-apps.json", (manager.root / ".opiha-apps.json").read_bytes())
            copy_tree(manager.root / "apps", staging / "apps")
        finally:
            errors = []
            for slug, identifier, running, auto in previous:
                try:
                    manager.engine.restart_policy(identifier, slug, auto if running else False)
                    if running:
                        manager.engine.action(identifier, slug, "start")
                except (AppError, OSError):
                    errors.append(slug)
            if errors:
                raise AppError("Some apps did not resume after snapshot; inspect their state locally")
        clear = Path(tmp) / "state.tar.gz"
        manifest = pack(staging, clear)
        staged_output = Path(tmp) / "output"
        if plaintext:
            shutil.copyfile(clear, staged_output)
        else:
            run(["age", "-r", recipient, "-o", str(staged_output), str(clear)])
        os.chmod(staged_output, 0o600)
        os.replace(staged_output, output)
        if signing_key:
            sign(output, checked_path(signing_key), Path(str(output) + ".sig"))
    return {"output": str(output), "sha256": digest(output), "files": len(manifest["files"]),
            "encrypted": not plaintext, "signed": bool(signing_key), "includes_homeassistant": False}


def restore(bundle: Path, destination: Path, *, identity=None, signature=None, trust_key=None, apply=False) -> dict:
    bundle, destination = checked_path(bundle), checked_path(destination, directory=True)
    if bool(signature) != bool(trust_key):
        raise AppError("Supply both signature and public trust key")
    if signature:
        verify(bundle, checked_path(signature), checked_path(trust_key))
    if destination.exists():
        raise AppError("Destination already exists; recovery never replaces live state")
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".opiha-recovery-", dir=destination.parent) as tmp:
        clear = bundle
        if identity:
            clear = Path(tmp) / "state.tar.gz"
            run(["age", "-d", "-i", str(checked_path(identity)), "-o", str(clear), str(bundle)])
            os.chmod(clear, 0o600)
        staged = Path(tmp) / "state"
        manifest = extract(clear, staged)
        if apply:
            os.replace(staged, destination)
    return {"verified": True, "files": len(manifest["files"]), "staged": apply,
            "destination": str(destination), "started_apps": False, "changed_live_state": False}
