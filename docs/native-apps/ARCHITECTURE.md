# Native architecture and boundaries

Home Assistant remains an ordinary supported Container installation. The additional manager and custom integration are independent community software, not an officially supported Supervisor installation. Native app processes run in Docker containers on the existing A733 kernel. No KVM, QEMU, guest OS, nested Docker or OS replacement is involved.

The in-HA panel uses `hass.callWS` with one registered command, `opiha_apps/request`. Every request checks that the current HA user is active and an administrator. The backend communicates with a bearer-authenticated, loopback-only Python host service. Browsers never receive that credential. The host service accepts only catalog app IDs, six lifecycle actions, and typed version/memory/CPU/port/radio options.

The host manager invokes `/usr/bin/docker` using an argument list and an explicitly selected local Unix socket. It ignores the caller's Docker context, `DOCKER_HOST`, shell expansion and arbitrary Compose data. Container IDs and ownership labels are verified before mutations. The manager does not have lifecycle operations for Home Assistant, the original Compose project, the kiosk or the reverse proxy.

## Plan and execution

Planning does not pull or start an image. A plan expires after five minutes, is single-use, and records the current container ID, running state and state-record revision. Approval enqueues a single-worker job. The worker repeats preflight and rejects changed state. A filesystem lock coordinates the daemon with local backup and repair operations.

Installation pulls the requested native architecture, checks the image metadata, locks to its registry digest, prepares private data, and creates a stopped container with restart disabled. An explicit Start applies the selected autostart policy. A stopped installation cannot unexpectedly claim a radio after the next host reboot merely because its UI checkbox was set.

An update pulls first, disables restart for the old app, stops it, and copies its data to a private rollback directory. It then replaces only that owned container. A journal records progress. Failed replacement attempts restore the prior image/options and the matching data. An interrupted transaction blocks ordinary operations until local repair. The process/runnable check is not a full application acceptance test; successful Node-RED deployment, firmware compilation, camera streaming and radio operation still need functional checks.

Removal removes the owned container but retains its data and record. Reinstalling the same saved settings uses the recorded digest rather than silently following a mutable tag. Old rollbacks are not automatically pruned.

## Embedded UIs

Node-RED, ESPHome and go2rtc have fixed, reviewed routing adapters. The HA backend issues a short-lived, HttpOnly, same-site cookie tied to an active administrator refresh token. Requests and live WebSockets recheck authorization. The panel renews its active session while visible.

Only selected headers and scoped backend cookies are forwarded. HA Authorization headers, HA cookies, the host-management token, arbitrary URLs and cross-origin redirects are not forwarded. ESPHome's adapter strips the mount prefix and supplies `X-Ingress-Path`/`X-Forwarded-Prefix`; Node-RED and go2rtc are configured to serve their own prefix. This is not a general HTML rewriting engine.

UI requests are proxied through HA; CPU-heavy application work, MQTT traffic and media processing do not run through the manager's Python API. Its UI proxy still has real overhead, particularly for video/file transfers, and must be measured for your workload.

## What remains external

HA Core lifecycle, HA's native backup flow, OS/kernel updates, your current image builder, networking, current Z-Wave/MQTT/proxy services and camera/NPU drivers stay where they are. This is intentionally not an attempt to reimplement every Supervisor API.
