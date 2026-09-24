#!/usr/bin/env python3
"""Encrypted snapshot to an existing off-box mounted destination; never silently falls back locally."""
import json
import os
from pathlib import Path
import subprocess
from datetime import datetime, timezone
s = json.loads(Path('/etc/opiha/backup.json').read_text())
mount = Path(s['mountpoint']).resolve()
output = Path(s['destination']).resolve()
if not mount.is_mount() or not (output == mount or mount in output.parents):
    raise SystemExit('Backup destination mount is unavailable; refusing a misleading local-only backup')
output.mkdir(parents=True, exist_ok=True)
name = datetime.now(timezone.utc).strftime('state-%Y%m%dT%H%M%SZ.tar.age')
args = ['/opt/orangepi4pro-homeassistant/bin/opiha', '--config', '/etc/opiha/appliance.json',
        'backup', '--output', str(output / name), '--recipient', s['recipient']]
if s.get('signing_key'):
    args += ['--signing-key', s['signing_key']]
subprocess.run(args, check=True)
# No automatic pruning in this alpha. Retention policy must not delete the only recovery point.
