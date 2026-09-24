# Migration from Hyper-V and a remote Z-Wave server

## Preserve a rollback before changing architecture

Record your source HA version, installation type, all installed Supervisor apps/add-ons, database backend and URL, MQTT endpoint, local TLS paths, media mounts, HACS/custom integrations and external services. The CLI inventories HA configuration, registries and custom-component manifests; it is not a Supervisor add-on export or a full infrastructure discovery tool.

Create a fresh **native Home Assistant backup** and retain its emergency kit/key separately. Keep an unchanged copy of the powered-off Hyper-V VM or its existing rollback mechanism. A VM checkpoint is not the only backup. Capture the independent Z-Wave server too: it is not necessarily inside the HA VM backup.

Use the same HA release on the Orange Pi for the first migration. Avoid a simultaneous kernel upgrade, HA upgrade and Z-Wave driver upgrade. The repository's release defaults are starting points; pin your source-compatible Z-Wave UI version privately when needed.

## Choose the first import method

### A. Native HA backup through onboarding

Install/start a new HA Container, open the HA onboarding page, and use its backup upload/restore flow with the required backup key. This is Home Assistant's supported migration route. **Do not pass that archive to `opiha restore`**: the formats are deliberately different, and this repository does not fake an undocumented decryption/onboarding API.

For a production-connected destination, stop the source VM before restoring and allowing the imported configuration to run. A restored copy can immediately execute automations, connect to cloud services and claim device connections. In a quarantine lab, expect network-dependent integrations and dependency downloads to fail.

HA Container has no Supervisor/apps. Export and recreate services such as Mosquitto, MariaDB, Node-RED or ESPHome separately. This release includes optional local MQTT and Z-Wave UI services, not a universal add-on converter. Do not delete the source VM until every required service has been accounted for.

### B. Stopped raw `/config` import

Use a complete, consistent config export, including dotfiles, `.storage`, `custom_components`, `www`, dashboards and the database. Do not copy a live SQLite file on its own. Stop HA cleanly and copy the whole directory, including any WAL/SHM files. A proper filesystem/database snapshot is an alternative only when its consistency is understood.

The Hyper-V host does not expose `/config` merely because it owns a VHDX. You need an actual file share/export of HA's config or a separately mounted consistent filesystem copy. The optional PowerShell helper works only with such a source:

```powershell
.\scripts\Export-HyperVConfig.ps1 `
  -SourceShare '\\YOUR-EXPORT-HOST\config' `
  -Destination 'D:\Private\ha-config-export' `
  -SourceStopped
```

This helper is source code provided for testing; PowerShell was not available in the build environment. It uses Robocopy, preserves dot-directories, checks exit codes, and refuses an existing nonempty destination. It does not stop HA for you and does not operate on VHDX files.

On the target:

```bash
sudo opiha configure --ha-version YOUR_SOURCE_RELEASE
sudo opiha inventory --ha-config /private/ha-config-export --output /private/before.json
sudo opiha import-config --source /private/ha-config-export --source-stopped
sudo opiha import-config --source /private/ha-config-export --source-stopped --apply --replace
sudo opiha inventory --output /private/after.json
sudo opiha compare /private/before.json /private/after.json
sudo opiha sqlite-check
```

Replace `YOUR_SOURCE_RELEASE` with a literal value such as `2026.9.3`, matching your actual VM. The copy process excludes dependency caches and bytecode so they can be rebuilt for arm64. A custom integration that embeds a native `.so` still needs its own ARM64-compatible build; inventory flags such files, but cannot manufacture compatible binaries.

Imports preserve other managed appliance components. They do not overwrite the existing configuration with repository seed YAML. Imported state remains disarmed until explicit cutover.

## Move the existing Z-Wave controller without rebuilding the mesh

Before disconnecting it, capture the remote server's full persistent store, version, Home ID, node inventory, NVM backup when supported, and existing S0/S2 keys, including any Long Range keys in use. Store them encrypted. No command in this repository creates replacement Z-Wave network keys, excludes devices or factory-resets a stick.

Stop the remote Z-Wave server. If it is **Z-Wave JS UI**, import its stopped store:

```bash
sudo opiha import-zwave --source /private/zwave-ui-store --source-stopped
sudo opiha import-zwave --source /private/zwave-ui-store --source-stopped --apply --replace
sudo opiha zwave-audit
ls -l /dev/serial/by-id/
sudo opiha configure --zwave-device '/dev/serial/by-id/YOUR_REAL_CONTROLLER_ID' --enable zwave
```

If the old server is a different packaging of Z-Wave JS, its data layout may not be a Z-Wave JS UI store. Export the keys/settings in that server's supported format and configure/import them into Z-Wave JS UI deliberately. Do not pass arbitrary add-on archives or a generic directory to `import-zwave` and assume equivalence. `zwave-audit` checks recognizable key fields and lengths; it does not validate the controller's actual network or radio state.

The local Z-Wave UI listens on loopback port 8091 and WebSocket 3000. The container's internal serial path is forced to `/dev/zwave`, and its WebSocket server is enabled through the documented external-settings mechanism. The HA integration should be **reconfigured**, keeping its existing entry and entity IDs, to:

```text
ws://127.0.0.1:3000
```

Use an SSH tunnel to review Z-Wave UI from your workstation:

```bash
ssh -L 8091:127.0.0.1:8091 ADMIN@ORANGE_PI_HOST
# Open http://127.0.0.1:8091
```

Existing Z-Wave UI auth is preserved. The image generates private default/session material but does not force a new auth mode or rotate an imported password. Loopback binding is the default exposure control. Enable/review UI authentication during the first enrollment.

## Cutover

Confirm the original HA VM and old Z-Wave server are stopped, and the controller is attached to only one server. Then:

```bash
sudo opiha activate --confirm-cutover
sudo systemctl restart opiha-stack.service
sudo opiha status
sudo opiha doctor
```

A missing optional camera or radio is reported without making HA itself dependent on that service starting. This does not mean that the unavailable feature is healthy.

Reconfigure the existing HA Z-Wave endpoint. Verify entity/device/area identity, several mains-powered nodes, battery nodes when they wake, secure device communication, automations, mobile apps, notifications and remote access. Reuse an old IP/DNS name only after the old server is off and after reviewing DHCP/reservations and TLS.

A private long-lived HA token may be used for read-only API checks:

```bash
sudo opiha live-check --token-file /private/ha-token.txt --output /private/live-target.json
```

The token is read from the file, not printed. The result still reveals entity IDs and should remain private. Counts alone cannot establish functional parity; use [the acceptance checklist](NEXT-STEPS.md).

## Rollback

Stop/deactivate the Orange Pi stack before moving the dongle back. Restore the previous host/server versions with their corresponding pre-upgrade state, then start the old VM. Never run both radio servers with one stick and never start two production HA copies as a shortcut.

Directory rollback preserves prior state but does not automatically roll back Docker versions, a controller firmware update, external databases or cloud-side changes. In particular, do not pair an old HA image with a database already migrated by a newer HA release. Keep matched version/state recovery points.
