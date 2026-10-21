# Native Apps 0.2.0-alpha.2: on-device acceptance (Orange Pi 4 Pro, ARM64)

Observed 2026-10-21 on the live appliance (HA 2026.9.3 Container, Docker 29.6, kernel 5.15.147-sun60iw2-cyberdeck). No hostnames, addresses, credentials or household data are recorded here.

## Real vs mocked

| Area | Result | Evidence type |
|---|---|---|
| Unit/integration suite | 274 passed, 3 skipped (WSL Ubuntu 24.04, Python 3.12); 267 passed on the board inside the HA image (Python 3.14) | real execution; Docker is faked in unit tests |
| Catalog images | All five releases verified linux/arm64 and pinned by multi-arch index digest | real registry queries from the board |
| Host install | `install-host` preview then `--apply`; HA `check_config` exit 0; one HA restart through `opiha-admin`; entity registry, config entries, devices and automations unchanged | real |
| HA authorization (real HA 2026.9.3, disposable instance) | admin WebSocket allowed; regular user denied; session endpoint denied to unauthenticated/regular/unknown-app; cross-origin write refused; arbitrary image option and unknown operation rejected | real HA, `scripts/native-apps/ha-lab-acceptance.py` |
| Panel over HTTPS | Loaded as the logged-in owner through the existing HTTPS route | real browser |
| Node-RED | Installed and started from the panel; editor opened inside HA (HTTP + WebSocket); flow deployed; container removed and recreated (new container ID); flow persisted | real |
| ESPHome | Installed and started; ESP-IDF toolchain downloaded; ESP32 firmware compiled with one ninja job | real (CLI; same manager) |
| Encrypted restore rehearsal | age + Ed25519 backup/restore of disposable data; content identical; tampered archive rejected with nothing staged | real age/openssl |
| Not exercised | Z-Wave, camera/go2rtc, Mosquitto start; physical touch on the kiosk panel; non-admin HA user through the production panel; image build/flash | not tested |

## Defects found on the device and fixed

1. The ingress allowlist dropped `Node-RED-API-Version`, so the editor failed with "Error adding flows" (fixed in alpha.2, regression test added).
2. Re-installing an app immediately after removal failed because the loopback port was briefly still bound (bounded retry, test added).

## Performance (60 s idle samples unless noted)

| Condition | CPU busy avg | HA response median / p95 | Min available RAM | Swap used | Peak temp |
|---|---|---|---|---|---|
| Before | 5.5 % | 4.5 / 21.7 ms | 3756 MiB | 970 MiB | 49.8 C |
| Manager + Node-RED idle | 7.8 % | 4.5 / 9.7 ms | 3497 MiB | 838 MiB | 50.6 C |
| Node-RED + ESPHome idle | 6.2 % | 4.5 / 12.0 ms | 3564 MiB | 870 MiB | 51.8 C |
| ESP32 compile (240 s) | 18.5 % (max 67 %) | 5.2 / 14.5 ms | 3336 MiB | 870 MiB | 63.4 C |

The manager service used about 12 MB; Node-RED about 60 MB; ESPHome about 535 MB idle and 608 MB while compiling (ceiling 1536 MiB). HA latency is the unauthenticated HTTP response time, not automation latency.
