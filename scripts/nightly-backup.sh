#!/usr/bin/env bash
set -euo pipefail
# This is a local private configuration, never an image artifact.
settings=/etc/opiha/backup.json
[[ -f "$settings" ]] || { echo 'Configure /etc/opiha/backup.json before enabling the timer.' >&2; exit 1; }
exec /usr/bin/python3 /opt/orangepi4pro-homeassistant/scripts/nightly-backup.py
