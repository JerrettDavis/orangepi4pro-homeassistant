# Repository Validation and Live Hardware Baseline Design

## Purpose

Turn the exported `0.1.0-alpha.1` source tree into a trustworthy, versioned foundation for a non-destructive Orange Pi deployment. This slice proves what the repository actually implements, records the current cyberdeck host without exposing private site data, and adds reusable diagnostics needed to reject unsafe deployment assumptions.

This slice does not install the appliance, change the live host, attach or configure the production Z-Wave controller, enable a camera that is not presently enumerated, build a release image, or flash any storage device.

## Confirmed starting state

- The source arrived without Git metadata and has no existing GitHub repository. A local `main` history was initialized and the unmodified alpha source was committed as the baseline.
- The supported Linux/WSL test run has 85 runnable passing tests and two skips: the real `age` roundtrip and the OpenCV HOG smoke test lack their optional dependencies in WSL.
- Native Windows produces four failures caused by POSIX permission and path semantics. Windows is not the documented appliance validation platform.
- All actual shell scripts pass `bash -n`.
- All four pinned images publish ARM64 manifests:
  - Home Assistant `2026.9.3`
  - Z-Wave JS UI `11.24.1`
  - Eclipse Mosquitto `2.0.22`
  - go2rtc `1.9.14`
- The live host runs Ubuntu 22.04 on AArch64 with `5.15.147-sun60iw2-cyberdeck`.
- The mounted root, boot, and EFI filesystems are `/dev/nvme0n1p3`, `/dev/nvme0n1p2`, and `/dev/nvme0n1p1`. The NVMe also contains other valuable partitions.
- A 128 GB SD filesystem is mounted at `/mnt/opisd-check`. Its purpose and disposability are not established, so it is not a flash target.
- LightDM, Xorg, XFCE, native HID multitouch, and the QDtech MPI7003 panel are active. Disabled Xorg fallback configurations remain available.
- Docker Engine 29.6.1 and Compose 5.2.0 are installed for ARM64. The SSH user cannot access the Docker socket and does not have passwordless sudo.
- No `/dev/video*`, `/dev/media*`, `/dev/serial/by-id`, Z-Wave controller, or GPU/NPU inference device is currently present.
- The host lacks `age`, FFmpeg, and Python OpenCV. GStreamer and V4L2 utilities are installed.
- `dnsmasq.service` is failed before appliance installation and must not be attributed to this project.

## Design principles

### Evidence before mutation

Diagnostics collect facts without installing packages, changing service state, mounting or unmounting media, reading secrets, or requiring Docker access. Commands report `unknown` or `unavailable` when permissions or tools are missing rather than manufacturing success.

### Sanitized by construction

The committed baseline records stable technical properties but excludes:

- IP and MAC addresses
- Wi-Fi SSIDs and credentials
- SSH keys and authorized-key material
- local usernames other than generic documented service accounts
- disk UUIDs, partition UUIDs, serial numbers, and host-specific identifiers
- browser profiles and authentication state
- Z-Wave keys, Home IDs, controller backups, and household state
- full package or environment dumps that may reveal site-specific data

Runtime inventory output supports a sanitized mode for documentation and a private full mode stored outside Git. The public scanner must reject common credential shapes and known private artifact names.

### Explicit validation tiers

Every feature claim uses one of these states:

1. `implemented`
2. `locally-tested-linux`
3. `arm64-manifest-verified`
4. `orange-pi-observed`
5. `orange-pi-runtime-validated`
6. `production-validated`
7. `planned`

Documentation must not collapse manifest availability, source-level tests, or observed device nodes into hardware validation.

## Repository hardening

### Validation entry point

Provide one documented command that runs the source scanner, Python compilation, Python tests, shell syntax checks, configuration/render validation, source-package determinism checks, and optional Docker smoke tests. Hardware tests remain separate and require an explicit host target.

The validation result reports each check as pass, fail, or skip with its reason. Optional-tool absence is a skip only when the associated capability is not being claimed as validated.

### Platform contract

Linux is authoritative for appliance behavior. WSL2 is supported for source validation when the repository is stored on a Linux filesystem; `/mnt/*` operation may be used for diagnostics but is not considered the reproducible reference environment. Native Windows wrappers may run portable CLI functions, but POSIX mode and shell-image tests are explicitly excluded or translated rather than reported as product failures.

### Honest version and architecture checks

Pinned references remain explicit release tags and may be locked to registry digests in private runtime configuration. Validation must confirm that every configured image has a `linux/arm64` manifest without pulling or running it. A missing tag, registry error, or missing ARM64 manifest fails the architecture check.

### Documentation reconciliation

