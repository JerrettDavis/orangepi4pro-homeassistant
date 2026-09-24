# Display, camera, presence and HACS

## Hardware responsibility

This is the **Orange Pi 4 Pro A733**, not the older RK3399 Orange Pi 4 and not a Rockchip RK3588 board. The existing board-support repository remains authoritative for kernel/device-tree/touch/boot details. The appliance neither swaps your kernel nor assumes a Rockchip accelerator API works on Allwinner.

The September 23 live inventory confirms the custom cyberdeck kernel,
LightDM/Xorg/XFCE, and native QDtech HID touch are active. It also confirms
there is currently no V4L2/media device and no GPU/NPU inference node. Treat
the [live baseline](LIVE-HARDWARE-BASELINE.md) as the current hardware truth;
the Openbox kiosk target below must be reconciled with the working XFCE session
before installation.

## Kiosk

The current implementation targets LightDM + Openbox + X11 and an installed Chromium/Chromium-browser or Firefox. The kiosk runs as an unprivileged locked local user. It starts at the local read-only status page and forwards to a local HA dashboard when the HTTP service responds. The browser's sandbox is not disabled.

Login once using a dedicated non-admin HA user. A persistent private browser profile supports subsequent restarts and is backed up, but vendor browser/keyring changes or revoked sessions may require reauthentication. No admin password, tokenized URL or default HA account is baked into the image.

X11 DPMS defaults to screen-off after ten minutes. Fresh person presence issues an X11 display-wake command. Touch input naturally wakes supported displays. DPMS and brightness behavior depend on your panel/driver; this alpha does not implement panel-specific backlight registers, a fade animation, or a Wayland compositor integration.

On a restored household, `dashboard_path` should point at an existing dashboard, usually `/lovelace`. The repository's `/dashboard-orangepi` dashboard only exists in fresh seeded config unless you explicitly add it to the restored config. The code never silently replaces your restored YAML to insert appliance cards.

## Camera bring-up

A working V4L2 capture device is required. The existence of `/dev/video0` alone is insufficient: it may be a codec/ISP node rather than a capture endpoint. A vendor CSI camera may need additional ISP/media-controller setup from your BSP.

```bash
v4l2-ctl --list-devices
v4l2-ctl --device=/dev/video0 --list-formats-ext
# Test a supported mode; don't assume every camera supports this example.
ffmpeg -f v4l2 -input_format mjpeg -video_size 640x480 -framerate 5 \
  -i /dev/video0 -frames:v 1 /private/camera-test.jpg
```

That test creates an actual private image, so keep it out of Git and public bug reports. No recording or photo capture occurs by default in the appliance runtime.

Configure the real device, then inspect the generated private `/srv/opiha/camera/go2rtc.yaml`. Despite its suffix it may contain JSON, which is valid YAML. Default capture is MJPEG 640x480 at 5 FPS, converted to H.264 by go2rtc's ffmpeg integration. Change the private camera configuration to match an actually supported mode; an existing config is not overwritten on restart. One go2rtc process owns the device, while the detector reads its local RTSP stream.

The API and RTSP ports are loopback-only. WebRTC is disabled by default. Use an SSH tunnel for stream debugging rather than exposing a config API capable of launching ffmpeg/exec commands. HA on the same host can consume `rtsp://127.0.0.1:8554/local` through a compatible camera integration. No remote-browser direct-camera exposure or LAN ACL design is automated here.

## Implemented detector, and its limits

`src/opiha/vision.py` is an executable OpenCV HOG/SVM person detector using the built-in pedestrian model. It processes at low frequency, requires consecutive hits, holds presence for a configurable duration, reconnects on stream errors, and marks stale/failed capture unavailable. It stores detection metadata, not frames or face identities.

This model is intentionally a minimal dependency baseline. It can miss seated/close-up/partially occluded people and can produce false positives. A blank-frame inference test only verifies that the backend executes; it is not an accuracy or A733 performance benchmark. Use this release for dashboard waking, not unlocking doors, safety alarms, identifying family members or reliably determining room occupancy.

The detector is constrained by systemd CPU/memory limits. go2rtc has separate limits. Monitor actual CPU temperature, throttling, dropped frames and HA response time before relying on simultaneous kiosk/camera workloads.

### Adding appliance sensors to a restored household

Fresh seed config already includes generic REST/template entities and a dashboard. To add them to a restored config, review/copy `homeassistant/packages/opiha.yaml` and merge an appropriate `homeassistant: packages:` include into your existing YAML rather than adding a duplicate top-level key. Include the optional dashboard only after reviewing your current Lovelace setup. This is an intentional first-migration review step; subsequent backups preserve the result.

The package reads the local diagnostic endpoint. If camera is disabled or stale, the presence entity is unavailable, not a fabricated "clear" state.

## NPU work is deliberately separate

`doctor` reports the presence of `/dev/galcore` but explicitly reports `npu_backend_implemented: false`. This repo does not include a working A733 NPU runtime, converted model, RKNN plugin or a Frigate acceleration claim.

The next backend should preserve the detector's status schema and test contract. Before implementing it, identify the actual BSP kernel driver and matching userspace SDK, licensing/redistribution rights, model conversion toolchain and supported operators, then compare an actual camera corpus for correctness and thermal performance. Keep HA operable with the accelerator disabled. Person detection and "3 TOPS" marketing do not establish supported model throughput.

## HACS and other custom code

An existing HA config import preserves HACS code/state, frontend resources, custom integrations and credentials. For a fresh image, `vendor-hacs --version ...` seeds explicitly fetched HACS software, not authenticated HACS state. A fresh GitHub device authorization remains a user action. No undocumented HACS bulk-install API is fabricated.

This alpha does not include a generic HACS repository desired-state synchronizer; your full restored config is the authoritative initial migration path. Inventory records custom component versions for comparison. Follow upstream license and version compatibility requirements for every integration/card you choose to vendor later.

## Other hardware-bound integrations

This alpha does not pass host D-Bus/Bluetooth adapters into HA or add multicast/USB permissions for every possible integration. Existing Bluetooth, Zigbee, Thread/Matter, serial or other host-bound integrations require an inventory-driven host/container mapping and their own acceptance tests. Preserve those services on their current host during the first cutover when appropriate. A full config copy preserves entries, not hardware access.

For an ARM64 kernel with pages larger than 4 KiB, check `getconf PAGESIZE` and HA logs for jemalloc compatibility. HA documents `DISABLE_JEMALLOC` as an opt-out for affected platforms; no page size or allocator compatibility has been inferred for your board here. Add the environment override to the generator deliberately if your actual baseline needs it.
