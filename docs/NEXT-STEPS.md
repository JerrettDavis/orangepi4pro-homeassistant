# Acceptance checklist and next steps

## Gate 1: workstation rehearsal

Run the full Python/shell test suite, then the real Docker smoke test. Confirm
the lab publishes no host port, the network is internal, and no camera/radio is
passed through. Import a stopped config copy and compare registries before
starting HA. Expect Internet/LAN integrations to be unavailable in quarantine.
Review native-extension warnings and list missing external/add-on services.

Do not proceed merely because entity counts match. Read actual logs, custom-integration import failures, SQLite checks, restored auth and dashboard availability. Retain the source native HA backup and its emergency kit.

## Gate 2: Orange Pi host baseline

The read-only portion of this gate was completed on September 23, 2026 and is
recorded in [the sanitized live baseline](LIVE-HARDWARE-BASELINE.md). Kernel,
NVMe boot roles, display, and native touch are observed. Docker workload,
camera, Z-Wave, kiosk, and appliance restart behavior remain unvalidated.

Use the existing boot-tested kernel and storage setup. Verify cold boot with the actual SD/NVMe boot chain; Ethernet; system time; unique SSH host keys; arm64 Docker images; reboot restart; display/touch and browser sandbox; power/thermal behavior. Test a separate spare destination disk/image before overwriting the only bootable setup.

Confirm the base rootfs has a real browser, age, OpenSSL, Python/OpenCV, Docker Compose, and enough space for current state plus a restore staging/rollback tree. Verify optional service failure does not prevent HA from starting.

## Gate 3: household cutover

Record source HA/Z-Wave versions and Home ID; stop both source services; export the old JS UI store and retain network keys/NVM; attach the original dongle; restore HA; reconfigure the existing HA Z-Wave connection. Preserve IDs rather than deleting/re-adding the integration.

Test the following against a written baseline:

| Item | Required observation |
|---|---|
| Identity | Same expected integration/device/entity/area IDs; no unexpected duplicates |
| History | Expected recorder range and representative long-term statistics |
| Custom code | Required HACS cards/integrations load with correct versions |
| Z-Wave | Home ID/nodes preserved; secure traffic works; sleeping devices update when awake |
| Automations | Representative triggers/actions work once, not twice |
| External services | MQTT, database, DNS/TLS, notifications, phone apps and remote access as applicable |
| Kiosk | Login persistence, touch accuracy, restart, idle blanking and wake |
| Camera | Supported V4L2 format, stable stream, detector staleness/unavailable behavior |
| Resources | Stable memory/temperature/CPU and acceptable HA latency under combined load |

Do not use door unlocking or safety-critical actions as the first automated test. Verify actuators deliberately and safely. Keep the old VM off but intact until you have observed normal household behavior over several days.

## Gate 4: actual recovery drill

Create a signed encrypted appliance backup, then verify/decrypt it on a separate fresh test target. Test corrupted ciphertext, wrong signature, wrong key, unsupported version, missing USB/controller, interrupted restore, and absent backup mount. Confirm all failures are visible and do not replace an existing household.

Flash a reviewed clean image on spare media, insert the private signed recovery medium, and cold boot. Confirm restored IDs, local Z-Wave connectivity, kiosk and expected credentials. Remove the USB. Verify the source VM/server remain stopped. This drill, not the existence of a backup file, establishes that the recovery path works on your hardware.

## Gate 5: image publication

Publish only clean-source image artifacts after rootfs audit and manual secret review. Record exact upstream base hash, board-support revision, package inventory, service versions/digests and a hardware acceptance report. The source CI does not boot your panel/camera/radio. No unattended privileged PR builds should run on a trusted image builder.

## Concrete implementation queue after the first hardware results

1. Wire the overlay into the real `orangepi4pro-images` rootfs hook and record its supported base revision. Add the specific A733 camera/ISP and browser requirements discovered during bring-up.
2. Add authenticated private site provisioning for network settings, off-box mounts and backup policy, with the same fresh-state/signature boundary. Those OS settings are intentionally not restored from arbitrary archive paths today.
3. Replace/augment HOG with a validated person model. Investigate A733 `galcore`/SDK/model conversion only after obtaining matching drivers, redistribution rights and a working reference model. Benchmark against the same camera corpus and preserve CPU fallback.
4. Add a tested external-service migration profile for whichever add-ons/database/MQTT deployment your actual inventory reveals. Avoid speculative services that complicate the first cutover.
5. Tighten reproducible builds with distro snapshots, pinned OS packages, signed release manifests, rootfs resize tooling and automated physical cold-boot/recovery tests.

No NPU backend, migration profile or fully unattended initial OAuth setup is claimed to exist merely because it is listed here.
