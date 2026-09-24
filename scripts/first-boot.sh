#!/usr/bin/env bash
set -euo pipefail
repo=/opt/orangepi4pro-homeassistant
cfg=/etc/opiha/appliance.json
for account in opiha-status opiha-vision; do
  if ! id "$account" >/dev/null 2>&1; then
    useradd --system --user-group --no-create-home --shell /usr/sbin/nologin "$account"
  fi
done
if ! id opiha-kiosk >/dev/null 2>&1; then
  useradd --create-home --user-group --shell /bin/bash opiha-kiosk
  passwd --lock opiha-kiosk
fi
# Scrubbed images may retain the account but not its old home directory.
install -d -m 0700 -o opiha-kiosk -g opiha-kiosk /home/opiha-kiosk
getent group nopasswdlogin >/dev/null || groupadd --system nopasswdlogin
usermod -a -G nopasswdlogin opiha-kiosk
if [[ ! -f "$cfg" ]]; then
  "$repo/bin/opiha" --config "$cfg" init --mode appliance
  /usr/bin/python3 "$repo/scripts/apply-public-defaults.py" "$cfg" /etc/opiha/image-defaults.json
fi
install -d -m 0755 /run/opiha
install -d -m 0755 -o opiha-vision -g opiha-vision /run/opiha/status
ssh-keygen -A
if [[ -b /dev/disk/by-label/OPIHA_RECOVERY && -f /etc/opiha/recovery-trust.pem && ! -f /var/lib/opiha/restored.json && ! -f /srv/opiha/ha/configuration.yaml ]]; then
  install -d -m 0700 /run/opiha/recovery
  mount -o ro,nosuid,nodev,noexec /dev/disk/by-label/OPIHA_RECOVERY /run/opiha/recovery
  trap 'umount /run/opiha/recovery' EXIT
  "$repo/bin/opiha" --config "$cfg" recover --media /run/opiha/recovery --trust-key /etc/opiha/recovery-trust.pem --confirm-unattended
  umount /run/opiha/recovery
  trap - EXIT
fi
if [[ -f /opt/opiha-cache/manifest.json ]]; then
  /usr/bin/python3 "$repo/scripts/load-cache.py" --config "$cfg" --cache /opt/opiha-cache
fi
/usr/bin/python3 "$repo/scripts/publish-runtime.py" "$cfg"
