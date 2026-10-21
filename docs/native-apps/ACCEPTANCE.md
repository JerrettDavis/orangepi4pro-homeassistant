# Acceptance on the actual Orange Pi

The included source tests do not establish that Home Assistant loaded this integration or that an app image ran on your board. Complete the following in stages without moving the production controller or replacing the existing OS.

## Local source checks

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
./scripts/test.sh -q
python3 -m compileall -q src homeassistant scripts
node --check homeassistant/custom_components/opiha_apps/panel.js
```

Install `age`/`age-keygen` to run the real encryption roundtrip instead of skipping it. Tests use synthetic credentials. Keep actual secrets outside the checkout. The optional browser test requires Playwright and Chromium; `scripts/browser-test.py --help` describes its in-memory, synthetic scope.

## Actual Docker smoke test

Use an empty test machine with a native Linux Docker Engine. This command is **not** designed to run beside an already-installed native manager: it creates its own private workspace but uses the fixed managed network and app names. It refuses foreign same-image applications rather than adopting them.

```bash
# Describe the operation without changing Docker.
python3 scripts/docker-smoke.py

# Root/Docker privileges and network access are required for the real test.
sudo python3 scripts/docker-smoke.py --app nodered --apply --confirm-network-access
```

The command pulls the explicit native image, prepares private state, creates and starts the selected blank app, probes its local HTTP endpoint, then stops/removes only its owned container. State, downloaded images and the network are retained for diagnosis. A local HTTP response is not proof that the application UI or every integration works. Run ESPHome and go2rtc separately after Node-RED.

## In-Home-Assistant acceptance

Install using `INSTALL.md`. Verify the original HA container and proxy are unchanged and port 8098 listens only on `127.0.0.1`. Validate HA configuration and restart HA once. Confirm the panel appears for an admin and is absent for the normal kiosk account; direct non-admin API calls must also be rejected.

For a blank Node-RED app, exercise Review, Install, Start, Open, logs, settings, Stop, and Start again. Confirm install initially leaves the container stopped. Create a harmless inject/debug flow and check it persists. Repeat over the existing HTTPS route and in the Companion App. Verify the editor's WebSocket connection and navigation, not just its first HTML response. Sign out/revoke the HA session and confirm the embedded route no longer grants access.

For ESPHome, open Device Builder, create a throwaway configuration, build one representative firmware project, and inspect its logs. Do not flash an existing device as a smoke test. Confirm the actual CPU, memory, toolchain persistence, prefix routing, and reconnect behavior. Test OTA/manual-IP access separately because bridged networking is not mDNS passthrough. Remote build pairing is optional and not configured by the adapter.

For go2rtc, start empty, then use a known encoded test stream. Check the prefix-aware UI and host-loopback RTSP endpoint. A stream does not prove local CSI/ISP, hardware encoding, NPU inference, or WebRTC transport.

For Mosquitto, verify anonymous connections fail, the generated account works, persistence survives restart, and existing MQTT services were not affected. For Z-Wave, keep the existing controller/server unchanged until a stopped export, original keys/store, exact version, persistent device and rollback are ready. Its native web UI is not embedded in this release.

## Performance and recovery

Run the before/after/load procedure in `PERFORMANCE.md`. Compare HA HTTP timing, real automation responsiveness, touchscreen scroll, thermal throttling, swap pressure and app OOM/restart events. Set a workload-specific acceptance threshold before deciding the result is acceptable. Do not mark an idle-only test as a firmware-build or camera-load qualification.

Create and verify an encrypted, signed native-app bundle with `BACKUP-RECOVERY.md`. Perform a fresh-directory recovery and confirm matching image/data after deliberately stopping the source apps. Keep the existing HA backup separate. Test reboot/autostart only after the blank apps work; do not power-cycle during an active image pull, database write or backup.

Record commands, exact software versions, pass/fail results and remaining limitations in a private acceptance report. Publish only sanitized conclusions. Do not replace the known-good boot system or retire the Hyper-V rollback because the source tests pass.
