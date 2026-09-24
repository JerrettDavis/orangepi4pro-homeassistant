# Upstream sources and version notes

Documentation/release choices were checked on 2026-09-23. No upstream image binary was downloaded into this source release. Release tags are explicit defaults, not a claim that they are the source household's versions or guaranteed immutable. Use exact migration versions and optional registry digest locking.

| Component | Default reference | Primary source |
|---|---|---|
| Home Assistant | `ghcr.io/home-assistant/home-assistant:2026.9.3` | https://github.com/home-assistant/core/releases/tag/2026.9.3 |
| Z-Wave JS UI | `zwavejs/zwave-js-ui:11.24.1` | https://github.com/zwave-js/zwave-js-ui/releases/tag/v11.24.1 |
| go2rtc | `alexxit/go2rtc:1.9.14` | https://github.com/AlexxIT/go2rtc/releases/tag/v1.9.14 |
| Mosquitto | `eclipse-mosquitto:2.0.22` | https://github.com/eclipse-mosquitto/mosquitto/releases/tag/v2.0.22 |

## Installation and restoration

- HA Linux/Container installation and installation-method boundaries: https://www.home-assistant.io/installation/linux/
- HA backup and migration/onboarding restore: https://www.home-assistant.io/common-tasks/general/
- HA backup integration: https://www.home-assistant.io/integrations/backup/
- Z-Wave JS, server topology, persistent device paths and network keys: https://www.home-assistant.io/integrations/zwave_js/
- Z-Wave JS UI environment settings for the selected version: https://raw.githubusercontent.com/zwave-js/zwave-js-ui/v11.24.1/docs/guide/env-vars.md
- Z-Wave JS UI container instructions: https://zwave-js.github.io/zwave-js-ui/#/getting-started/docker
- Docker's official Ubuntu installation instructions: https://docs.docker.com/engine/install/ubuntu/
- Compose env-file object options/version boundary: https://docs.docker.com/reference/compose-file/services/#env_file

The implementation uses native HA onboarding for native backups, not a fabricated archive parser. Generic HAOS apps/add-ons are outside its automatic conversion scope. An external Z-Wave server has independent state and needs a separate export.

## Hardware and UI

- Existing base image tooling and its current source/dry-run boundaries: https://github.com/JerrettDavis/orangepi4pro-images
- Board support, kernel, boot and touch details: https://github.com/JerrettDavis/orangepi4pro-board-support
- Cyberdeck planning and hardware runbooks: https://github.com/JerrettDavis/orangepi4pro-cyberdeck
- go2rtc upstream security guidance and integration configuration: https://github.com/AlexxIT/go2rtc
- go2rtc FFmpeg device modes: https://github.com/AlexxIT/go2rtc/blob/master/internal/ffmpeg/device/README.md
- go2rtc selected-version Linux device options: https://raw.githubusercontent.com/AlexxIT/go2rtc/v1.9.14/internal/ffmpeg/device/device_linux.go
- REST sensor integration: https://www.home-assistant.io/integrations/rest/
- Frigate detector integrations (not an A733 acceleration guarantee): https://docs.frigate.video/configuration/object_detectors/

The upstream device documentation states that format, size and frame rate must match the actual camera. A reported accelerator or a device node is not evidence that a model backend works. This repo implements only the documented CPU baseline described in HARDWARE.md.

## HACS and crypto

- HACS download: https://www.hacs.xyz/docs/use/download/download/
- HACS initial setup and GitHub authorization: https://www.hacs.xyz/docs/use/configuration/basic/
- age implementation/CLI: https://github.com/FiloSottile/age
- OpenSSL pkeyutl: https://docs.openssl.org/3.0/man1/openssl-pkeyutl/

HACS code can be fetched/pinned without publishing a household's OAuth state. A fresh OAuth enrollment is not bypassed. Age handles encryption; this repo's Ed25519 signature authenticates a domain-separated SHA256 digest of the encrypted archive.

External links document assumptions and upstream behavior. They do not imply those projects endorse this appliance or that this release has passed ARM64/hardware acceptance testing.
