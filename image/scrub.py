#!/usr/bin/env python3
"""Sanitize a COPY of an attested clean base. Never use on a live installation."""
from pathlib import Path
import argparse
import shutil
import sys
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--root', type=Path, required=True)
p.add_argument('--apply', action='store_true', required=True)
a = p.parse_args()
r = a.root.resolve()
if r == Path('/') or not (r / 'etc/os-release').exists():
    raise SystemExit('Refusing live or invalid root')

def remove(path: Path):
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)

# This is not a promise that an arbitrary personal disk clone can be made public.
for name in ('root', 'home', 'var/log', 'var/tmp', 'tmp', 'var/lib/cloud', 'var/lib/docker', 'var/lib/containerd',
             'var/lib/NetworkManager', 'var/lib/opiha', 'srv/opiha', 'etc/NetworkManager/system-connections'):
    path = r / name
    if path.is_symlink():
        raise SystemExit(f'Unexpected symlink in scrub target: {name}')
    if path.exists():
        for child in path.iterdir():
            remove(child)
for pattern in ('etc/ssh/ssh_host_*', 'etc/opiha/appliance.json', 'etc/opiha/backup.json',
                'etc/wpa_supplicant/*.conf', 'var/lib/dbus/machine-id', 'etc/machine-id'):
    for path in r.glob(pattern):
        remove(path)
(r / 'etc/machine-id').write_text('')
# Lock all password hashes, including vendor defaults. Access is via a supplied public SSH key.
shadow = r / 'etc/shadow'
if shadow.exists():
    rows = []
    for line in shadow.read_text().splitlines():
        fields = line.split(':')
        if len(fields) > 1:
            fields[1] = '!'
        rows.append(':'.join(fields))
    shadow.write_text('\n'.join(rows) + '\n')
ssh = r / 'etc/ssh/sshd_config.d'
ssh.mkdir(parents=True, exist_ok=True)
(ssh / '10-opiha-image.conf').write_text('PasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitRootLogin prohibit-password\n')
