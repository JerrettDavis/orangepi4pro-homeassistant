#!/usr/bin/env bash
set -euo pipefail

export DISPLAY="${DISPLAY:-:0}"
export XAUTHORITY="${XAUTHORITY:-$HOME/.Xauthority}"

for _ in $(seq 1 60); do
  xset q >/dev/null 2>&1 && break
  sleep 2
done
xset q >/dev/null 2>&1 || {
  echo "No usable existing X11 session" >&2
  exit 1
}

xset s off || echo "Display server did not accept screen-saver disable hint" >&2
xset -dpms || echo "Display server did not accept DPMS disable hint" >&2

url=http://127.0.0.1:8123/
for _ in $(seq 1 90); do
  curl --fail --silent --show-error --max-time 5 "$url" >/dev/null 2>&1 && break
  sleep 2
done
curl --fail --silent --show-error --max-time 5 "$url" >/dev/null || {
  echo "Home Assistant did not become ready" >&2
  exit 1
}

command -v firefox >/dev/null 2>&1 || {
  echo "Firefox is not installed" >&2
  exit 1
}

profile="$HOME/snap/firefox/common/opiha-kiosk"
install -d -m 0700 "$profile"

# The profile carries the user's HA session. It is private runtime state and is
# never embedded in the launch URL, service unit, repository, or public image.
echo "Launching Firefox kiosk against local Home Assistant" >&2
exec firefox --no-remote --profile "$profile" --kiosk "$url"
