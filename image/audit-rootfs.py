#!/usr/bin/env python3
"""Reject known private state patterns. Clean-base provenance is still mandatory."""
from pathlib import Path
import argparse
import re
import sys
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('root', type=Path)
a = p.parse_args()
r = a.root.resolve()
findings = []
for pattern in ('srv/opiha/ha/.storage/*', 'root/.ssh/id_*', 'home/*/.ssh/id_*',
                'etc/ssh/ssh_host_*_key', 'etc/NetworkManager/system-connections/*',
                'etc/opiha/appliance.json', 'etc/opiha/backup.json', 'var/lib/docker/containers/*',
                'etc/apt/auth.conf', 'etc/apt/auth.conf.d/*'):
    findings += [str(f.relative_to(r)) for f in r.glob(pattern) if f.is_file()]
for folder in ('etc/netplan', 'etc/cloud/cloud.cfg.d'):
    for f in (r / folder).glob('*'):
        if f.is_file() and re.search(r'password\s*:|auth[-_]token\s*:|BEGIN .*PRIVATE KEY|AGE-SECRET-KEY-', f.read_text(errors='replace'), re.I):
            findings.append(str(f.relative_to(r)))
if findings:
    print('Known private content remains. These paths require review:', file=sys.stderr)
    print('\n'.join(sorted(set(findings))), file=sys.stderr)
    raise SystemExit(1)
print('Known-state audit passed. This does not prove an arbitrary used disk image is safe to publish.')
