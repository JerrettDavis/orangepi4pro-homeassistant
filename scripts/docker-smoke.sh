#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
cfg="$PWD/.local/smoke/appliance.json"
[[ ! -f "$cfg" ]] || { echo 'Smoke workspace already exists; inspect or remove it first.' >&2; exit 2; }
# No production restore, LAN access, USB, camera, credentials, or host network.
bin/opiha --config "$cfg" init --mode lab
bin/opiha --config "$cfg" configure --lab-port 28123
trap 'bin/opiha --config "$cfg" down || true' EXIT
bin/opiha --config "$cfg" up
python3 - <<'PY'
import time, urllib.request
for _ in range(90):
    try:
        with urllib.request.urlopen('http://127.0.0.1:28123/', timeout=3) as r:
            if r.status == 200:
                print('PASS: Home Assistant blank onboarding responds in quarantine lab')
                break
    except OSError:
        pass
    time.sleep(2)
else:
    raise SystemExit('FAIL: Home Assistant did not become HTTP-responsive')
PY
