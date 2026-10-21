"""App-data copies with a bounded, validated symlink policy.

Node-RED/npm legitimately creates relative links in node_modules/.bin. Internal
relative links are retained. Absolute/escaping links and special files are rejected.
"""
from __future__ import annotations
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
from .common import AppError, checked_path


def inventory(root: Path, max_bytes: int = 64 * 1024**3, max_files: int = 250000) -> tuple[list[Path], int]:
    checked_path(root)
    files, size = [], 0
    for directory, dirs, names in os.walk(root, followlinks=False):
        for name in sorted(dirs + names):
            path = Path(directory) / name
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                link = os.readlink(path)
                if os.path.isabs(link) or "\x00" in link or "\\" in link:
                    raise AppError("An application file links outside its data directory")
                try:
                    target = path.resolve(strict=False)
                except (RuntimeError, OSError) as exc:
                    raise AppError("Cyclic or invalid application symlink") from exc
                if target != root and root not in target.parents:
                    raise AppError("An application symlink escapes its data directory")
            elif stat.S_ISREG(info.st_mode):
                size += info.st_size
            elif not stat.S_ISDIR(info.st_mode):
                raise AppError("Application data contains a socket, device, or other special file")
            files.append(path)
            if size > max_bytes or len(files) > max_files:
                raise AppError("Application data exceeds the snapshot limits")
    return files, size


def copy_tree(source: Path, destination: Path) -> None:
    _, size = inventory(source)
    checked_path(destination)
    if destination.exists():
        raise AppError("Snapshot destination already exists")
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if shutil.disk_usage(destination.parent).free < size + 256 * 1024**2:
        raise AppError("Not enough free storage for a complete rollback copy")
    shutil.copytree(source, destination, symlinks=True)


def set_owner(root: Path, uid: int) -> None:
    files, _ = inventory(root)
    if os.geteuid() == 0:
        os.chown(root, uid, uid)
        for path in files:
            os.chown(path, uid, uid, follow_symlinks=False)
