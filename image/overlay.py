#!/usr/bin/env python3
"""Install source/services into a mounted rootfs, or a live machine with explicit consent.
Never touches the bootloader, kernel, partition table, or existing household state.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from opiha.common import ApplianceError, REPO, atomic_json, atomic_bytes
from opiha import __version__

PUBLIC_DIRS = ('bin', 'src', 'scripts', 'image', 'systemd', 'homeassistant', 'web', 'config', 'vendor')


def apply(root: Path, live: bool, kiosk: bool, public_defaults: Path, trust_key: Path | None = None) -> None:
    root = root.resolve()
    if root == Path('/') and not live:
        raise ApplianceError('Live root requires --live')
    if root != Path('/') and not (root / 'etc/os-release').is_file():
        raise ApplianceError('Target does not look like a mounted Linux root filesystem')
    if not live and (root / 'srv/opiha/ha/.storage').exists():
        raise ApplianceError('Image root contains household state. Use a clean base, not a live disk clone')
    defaults = json.loads(public_defaults.read_text())
    if set(defaults) - {'ha_version', 'images', 'timezone', 'dashboard_path'}:
        raise ApplianceError('Public defaults contain unsupported fields')
    destination = root / 'opt/orangepi4pro-homeassistant'
    if root != Path('/') and not destination.resolve().is_relative_to(root):
        raise ApplianceError('Destination escapes mounted root')
    destination.mkdir(parents=True, exist_ok=True)
    for name in PUBLIC_DIRS:
        source = REPO / name
        shutil.copytree(source, destination / name, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo'))
    for name in ('README.md', 'LICENSE', 'VERSION', 'pyproject.toml'):
        if (REPO / name).exists():
            shutil.copy2(REPO / name, destination / name)
    # The image ships code, never .local, .git, test output or actual runtime config.
    etc = root / 'etc/opiha'
    etc.mkdir(parents=True, exist_ok=True)
    atomic_json(etc / 'image-defaults.json', defaults, 0o644)
    atomic_json(etc / 'installation.json', {'version': __version__, 'kiosk': kiosk}, 0o644)
    if trust_key:
        text = trust_key.read_text()
        if not text.startswith('-----BEGIN PUBLIC KEY-----') or 'PRIVATE KEY' in text:
            raise ApplianceError('Recovery trust material must be a PUBLIC key')
        atomic_bytes(etc / 'recovery-trust.pem', text.encode(), 0o644)
    units = root / 'etc/systemd/system'
    units.mkdir(parents=True, exist_ok=True)
    for unit in (REPO / 'systemd').glob('*'):
        shutil.copy2(unit, units / unit.name)
    enabled = ['opiha-firstboot.service', 'opiha-stack.service', 'opiha-status.service', 'opiha-vision.service']
    if kiosk:
        enabled.append('opiha-kiosk.service')
        lightdm = root / 'etc/lightdm/lightdm.conf.d/80-opiha-kiosk.conf'
        atomic_bytes(lightdm, b'[Seat:*]\nautologin-user=opiha-kiosk\nautologin-user-timeout=0\nuser-session=openbox\n', 0o644)
    for name in enabled:
        wants = units / ('graphical.target.wants' if name == 'opiha-kiosk.service' else 'multi-user.target.wants')
        wants.mkdir(parents=True, exist_ok=True)
        link = wants / name
        if not link.exists():
            link.symlink_to('../' + name)
    atomic_bytes(root / 'usr/local/bin/opiha', b'#!/bin/sh\nexec /opt/orangepi4pro-homeassistant/bin/opiha --config /etc/opiha/appliance.json "$@"\n', 0o755)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--target-root', type=Path, required=True)
    p.add_argument('--apply', action='store_true')
    p.add_argument('--live', action='store_true')
    p.add_argument('--enable-kiosk', action='store_true')
    p.add_argument('--public-defaults', type=Path, default=REPO / 'config/image-defaults.json')
    p.add_argument('--trust-key', type=Path)
    a = p.parse_args()
    if not a.apply:
        print(json.dumps({'dry_run': True, 'target': str(a.target_root.resolve()), 'kiosk': a.enable_kiosk,
                          'boot_assets_modified': False, 'services_started': False}, indent=2))
        return 0
    if os.geteuid() != 0:
        raise ApplianceError('Applying a host/rootfs overlay requires root')
    apply(a.target_root, a.live, a.enable_kiosk, a.public_defaults, a.trust_key)
    print('Overlay installed. Services were not started and household state was not modified.')
    return 0

if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ApplianceError, OSError, ValueError) as e:
        print(f'overlay: {e}', file=sys.stderr)
        raise SystemExit(2)
