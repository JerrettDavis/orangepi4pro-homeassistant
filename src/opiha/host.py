from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

from . import config
from .common import ApplianceError, REPO, atomic_json, atomic_bytes, private_mkdir, read_json


PUBLIC_DIRS = ("bin", "src", "scripts", "homeassistant", "web", "config", "vendor")
PUBLIC_FILES = ("README.md", "LICENSE", "VERSION", "pyproject.toml")


@dataclass(frozen=True)
class Layout:
    root: Path
    install_root: Path
    current: Path
    state_root: Path
    work_root: Path
    config: Path
    unit: Path
    manifest: Path

    @classmethod
    def for_root(cls, root: Path) -> "Layout":
        root = root.absolute()
        return cls(
            root=root,
            install_root=root / "opt/orangepi-homeassistant",
            current=root / "opt/orangepi-homeassistant/current",
            state_root=root / "srv/homeassistant",
            work_root=root / "var/lib/orangepi-homeassistant",
            config=root / "etc/orangepi-homeassistant/appliance.json",
            unit=root / "etc/systemd/system/orangepi-homeassistant.service",
            manifest=root / "var/lib/orangepi-homeassistant/deployment.json",
        )


def _validate_release(release: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,79}", release):
        raise ApplianceError("Invalid host release identifier")


def _reject_symlink_ancestors(path: Path, root: Path) -> None:
    current = path
    while True:
        if current.is_symlink():
            raise ApplianceError(f"Host destination contains a symlink: {current}")
        if current == root or current.parent == current:
            break
        current = current.parent


def _owned_files(layout: Layout) -> set[str]:
    if not layout.manifest.is_file():
        return set()
    try:
        document = json.loads(layout.manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return {str(value) for value in document.get("owned_files", [])}


def _relative(layout: Layout, path: Path) -> str:
    return path.relative_to(layout.root).as_posix()


def plan(*, root: Path = Path("/"), release: str) -> dict:
    _validate_release(release)
    layout = Layout.for_root(root)
    if not (layout.root / "etc/os-release").is_file():
        raise ApplianceError("Target does not look like a Linux root")
    for path in (
        layout.install_root,
        layout.state_root,
        layout.work_root,
        layout.config,
        layout.unit,
    ):
        _reject_symlink_ancestors(path, layout.root)
    owned = _owned_files(layout)
    for path, label in ((layout.unit, "unit"), (layout.config, "configuration")):
        if path.exists() and _relative(layout, path) not in owned:
            raise ApplianceError(f"Existing Home Assistant {label} is not owned by this installer")

    release_path = layout.install_root / "releases" / release
    if release_path.exists():
        try:
            manifest = read_manifest(layout)
        except ApplianceError as exc:
            raise ApplianceError("Existing host release is not owned by this installer") from exc
        if (
            manifest.get("release") != release
            or manifest.get("release_path") != _relative(layout, release_path)
            or manifest.get("release_sha256") != tree_sha256(release_path)
        ):
            raise ApplianceError("Existing host release is not owned by this installer")
    changes: list[str] = []
    if not release_path.exists():
        changes.append("install-release")
    if not layout.state_root.exists():
        changes.append("create-private-state")
    if not layout.config.exists():
        changes.append("create-appliance-config")
    if not layout.unit.exists():
        changes.append("install-disabled-unit")
    selected = Path("releases") / release
    if not layout.current.is_symlink() or Path(os.readlink(layout.current)) != selected:
        changes.append("select-release")
    return {
        "schema": 1,
        "apply": False,
        "root": str(layout.root),
        "release": release,
        "changes": changes,
        "starts_services": False,
        "enables_services": False,
        "installs_packages": False,
        "changes_boot_or_network": False,
    }


def tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root).as_posix().encode()
        if path.is_symlink():
            digest.update(b"L\0" + relative + b"\0" + os.readlink(path).encode() + b"\0")
        elif path.is_file():
            digest.update(b"F\0" + relative + b"\0")
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            digest.update(b"\0")
    return digest.hexdigest()


def read_manifest(layout: Layout) -> dict:
    value = read_json(layout.manifest)
    if not isinstance(value, dict) or value.get("schema") != 1:
        raise ApplianceError("Invalid host deployment manifest")
    return value


def _copy_release(destination: Path) -> None:
    for name in PUBLIC_DIRS:
        shutil.copytree(
            REPO / name,
            destination / name,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
        )
    for name in PUBLIC_FILES:
        source = REPO / name
        if source.is_file():
            shutil.copy2(source, destination / name)


def _unit_text() -> bytes:
    return b"""[Unit]
Description=Orange Pi Home Assistant container
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/opt/orangepi-homeassistant/current/bin/opiha --config /etc/orangepi-homeassistant/appliance.json up --onboarding
ExecStop=/opt/orangepi-homeassistant/current/bin/opiha --config /etc/orangepi-homeassistant/appliance.json down
TimeoutStartSec=0
TimeoutStopSec=180
UMask=0077
"""


def install(*, root: Path = Path("/"), release: str) -> dict:
    proposed = plan(root=root, release=release)
    layout = Layout.for_root(root)
    if layout.state_root.exists() and any(layout.state_root.iterdir()):
        if not (layout.state_root / ".opiha-state.json").is_file():
            raise ApplianceError("Refusing unowned populated state directory")

    releases = layout.install_root / "releases"
    releases.mkdir(parents=True, exist_ok=True)
    release_path = releases / release
    if not release_path.exists():
        staging = Path(tempfile.mkdtemp(prefix=f".{release}.", dir=releases))
        try:
            _copy_release(staging)
            staging.rename(release_path)
        finally:
            if staging.exists():
                shutil.rmtree(staging)

    private_mkdir(layout.state_root)
    if not (layout.state_root / ".opiha-state.json").exists():
        config.create_state(layout.state_root)
    private_mkdir(layout.work_root)
    private_mkdir(layout.config.parent)

    if not layout.config.exists():
        cfg = config.default_config("appliance", layout.config.parent)
        cfg.update(
            data_dir="/srv/homeassistant",
            work_dir="/var/lib/orangepi-homeassistant",
            status_dir="/run/orangepi-homeassistant/status",
        )
        config.validate(cfg)
        atomic_json(layout.config, cfg, 0o600)

    atomic_bytes(layout.unit, _unit_text(), 0o644)

    selected = Path("releases") / release
    temporary_link = layout.install_root / ".current.new"
    if temporary_link.exists() or temporary_link.is_symlink():
        temporary_link.unlink()
    temporary_link.symlink_to(selected, target_is_directory=True)
    os.replace(temporary_link, layout.current)

    owned = [_relative(layout, layout.config), _relative(layout, layout.unit)]
    manifest = {
        "schema": 1,
        "release": release,
        "release_sha256": tree_sha256(release_path),
        "release_path": _relative(layout, release_path),
        "owned_files": sorted(owned),
        "services_enabled": False,
        "services_started": False,
    }
    atomic_json(layout.manifest, manifest, 0o600)
    return {**proposed, "applied": True}
