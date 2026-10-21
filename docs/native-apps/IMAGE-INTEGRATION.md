# Public image integration

This release does not build or flash an A733 HAOS image and involves no virtual machine. The native app manager is part of the existing image pipeline: `image/overlay.py` copies the repository (including `src/opiha_apps`, `homeassistant/custom_components/opiha_apps` and `bin/opiha-apps`) into `/opt/orangepi4pro-homeassistant` and installs the `/usr/local/bin/opiha-apps` wrapper.

The overlay is **code only**. It deliberately does not create or enable any of the following; the audit script `image/audit-rootfs.py` rejects them if they appear in a rootfs:

- `/etc/orangepi-apps/*` (manager configuration and its private credential),
- `/srv/orangepi-apps/*` (app state and rollbacks),
- `orangepi-apps.service` or any `*.wants` link for it,
- `<data_dir>/ha/opiha-apps-connection.json` (HA panel credential).

First boot is therefore unchanged. After the appliance provisioning created its private appliance JSON and a valid HA configuration, an administrator opts in once on the running machine:

```bash
sudo opiha-apps install-host            # preview, nothing changes
sudo opiha-apps install-host --apply
sudo systemctl daemon-reload && sudo systemctl enable --now orangepi-apps.service
```

The installer generates new private credentials at runtime. With a restored HA backup that already contains the panel, use the matching release and `--adopt-restored-panel`. Validate HA configuration and restart HA only at the intended maintenance boundary.

Recover native-app data separately using its signed/encrypted bundle (`opiha-apps backup` / `restore`, see [Backup and recovery](BACKUP-RECOVERY.md)). A signed HA backup, an `opiha-state-v1` appliance bundle and a native-app bundle have different formats and cannot be substituted for one another.

Never publish a clone of a running household disk. For public releases retain the source commit, base-image identity, file hashes, the digest-pinned container references in `src/opiha_apps/catalog.py` and the upstream licenses. Validate a clean build and a recovery drill on spare media before making a reflash the primary recovery path.
