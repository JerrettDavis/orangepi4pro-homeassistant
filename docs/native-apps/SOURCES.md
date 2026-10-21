# Source provenance and compatibility references

Reviewed for the September 24, 2026 iteration. These links establish upstream contracts, not on-device validation of this release. No third-party source or container layers are bundled in this module.

## Existing project

- Current upstream inspected through the connected GitHub tool: https://github.com/JerrettDavis/orangepi4pro-homeassistant/tree/7f77df51b528a4d6e30c82a8a251000b1d84a896
- Recorded hardware state: https://github.com/JerrettDavis/orangepi4pro-homeassistant/blob/7f77df51b528a4d6e30c82a8a251000b1d84a896/docs/LIVE-HARDWARE-BASELINE.md
- Existing host paths/ownership: https://github.com/JerrettDavis/orangepi4pro-homeassistant/blob/7f77df51b528a4d6e30c82a8a251000b1d84a896/src/opiha/host.py
- Existing HTTPS and service layout: https://github.com/JerrettDavis/orangepi4pro-homeassistant/blob/7f77df51b528a4d6e30c82a8a251000b1d84a896/src/opiha/compose.py
- Working Firefox touch launcher: https://github.com/JerrettDavis/orangepi4pro-homeassistant/blob/7f77df51b528a4d6e30c82a8a251000b1d84a896/scripts/kiosk-session.sh

## HA and Docker contracts

- Supervisor responsibilities and official apps: https://developers.home-assistant.io/docs/supervisor/
- Supervisor supported OS: https://www.home-assistant.io/more-info/unsupported/os
- HA 2026.9.3 custom panel registration: https://github.com/home-assistant/core/blob/2026.9.3/homeassistant/components/panel_custom/__init__.py
- HA 2026.9.3 HTTP authentication: https://github.com/home-assistant/core/blob/2026.9.3/homeassistant/components/http/auth.py
- HA 2026.9.3 request-user constants: https://github.com/home-assistant/core/blob/2026.9.3/homeassistant/components/http/const.py
- Docker memory/swap and CPU-share semantics: https://docs.docker.com/engine/containers/resource_constraints/

## Native application references

- Node-RED native Docker: https://nodered.org/docs/getting-started/docker
- Node-RED 5.0.7 release: https://github.com/node-red/node-red/releases/tag/5.0.7
- ESPHome native image with pinned Device Builder 1.14.9: https://github.com/esphome/esphome/blob/2026.9.0/docker/Dockerfile
- ESPHome dashboard command routing/persistent toolchain paths: https://github.com/esphome/esphome/blob/2026.9.0/docker/docker_entrypoint.sh
- Device Builder proxy prefixes, host/origin checks and remote build pairing: https://github.com/esphome/device-builder/blob/main/README.md (moving documentation; confirm against the shipped image)
- go2rtc configuration and native images: https://github.com/AlexxIT/go2rtc
- Mosquitto native Docker: https://hub.docker.com/_/eclipse-mosquitto
- Z-Wave JS UI native Docker: https://zwave-js.github.io/zwave-js-ui/#/getting-started/docker

Application versions are defaults, not automatic latest-version promises. Runtime digest and native-architecture checks are mandatory. A registry digest is content identity, not an independent signature or publisher attestation.
