#!/usr/bin/env bash
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "Run through sudo" >&2; exit 1; }
user=${1:-}
[[ $user =~ ^[a-z_][a-z0-9_-]*$ ]] || { echo "Supply the existing SSH username" >&2; exit 1; }
[[ ${SUDO_USER:-} == "$user" ]] || { echo "Username must match SUDO_USER" >&2; exit 1; }
/usr/bin/id "$user" >/dev/null 2>&1 || { echo "User does not exist" >&2; exit 1; }

repo=$(cd -- "$(/usr/bin/dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
"$repo/bin/opiha" host install --apply

wrapper=$(/usr/bin/mktemp)
trap '/bin/rm -f -- "$wrapper"' EXIT
printf '%s\n' '#!/bin/sh' \
  'exec /usr/bin/python3 /opt/orangepi-homeassistant/current/bin/opiha-admin "$@"' \
  > "$wrapper"
/usr/bin/install -o root -g root -m 0755 "$wrapper" /usr/local/sbin/opiha-admin
/bin/rm -f -- "$wrapper"
trap - EXIT

tmp=$(/usr/bin/mktemp /etc/sudoers.d/.orangepi-homeassistant.XXXXXX)
trap '/bin/rm -f -- "$tmp"' EXIT
printf '%s ALL=(root) NOPASSWD: /usr/local/sbin/opiha-admin\n' "$user" > "$tmp"
/bin/chmod 0440 "$tmp"
/usr/sbin/visudo -cf "$tmp" >/dev/null
/usr/bin/install -o root -g root -m 0440 "$tmp" /etc/sudoers.d/orangepi-homeassistant
/bin/rm -f -- "$tmp"
trap - EXIT

echo "Installed the appliance files and restricted passwordless admin wrapper."
echo "Verify with: sudo -n /usr/local/sbin/opiha-admin daemon-reload"
