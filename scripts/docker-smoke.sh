#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
cfg="$PWD/.local/smoke/appliance.json"
[[ ! -f "$cfg" ]] || { echo 'Smoke workspace already exists; inspect or remove it first.' >&2; exit 2; }
# No production restore, LAN access, USB, camera, credentials, or host network.
bin/opiha --config "$cfg" init --mode lab
trap 'bin/opiha --config "$cfg" down || true' EXIT
bin/opiha --config "$cfg" up
project="$(bin/opiha --config "$cfg" render | python3 -c 'import json,sys; print(json.load(sys.stdin)["name"])')"
container="$(docker ps -q \
  --filter "label=com.docker.compose.project=$project" \
  --filter 'label=com.docker.compose.service=homeassistant')"
[[ -n "$container" ]] || { echo 'FAIL: Home Assistant smoke container is missing' >&2; exit 1; }
OPIHA_SMOKE_CONTAINER="$container" python3 - <<'PY'
import os, subprocess, time
container = os.environ['OPIHA_SMOKE_CONTAINER']
for _ in range(90):
    status = subprocess.run(
        ['docker', 'inspect', '--format', '{{.State.Health.Status}}', container],
        check=False, capture_output=True, text=True,
    )
    if status.returncode == 0 and status.stdout.strip() == 'healthy':
        probe = subprocess.run(
            ['docker', 'exec', container, 'python3', '-c',
             "import urllib.request; assert urllib.request.urlopen('http://127.0.0.1:8123/',timeout=5).status == 200"],
            check=False,
        )
        if probe.returncode == 0:
            print('PASS: Home Assistant blank onboarding responds inside the quarantine network')
            break
    time.sleep(2)
else:
    raise SystemExit('FAIL: Home Assistant did not become HTTP-responsive')
PY
