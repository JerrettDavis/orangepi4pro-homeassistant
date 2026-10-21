# Removing the native layer without reverting the appliance

The original Home Assistant, proxy, cyberdeck boot, Firefox, camera and radio stack is outside this manager's ownership. Do not roll those back just to remove this panel.

First export any useful new app state and stop each **newly managed app** through the panel or CLI. A stopped manager does not itself stop Docker containers with an enabled restart policy. Disable app autostart deliberately before removing the manager. Broker/radio/flow clients can be affected when their server stops; check dependencies first.

```bash
sudo python3 /opt/orangepi-apps/current/bin/opiha-apps app stop nodered --apply
sudo systemctl disable --now orangepi-apps.service
```

Repeat the stop action only for installed apps; do not use a blanket `docker stop` or `docker system prune`. Keep `/srv/orangepi-apps` and the private backup until recovery is verified.

Remove only the added empty `opiha_apps:` stanza from the current HA YAML. Validate configuration and restart HA once. Do **not** restore the entire old YAML backup over unrelated newer edits. After HA is no longer loading the integration, remove its `custom_components/opiha_apps` directory and private `opiha-apps-connection.json` if desired. Keep deployment ownership metadata until any later reinstall is reconciled.

There is no automatic destructive uninstall in this alpha. Inspect the recorded ownership/checksums before deleting the native unit or release directories. Never remove the original appliance directories or current-release selector: they have different names. Kernel/boot/network rollback is neither needed nor provided by this layer.

For one failed app update use the narrower recorded transaction repair in `BACKUP-RECOVERY.md`, which restores the matching old image/data rather than downgrading a migrated database in place.
