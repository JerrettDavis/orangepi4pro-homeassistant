#!/usr/bin/env bash
set -euo pipefail
repo=/opt/orangepi4pro-homeassistant
/usr/bin/python3 "$repo/scripts/publish-runtime.py" /etc/opiha/appliance.json
exec "$repo/bin/opiha" --config /etc/opiha/appliance.json up --onboarding
