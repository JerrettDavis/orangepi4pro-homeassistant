# orangepi4pro-homeassistant

**A rebuildable home-control appliance for the Orange Pi 4 Pro, Allwinner A733.**

Version **0.1.0-alpha.1**. This is a complete source repository for local evaluation, migration rehearsals, a guarded image-overlay build, and subsequent recovery. It is **not a prebuilt, board-validated disk image**. Read [the validation report](reports/VALIDATION.md) before using it as the only controller for a home.

The current cyberdeck host has now been inspected read-only. Its NVMe boot
chain, custom kernel, Xorg display, and native touchscreen are
`orange-pi-observed`; no appliance containers, camera stream, Z-Wave radio, or
flashable image have yet been runtime-validated. See the sanitized
[live hardware baseline](docs/LIVE-HARDWARE-BASELINE.md).

The host is your existing boot-tested Ubuntu/Debian arm64 Orange Pi image. Home Assistant runs in Docker; the host owns the display and camera. Your household lives in a separately encrypted state bundle, never in Git or a public image.

```text
Existing Orange Pi A733 image + board-support kernel / boot assets
  ├─ Home Assistant Container                 /srv/opiha/ha
  ├─ optional Z-Wave JS UI → existing stick    /srv/opiha/zwave
  ├─ optional authenticated Mosquitto         /srv/opiha/mqtt
  ├─ optional go2rtc → V4L2 camera             /srv/opiha/camera
  ├─ native OpenCV person detector            /run/opiha/status
  ├─ LightDM / Openbox / browser kiosk        /srv/opiha/kiosk
  └─ opiha CLI + systemd + signed recovery

Public software image + private signed/encrypted state + external decryption key
                                   ↓
                        Restored home-control appliance
```

## Start on your PC

Use Linux or WSL2 with the repository in the Linux filesystem, not under `/mnt/c`. Python 3.10+ is required. Docker Engine with Compose v2 is needed only for container operations; the pure application tests do not need it.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
./scripts/test.sh
./scripts/test.sh --images

./bin/opiha init --mode lab
./bin/opiha render
./bin/opiha up
# Open http://127.0.0.1:18123
./bin/opiha down
```

The lab starts only HA, binds its UI to loopback, uses a Docker internal network, and passes through no hardware. It deliberately does not expose household integrations to the LAN. This is a migration rehearsal environment, not a substitute for a disconnected VLAN or a security sandbox. Restored integrations needing Internet downloads will not initialize in this quarantine. See [local testing](docs/QUICKSTART.md).

For a real migration, **set HA to your source instance's exact version before importing anything**. The shipped `2026.9.3` is an explicit software default, not a claim about your VM.

## Implemented in this release

| Area | Included |
|---|---|
| Runtime | Validated configuration; generated Compose JSON; explicit release tags; optional registry digest locking; per-service resource limits and loopback admin ports |
| Migration | Read-only config inventory, comparison, SQLite check, API health inventory, stopped `/config` import, stopped Z-Wave JS UI store import, PowerShell config export helper |
| State | Hash-manifested backup format; age encryption; Ed25519 signatures; quiesced snapshots; dry-run restore; atomic state replacement; retained rollback directory; interrupted-restore repair |
| Recovery | Signed removable-media first boot; external age identity; version checks; fresh-state gate; private portable service settings; production activation gate |
| Image | Explicit live-host overlay or clean-base `.img` copy builder; SHA verification; selected-root-partition mounting; scrubbing and audit; regenerated SSH host keys; public container cache |
| Display | Read-only diagnostic web page; browser kiosk; persistent browser profile; local person-presence display wake |
| Camera | go2rtc V4L2 stream configuration; executable CPU HOG/SVM detector; debounce, expiry, reconnect, no recording |
| HA customization | Generic seed dashboard/theme/status entities; optional explicitly pinned HACS software vendoring; existing config always wins |
| Development | Automated tests, CI, Docker smoke script, allowlisted source packaging, runbooks and hardware acceptance checklist |

**Not claimed:** A733 NPU support, vendor CSI/ISP driver bring-up, hardware video acceleration, Supervisor/add-on conversion, unattended initial OAuth enrollment, raw encrypted native-HA-backup extraction, production reliability, or boot-tested image artifacts. These are explicit boundaries, not hidden TODO implementations.

## The two restore paths

**First migration:** use Home Assistant's supported onboarding backup upload, or import a complete, consistently stopped `/config` copy. Native HA backups and this repo's appliance bundles are different formats. An HAOS add-on backup does not become a Compose service automatically.

**Subsequent reflashes:** use `opiha backup` to capture HA, the Z-Wave UI store, local MQTT state, camera config, local TLS/media/share files, private settings and the kiosk profile. Supply the encrypted bundle and identity separately from the image. Signed USB recovery verifies the sender, decrypts, restores, checks versions, and arms startup on fresh state.

External databases, NAS contents, OS network/mount policy, reverse-proxy services and revoked third-party authorizations still need their own recovery arrangements. See [recovery](docs/RECOVERY.md).

## Read in this order

1. [Quickstart and safe PC tests](docs/QUICKSTART.md)
2. [Hyper-V migration and Z-Wave cutover](docs/MIGRATION.md)
3. [Install on the existing Orange Pi host](docs/HOST-INSTALL.md)
4. [Build a custom image and offline container cache](docs/IMAGE-BUILD.md)
5. [Encrypted backups and signed unattended recovery](docs/RECOVERY.md)
6. [Display, camera, HACS and NPU boundaries](docs/HARDWARE.md)
7. [Architecture and operational contract](docs/ARCHITECTURE.md)
8. [Acceptance tests and next implementation steps](docs/NEXT-STEPS.md)

[Security](SECURITY.md) · [Command reference](docs/CLI.md) · [Upstream sources and version notes](docs/SOURCES.md) · [Validation](reports/VALIDATION.md)

## Existing repository boundaries

This repository does not pretend the upstream projects expose a finished image API that they do not have.

- `orangepi4pro-board-support`: kernel, device tree, drivers and boot compatibility.
- `orangepi4pro-images`: clean base images and generic image construction.
- `orangepi4pro-cyberdeck`: hardware/display bring-up and existing runbooks.
- This repository: the appliance overlay, state boundary, operational tooling and tests.

No kernel, bootloader or partition-table replacement is performed by this overlay. The image builder modifies a regular-file copy and the chosen Linux root partition only. Vendor image contents remain your responsibility: **never publish a clone of a used household disk**.

MIT license covers this repository's original code. Bundled/fetched upstream software retains its own licenses. No upstream container images, model archives, HACS release archives, household files or real credentials are included in this source release.
