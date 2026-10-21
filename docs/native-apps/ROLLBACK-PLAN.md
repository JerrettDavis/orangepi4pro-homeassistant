# Native apps: production rollback plan

Before the first change an age-encrypted archive of the HA configuration (excluding the recorder database and HA backups), `/etc/orangepi-homeassistant`, the systemd units and `/etc/docker` was written on the appliance and copied off-box; its SHA-256 was compared on both ends and a decrypt + content comparison succeeded. The age identity is stored off-box only. HA automatic backups (including the database) remain the database recovery path.

Rollback of the native layer, in order, never touches HA data, the proxy, the kiosk, networking or boot:

1. `sudo systemctl disable --now orangepi-apps.service`; remove app containers named `opiha-apps-*` with the panel or `opiha-apps app remove <slug>` (data is retained).
2. Restore `configuration.yaml` from `/etc/orangepi-apps/configuration-before-*.yaml` (the only edit is a trailing `opiha_apps:` key), delete `<ha>/custom_components/opiha_apps` and `<ha>/opiha-apps-connection.json`, then restart HA with `opiha-admin restart`.
3. Remove `/etc/systemd/system/orangepi-apps.service`, `/opt/orangepi-apps`, `/etc/orangepi-apps`; `systemctl daemon-reload`.
4. Optionally revert the fstab line for `/srv/orangepi-apps` and `/etc/sysstat/sysstat` from their saved copies.
