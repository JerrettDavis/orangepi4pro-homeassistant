# Live Orange Pi 4 Pro hardware baseline

Observed read-only on **September 23, 2026**. This document is intentionally
sanitized: it contains no local addresses, MAC addresses, disk identifiers,
serial numbers, usernames, credentials, or household state.

## Validation status

| Area | Tier | Evidence |
|---|---|---|
| OS, kernel, storage roles, display and touch | `orange-pi-observed` | Read-only commands over SSH on the running cyberdeck system |
| Container image architecture | `arm64-manifest-verified` | OCI indexes for all four pinned releases contain ARM64 manifests |
| Repository tests and generated configuration | `locally-tested-linux` | Full WSL/Linux validation command |
| Blank Home Assistant container on this board | `orange-pi-runtime-validated` | Pinned ARM64 image reached healthy state and survived a stop/recreate/start cycle with persistent bind storage |
| Camera stream and detection | `planned` | No V4L2 or media-controller device is currently enumerated |
| Z-Wave runtime | `planned` | No serial-by-id device or controller is currently attached |
| Image boot and recovery | `planned` | No appliance image has been built or booted from spare media |
| Production household migration | `planned` | Hyper-V remains authoritative and no controller or household state has moved |

`orange-pi-observed` means a property was read from the live system. It does
not mean an appliance service using that property has passed a runtime test.

## Platform identity

- Board device-tree model: `sun60iw2`, corresponding to the Allwinner A733
  Orange Pi 4 Pro platform used by the related repositories.
- Userspace: Orange Pi Ubuntu 22.04 Jammy, AArch64.
- Kernel: `5.15.147-sun60iw2-cyberdeck`, built with preemption and the native
  HID multitouch modules required by the panel.
- CPU: six Cortex-A55 cores and two Cortex-A76 cores; AArch64 includes ASIMD,
  AES, SHA, CRC32, atomics, half-precision, and dot-product instructions.
- Memory: 5.7 GiB physical RAM with a 2.9 GiB zram swap device. At observation
  time, approximately 5.1 GiB was available.

## Storage and boot topology

The working system is an NVMe-root installation:

| Role | Backing storage | Filesystem | Observed capacity/state |
|---|---|---|---|
| EFI | first NVMe partition | FAT32 | 512 MiB, mounted read-write |
| `/boot` | second NVMe partition | ext4 | 2 GiB, mounted read-write |
| `/` | third NVMe partition | ext4 | 50 GiB, about 35 GiB free |
| Additional roots/data/cache | other partitions on the same NVMe disk | ext4 | Valuable existing cyberdeck partitions; not appliance scratch space |
| Existing SD filesystem | one partition on a 128 GB SD card | ext4 | Mounted under `/mnt`; ownership and disposability are unproven |
| SPI/MTD | 16 MiB MTD block device | not mounted | Present; exact active bootloader provenance has not yet been proven |

Safety consequences:

- The entire NVMe disk is protected because it owns root, boot, EFI, and other
  valuable partitions. It must never be a flash destination while this system
  is running.
- The mounted SD card is not considered spare media. Its mount must not be
  changed and it must not be written until its owner and recovery role are
  explicitly established.
- The live system uses separate EFI, boot, and root filesystems. An image or
  restore procedure that assumes a single-partition vendor layout is invalid.

The kernel command line identifies the NVMe root and records the working
1024×600 display pre-initialization parameters. The active boot configuration
uses the cyberdeck kernel, matching initrd, and
`allwinner/sun60i-a733-orangepi-4-pro.dtb`. U-Boot scripts, Extlinux, GRUB
assets, and a custom boot-selector initramfs all exist under `/boot`; the
current command line reports the graphical cyberdeck selector path. The
following SHA-256 values identify the observed assets without publishing disk
identifiers:

| Asset | SHA-256 |
|---|---|
| Cyberdeck kernel image | `f419a04e65f300ec5550be37669c8a1f0145351798b0173eb0cb5fd91fec40c3` |
| Cyberdeck board DTB | `cf8a18cd595a7128fd8174f6a9d7e57f408cece977cdb887a3f060238e4fcac3` |
| Active U-Boot script | `0b413340eb45a8abf9c966813bf366817673a4346efe6de65637e5d29c042f5d` |

Before any image work, preserve a private copy of the complete boot partitions,
partition table, MTD/SPI contents where readable, and current package/service
inventory. The hashes above are identification evidence, not a recovery copy.

## Display and touchscreen

- LightDM is active and starts an XFCE Xorg session at boot.
- The active display server is Xorg on display `:0`; `/dev/fb0` and one DRM
  card are present.
- The display mode is 1024×600, consistent with the boot command line and the
  cyberdeck repositories.
- The QDtech/Specialix MPI7003 controller is attached over USB and appears as
  the `QDtech MPI7003` input device.
- `hid-multitouch`, `uhid`, and `uinput` are loaded from the cyberdeck kernel.
  Native HID touch is the active strategy.
- The older evdev/X11 calibration files are retained under a disabled
  directory. They are recovery fallbacks, not the current input path.
- Firefox is installed as an ARM64 Snap. Chromium and Openbox were not found.

