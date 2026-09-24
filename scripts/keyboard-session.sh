#!/usr/bin/env bash
set -euo pipefail

gsettings_command=${GSETTINGS_COMMAND:-gsettings}
onboard_command=${ONBOARD_COMMAND:-onboard}
command -v "$gsettings_command" >/dev/null || { echo "gsettings is required" >&2; exit 1; }
command -v "$onboard_command" >/dev/null || { echo "Onboard is required" >&2; exit 1; }

# Keep the keyboard hidden until focus or an explicit toggle requests it.
"$gsettings_command" set org.onboard.auto-show enabled true
"$gsettings_command" set org.onboard start-minimized true
"$gsettings_command" set org.onboard.icon-palette in-use true
"$gsettings_command" set org.onboard show-status-icon true
"$gsettings_command" set org.onboard.window docking-enabled false
"$gsettings_command" set org.onboard.window force-to-top true
"$gsettings_command" set org.onboard.window.landscape x 0
"$gsettings_command" set org.onboard.window.landscape y 395
"$gsettings_command" set org.onboard.window.landscape width 1024
"$gsettings_command" set org.onboard.window.landscape height 205

exec "$onboard_command" --not-show-in=
