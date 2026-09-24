#!/usr/bin/env bash
set -euo pipefail
export DISPLAY="${DISPLAY:-:0}"
export XAUTHORITY="${XAUTHORITY:-/home/opiha-kiosk/.Xauthority}"
# LightDM owns the graphical session; never start a competing X server.
for _ in $(seq 1 60); do
  if xset q >/dev/null 2>&1; then break; fi
  sleep 2
done
xset q >/dev/null 2>&1 || { echo 'No usable X11 session. Check LightDM autologin and XAUTHORITY.' >&2; exit 1; }
xset s off
xset +dpms
xset dpms 0 0 600
profile=/srv/opiha/kiosk/browser
mkdir -p "$profile"
/opt/orangepi4pro-homeassistant/scripts/wake-screen.py &
wake_pid=$!
trap 'kill "$wake_pid" 2>/dev/null || true' EXIT
url=http://127.0.0.1:8099/
if command -v chromium >/dev/null 2>&1; then browser=chromium
elif command -v chromium-browser >/dev/null 2>&1; then browser=chromium-browser
elif command -v firefox >/dev/null 2>&1; then
  firefox --no-remote --profile "$profile" --kiosk "$url"
  exit $?
else echo 'Install a working Chromium or Firefox browser in the base OS.' >&2; exit 1
fi
# Never --no-sandbox and never embed HA credentials in launch arguments.
"$browser" --kiosk --no-first-run --no-default-browser-check --disable-session-crashed-bubble \
  --user-data-dir="$profile" "$url"
