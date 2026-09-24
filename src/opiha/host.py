from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re

from .common import ApplianceError


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


def _owned_unit(layout: Layout) -> bool:
    if not layout.manifest.is_file():
        return False
    try:
        document = json.loads(layout.manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return str(layout.unit.relative_to(layout.root)) in document.get("owned_files", [])


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
    if layout.unit.exists() and not _owned_unit(layout):
        raise ApplianceError("Existing Home Assistant unit is not owned by this installer")

    release_path = layout.install_root / "releases" / release
    changes: list[str] = []
    if not release_path.exists():
        changes.append("install-release")
    if not layout.state_root.exists():
        changes.append("create-private-state")
    if not layout.config.exists():
        changes.append("create-appliance-config")
    if not layout.unit.exists():
        changes.append("install-disabled-unit")
    if not layout.current.exists() or not layout.current.is_symlink():
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