The appliance kiosk must reuse LightDM/XFCE/Xorg initially. Replacing the
display manager, switching compositors, or re-enabling the legacy touch shim
is outside the first deployment and needs its own rollback test.

## Camera, graphics, and inference devices

- `v4l2-ctl` is installed, but `/dev/video*` and `/dev/media*` are absent.
- Camera/CSI/ISP nodes exist in the live device tree, but node presence in the
  DTB has not produced a usable capture endpoint.
- No camera-related kernel module was observed as an active capture driver.
- No `/dev/galcore`, `/dev/mali*`, or `/dev/npu*` node is present.
- System and reserved DMA heaps are present, and the Sunxi video engine module
  is loaded. Neither fact establishes a usable camera or NPU inference path.
- GStreamer is installed. FFmpeg and Python OpenCV are absent.

Camera work is therefore blocked on identifying the physical sensor and its
matching vendor driver/ISP path. CPU detection can be installed independently,
but it cannot be hardware-validated until a stream exists. A733 NPU support
remains optional and must not gate the appliance.

## USB and Z-Wave readiness

The touchscreen and its USB hub are the only application-relevant USB devices
observed. `/dev/serial/by-id` does not currently exist, so the production
Z-Wave controller is not attached. Z-Wave JS UI must remain disabled until the
existing controller is deliberately moved and its stable by-id path, model,
firmware, network backup, security-key inventory, and source-server version
have been recorded privately.

## Docker and host dependencies

- Docker Engine 29.6.1 and Compose 5.2.0 are installed for `linux/arm64`.
- The Docker socket is not directly accessible to the SSH account. A reviewed,
  root-owned fixed-command wrapper now permits only appliance operations; it
  does not grant Docker-group membership or general passwordless sudo.
- Home Assistant `2026.9.3` was pulled and reached healthy state on ARM64. Its
  blank onboarding endpoint was reachable locally and from the trusted LAN,
  and a container recreation completed successfully.
- Containerd and the Docker socket are enabled. Docker service startup is
  socket-managed rather than unconditionally enabled.
- Present tools include OpenSSL, Python 3, GStreamer, V4L2 utilities, `curl`,
  `jq`, and `rsync`.
- Missing deployment dependencies include `age`, `age-keygen`, FFmpeg, and
  Python OpenCV.

All pinned application images publish ARM64 manifests. This proves registry
availability, not that the images have started successfully on this board.

## Network, time, and services

- NetworkManager is active and enabled; legacy `networking.service` is also
  active. `systemd-networkd` is inactive.
- Wi-Fi owns the current default route. The appliance now uses the primary
  trusted WLAN, with the former device WLAN retained at lower autoconnect
  priority as a fallback. DHCP routing, DNS, external HTTPS, SSH, and HA LAN
  access were runtime-validated after the move. Ethernet is present but down.
- SSH is active. mDNS/Avahi is inactive.
- Chrony is enabled and the clock reported synchronized.
- One pre-existing failed unit, `dnsmasq.service`, was observed before any
  appliance change. It must be diagnosed or intentionally disabled separately;
  future deployment validation must not attribute it to Home Assistant.
- Custom enabled services include the cyberdeck boot selector and a local
  resume helper. Appliance installation must not replace or disable them.

No network settings, firewall rules, SSH configuration, or service enablement
were changed during inventory.

## Thermal snapshot

At observation time, CPU, GPU, NPU, and DDR thermal zones reported roughly
56–58 °C, while the skin zone reported roughly 36 °C. This is a single idle
snapshot, not a load qualification. Home Assistant, kiosk, camera transcoding,
and person detection must be tested together while monitoring temperature,
throttling, memory pressure, and UI latency.

## Comparison with related repositories

- `orangepi4pro-board-support` describes the same cyberdeck kernel and native
  HID multitouch strategy. The live host confirms the kernel modules are
  loaded and the legacy X11 touch configuration is disabled.
- `orangepi4pro-images` contains matching cyberdeck kernel/DTB and NVMe boot
  selector assets. That checkout also contains uncommitted rescue work, so it
  is reference material rather than a clean image-build input until reviewed.
- `orangepi4pro-cyberdeck` correctly treats board support and image construction
  as responsibilities of the related repositories. Its older discussion of
  the libusb/X11 touch workaround is now superseded on the live host by native
  HID multitouch.
- None of the related repositories proves the current physical camera path,
  active SPI bootloader contents, or a Home Assistant appliance boot.

## Next safe actions

1. Run the committed public hardware inventory on the board and verify its
   output contains no local identifiers.
2. Obtain interactive administrative elevation while keeping the current SSH
   session open; inspect Docker daemon state before installing anything.
3. Save private recovery evidence for the partition table, boot partitions,
   SPI/MTD content, enabled services, and installed package versions.
4. Install only the missing appliance dependencies after reviewing the dry run.
5. Deploy a blank Home Assistant stack beside the cyberdeck environment,
   leaving camera and Z-Wave disabled.
6. Validate HA persistence and restart behavior before enabling the kiosk.
7. Identify the camera hardware and driver path before configuring go2rtc.
8. Keep the production Z-Wave controller and Hyper-V instance untouched until
   their migration checklists and rollback artifacts are complete.

