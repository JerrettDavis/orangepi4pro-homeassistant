"""Per-add-on backup and restore: the data an add-on keeps plus the options it was configured with.

A backup is a private gzip tar holding `data/`, `addon_config/` and a `meta.json`, with a sidecar `.json` that records its
size and SHA-256. Restore verifies the hash, accepts only regular files and directories under those two roots, and never
changes the install decisions (image, ports, granted privileges): only the add-on's data and its options.
"""
from __future__ import annotations
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import tarfile
import time
from .common import AppError, atomic, checked_path, read_json, stamp, write_json
from .filesystem import inventory

ROOTS = ("data", "addon_config")
ID = re.compile(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}")
MAX_BYTES = 16 * 1024**3


def directory(mgr) -> Path:
    path = checked_path(mgr.root / "addon-backups")
    path.mkdir(mode=0o700, exist_ok=True)
    return path


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for part in iter(lambda: f.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def create(mgr, slug: str, version: str, config: dict) -> dict:
    """Write a backup of `slug`. The caller has stopped the add-on so the copy is consistent."""
    root = mgr.app_dir(slug)
    total = 0
    for name in ROOTS:
        if (root / name).is_dir():
            total += inventory(root / name, max_bytes=MAX_BYTES)[1]
    out = directory(mgr)
    if shutil.disk_usage(out).free < total + 512 * 1024**2:
        raise AppError("Not enough free storage for this backup")
    backup_id = stamp()
    target = out / f"{slug}-{backup_id}.tar.gz"
    meta = {"schema": 1, "id": backup_id, "slug": slug, "version": version, "created": time.time(), "config": config}
    tmp = target.with_suffix(".part")
    try:
        with tarfile.open(tmp, "w:gz") as tar:
            blob = json.dumps(meta, sort_keys=True).encode()
            info = tarfile.TarInfo("meta.json")
            info.size, info.mode, info.mtime = len(blob), 0o600, int(time.time())
            tar.addfile(info, io.BytesIO(blob))
            for name in ROOTS:
                if (root / name).is_dir():
                    tar.add(root / name, arcname=name, recursive=True)
        os.chmod(tmp, 0o600)
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)
    side = {**meta, "file": target.name, "size": target.stat().st_size, "sha256": _sha256(target)}
    write_json(out / f"{slug}-{backup_id}.json", side)
    return side


def listing(mgr, slug: str) -> list[dict]:
    rows = []
    for p in sorted(directory(mgr).glob(f"{slug}-*.json")):
        try:
            row = read_json(p)
        except AppError:
            continue
        if row.get("slug") == slug and ID.fullmatch(str(row.get("id", ""))):
            rows.append({k: row[k] for k in ("id", "slug", "version", "created", "size")})
    return rows


def find(mgr, slug: str, backup_id: str) -> tuple[dict, Path]:
    if not isinstance(backup_id, str) or not ID.fullmatch(backup_id):
        raise AppError("Unknown backup")
    out = directory(mgr)
    side = out / f"{slug}-{backup_id}.json"
    if not side.is_file():
        raise AppError("Unknown backup")
    meta = read_json(side)
    path = checked_path(out / str(meta.get("file", "")))
    if path.parent != out or meta.get("slug") != slug or meta.get("id") != backup_id or not path.is_file():
        raise AppError("Backup record does not match its file")
    if path.stat().st_size != meta.get("size") or _sha256(path) != meta.get("sha256"):
        raise AppError("Backup file failed its integrity check")
    return meta, path


def extract(path: Path, destination: Path) -> None:
    """Unpack only regular files and directories under data/ and addon_config/, into an empty `destination`."""
    destination.mkdir(mode=0o700)
    total = 0
    with tarfile.open(path, "r:gz") as tar:
        members = tar.getmembers()
        for m in members:
            parts = Path(m.name).parts
            if m.name == "meta.json":
                continue
            if (not parts or parts[0] not in ROOTS or m.name.startswith("/") or ".." in parts
                    or not (m.isreg() or m.isdir())):
                raise AppError("Backup contains an entry that is not allowed: " + m.name[:80])
            total += m.size
            if total > MAX_BYTES:
                raise AppError("Backup is larger than the supported size")
        if shutil.disk_usage(destination).free < total + 256 * 1024**2:
            raise AppError("Not enough free storage to restore this backup")
        for m in members:
            if m.name != "meta.json":
                tar.extract(m, destination, set_attrs=True, filter="data") if hasattr(tarfile, "data_filter") else tar.extract(m, destination)
