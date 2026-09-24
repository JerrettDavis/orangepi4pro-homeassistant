#!/usr/bin/env bash
set -euo pipefail

dbus_send_command=${DBUS_SEND_COMMAND:-dbus-send}
exec "$dbus_send_command" --session --type=method_call \
  --dest=org.onboard.Onboard \
  /org/onboard/Onboard/Keyboard \
  org.onboard.Onboard.Keyboard.ToggleVisible
