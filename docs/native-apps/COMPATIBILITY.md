# Catalog compatibility

An adapter is an explicit native deployment contract, not a claim that an arbitrary HA add-on works outside Supervisor. The five included adapters require real Docker/ARM64 and in-HA acceptance on the Orange Pi. Their templates, data handling and gateway contracts were tested with documented test doubles where hardware was unavailable.

| Application | Native contract | Important limits |
|---|---|---|
| Node-RED | Official container, `/data`, UID 1000, prefixed editor and HTTP nodes. | HA WebSocket nodes and HA credentials must be configured deliberately. No fake Supervisor token. Palette packages and flows are trusted executable code. |
| ESPHome | Official 2026.9.0 container, which pins Device Builder 1.14.9; `/config`, persistent toolchain cache, requested one-process compile limit. | Bridged networking does not supply mDNS discovery. Use fixed IP/manual peer configuration. OTA is the starting path; USB/Web Serial capability is not granted by this adapter. Remote builds are not automatically paired. |
| go2rtc | Native container, private configuration, prefixed API/UI, loopback RTSP port 28554. | No local `/dev/video`, encoder or NPU is assumed. No browser WebRTC transport port is opened. This is not a Frigate object-detection/NVR deployment. |
| Mosquitto | Native authenticated broker; private generated account; UID 1883; persistent data. | Host clients use the selected loopback port, default 21883. Other manager apps use `opiha-apps-mosquitto:1883`. Existing LAN clients cannot reach a loopback-only broker directly; do not migrate them by accident. |
| Z-Wave JS UI | Native image, persistent store, optional exact serial-by-id mapping, UI port 28091 and server port 23000 on loopback. | Start requires the restored original `settings.json`, device presence and explicit migration review. Existing external deployments block automatic takeover. The upstream web UI is not embedded in this release; use the existing secured proxy or an SSH tunnel. |

The defaults are explicit release tags, not `latest`. A tag may disappear or an upstream image may cease publishing ARM64; that must fail the pull/architecture check, not invoke emulation. A release tag is not a signed supply-chain attestation. Container images are not bundled in this ZIP.

## Existing services

The image repository and Docker ownership labels are used to identify services already managed elsewhere. Such entries are read-only in the new catalog. The manager will not infer where your old credentials live, copy a live broker database, or start a second process on a controller. Complete service migration needs a stopped export, original credentials, a version match and a deliberate endpoint change.

Z-Wave starts never generate new network keys, reset a controller or exclude/reinclude nodes. The start gate checks state-file/device presence and your attestation; it cannot independently prove that a remote desktop stopped or that every stored S0/S2/LR key is correct.

## Not implemented here

There is no generic Supervisor add-on repository importer, Supervisor ingress API emulation, Home Assistant OS updater, Matter Server adapter, Thread/OTBR adapter, shared audio/D-Bus broker, Frigate adapter, VS Code/File Editor adapter, NPU backend, or native A733 HAOS board image. Host network/IPv6/multicast, BlueZ, audio, extra hardware and privileged access need explicit per-app engineering.

## Adding another app

Add a reviewed catalog entry and its seed/spec implementation, then tests for filesystem ownership, persistence, architecture, budget, ports, rollback and any UI route. Keep arbitrary mounts, commands, environment values, repository URLs and Compose YAML out of the browser API. Add hardware capabilities only for that adapter. An application requiring Supervisor-specific `/data/options.json`, tokens, discovery or service APIs needs real native replacements, not fabricated compatibility flags.

Before calling a new adapter ready, pull its ARM64 image, start it on the target, test its actual UI/WebSocket path, create persistent data, update and recover it, and measure its workload alongside HA. Update the catalog's compatibility notes and hardware-validation status honestly.
