# Public image integration

This release does not build or flash an A733 HAOS image. It supplies public native-app software for the existing cyberdeck image pipeline. No virtual machine is involved.

After your existing builder mounts a **clean base root filesystem**, stage the public payload:

```bash
python3 scripts/stage-image.py --root /path/to/mounted/build-root
sudo python3 scripts/stage-image.py --root /path/to/mounted/build-root --apply
```

The destination is `/usr/share/opiha-native-apps`. The script never writes boot assets, partitions, tokens, HA state, unit enablement or network configuration. It refuses `/`, known household state and conflicting payload files. These are guards on this payload, **not an audit of every secret that could exist in an arbitrary vendor or used image**. Never publish a clone of the running household disk.

Keep the base appliance's existing first-boot provisioning responsible for storage, its private appliance JSON and a valid HA configuration. Once those exist, the on-device provisioning step is:

```bash
python3 /usr/share/opiha-native-apps/bin/opiha-apps install-host --apply
systemctl daemon-reload
systemctl enable --now orangepi-apps.service
```

The installer generates new private credentials at runtime. Validate HA configuration and start/restart HA only at the intended first-boot/maintenance boundary. With a restored HA backup, use the matching release and the documented `--adopt-restored-panel` path. The stage command alone does not wire these actions into your existing pipeline; make that change in the local session after verifying its current first-boot ordering.

Recover native-app data separately using its signed/encrypted bundle. Restore does not automatically start apps or rewrite host settings. A signed HA backup and a signed native-app backup have different formats and cannot be substituted for one another.

For public releases retain the source commit, base-image identity, payload version, file hashes, exact container references and licenses. Downloaded container layers or vendor drivers retain upstream licenses. Validate a clean build and a recovery drill on spare media before making a reflash the primary recovery path. No current root disk needs to be flashed just to install this layer.