Existing claims in `README.md`, `reports/VALIDATION.md`, and the runbooks are reconciled with current evidence. Unsupported claims are downgraded, and the absent camera plus missing host dependencies are recorded as deployment prerequisites rather than silently assumed.

## Hardware inventory interface

Add or extend the CLI so the reusable interface is:

```text
opiha hardware inventory [--output PATH] [--private]
opiha hardware camera
opiha hardware zwave
opiha hardware storage
```

The default output is safe for public documentation. `--private` may include local addressing and identifiers but requires an explicit output path outside the repository and creates the file with mode `0600` on POSIX systems.

### Inventory fields

The sanitized inventory records:

- OS family/version and CPU architecture
- kernel release and device-tree model
- root/boot/EFI device classes and partition roles without UUIDs or serials
- filesystem types, sizes, free space, and mount roles
- boot mechanism, kernel/DTB filenames, and hashes of critical boot assets
- Docker/Compose client and server availability separately
- display manager, display server, desktop session, DRM/framebuffer presence, and resolution where observable
- input device names and the stable touch strategy
- camera/media device presence and V4L2 capability summaries
- serial-by-id presence without exposing an attached production controller unless private mode is used
- network manager, link classes, default-route interface class, mDNS, SSH, and time synchronization state without addresses
- failed and appliance-relevant services
- thermal zones, memory, CPU topology, and free storage
- availability of `age`, OpenSSL, FFmpeg, GStreamer, OpenCV, V4L2 utilities, Docker, Compose, `jq`, and `rsync`

### Storage safety model

Storage inventory resolves parent disks for `/`, `/boot`, and `/boot/efi`. Any later flash workflow consumes this model and rejects:

- the current root partition or its parent disk
- the current boot or EFI partition or their parent disk
- mounted destinations
- non-block devices
- ambiguous device ancestry
- devices whose size/model cannot be displayed

This slice tests the parsing and rejection model but does not implement or invoke real image writes.

## Live baseline document

Create `docs/LIVE-HARDWARE-BASELINE.md` with:

- observation date and validation tier
- sanitized storage and boot topology
- kernel, DTB, bootloader, and boot-selector provenance
- display/touch stack and fallback configuration
- camera, serial, GPU, and NPU device status
- Docker and host dependency readiness
- networking/service summaries without local addressing
- resource and thermal snapshot
- meaningful differences from `orangepi4pro-images`, `orangepi4pro-board-support`, and `orangepi4pro-cyberdeck`
- exact unvalidated assumptions and the next safe host actions

The document identifies the custom cyberdeck kernel and boot assets as the authoritative baseline. It explicitly forbids whole-disk writes to the running NVMe and declines to classify the mounted SD card as spare media.

## Tests

Automated tests cover:

- sanitization of IP, MAC, UUID, serial, hostname, username, and credential-shaped fields
- parsing representative `lsblk`, `findmnt`, input, V4L2, and service output
- missing commands and permission-denied behavior
- root/boot/EFI parent-disk resolution
- rejection of current root and boot disks
- mounted-device rejection
- ARM64 manifest-list parsing, including attestations with `unknown/unknown`
- validation status aggregation and honest skip reasons
- public/private inventory file permissions and repository-path refusal for private output

Fixtures use synthetic identifiers only. Hardware-facing tests are marked separately and never make ordinary CI claim physical validation.

## Acceptance criteria

This slice is complete when:

1. The source tree has reviewable Git history with no private state staged.
2. The full supported Linux validation command passes.
3. Optional `age` and OpenCV tests either run successfully in a disposable environment or remain explicitly reported as unvalidated prerequisites.
4. All pinned image references are verified to publish ARM64 manifests.
5. The hardware inventory commands are non-destructive and covered by fixture-based tests.
6. A fresh sanitized inventory from the Orange Pi contains no forbidden local identifiers.
7. `docs/LIVE-HARDWARE-BASELINE.md` matches observed live state and related repository evidence.
8. Documentation clearly distinguishes implemented, locally tested, ARM64-manifest verified, live-observed, and still-unvalidated capabilities.
9. No Orange Pi packages, services, networking, Docker state, boot assets, mounts, or storage contents were changed while completing this slice.

## Subsequent slices

After this slice passes review, the next specs cover, in order:

1. non-destructive host installation and blank Home Assistant startup
2. kiosk integration with the existing LightDM/XFCE/Xorg session
3. camera enumeration/bring-up and CPU presence detection
4. Z-Wave JS UI staging and production migration checklist
5. encrypted appliance backup, restore, and interrupted-recovery validation on ARM64
6. cyberdeck-derived image build and guarded spare-media flash rehearsal
7. Hyper-V Home Assistant migration rehearsal and deliberate production cutover

