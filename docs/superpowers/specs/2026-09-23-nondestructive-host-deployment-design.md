# Non-destructive host deployment design

## Goal

Install and start a blank Home Assistant Container on the existing Orange Pi
cyberdeck OS without changing its kernel, boot assets, partition layout,
network configuration, display manager, desktop session, or currently mounted
media. The deployment must be reviewable before elevation and leave a direct
rollback path.

## Live constraints

- The running NVMe root/boot/EFI chain is authoritative and protected.
- LightDM, Xorg, and XFCE already provide the working 1024x600 touch session.
- Docker Engine and Compose are installed, but the SSH account cannot access
  the daemon and does not have passwordless sudo.
- The host lacks `age`, FFmpeg, and Python OpenCV. None is required for the
  first blank-HA milestone.
- No camera or stable serial device is present, so camera and Z-Wave services
  remain disabled.
- A mounted SD card has unknown ownership and is not deployment storage.

## Approach

Use a two-stage host installer exposed through the `opiha host` CLI:

1. `opiha host plan` performs read-only prerequisite and collision checks and
   emits an explicit change manifest.
2. `sudo opiha host install --apply` copies only public repository runtime
   assets, creates private runtime directories, writes a fresh appliance
   configuration, installs systemd units, and records a deployment manifest.

The first install is deliberately headless. It does not install packages,
replace Docker, create a kiosk account, edit LightDM, enable camera/Z-Wave/MQTT,
or enable/start systemd units. Service enablement and startup are separate
commands after the operator has reviewed the installed state.

The existing alpha overlay remains useful for clean image roots but is not the
live-host installer: it currently copies image-oriented units and, with kiosk
enabled, replaces the working XFCE session with Openbox autologin. The live
installer must not do that.

## Filesystem contract

- Public runtime code: `/opt/orangepi-homeassistant/current`
- Private service state: `/srv/homeassistant/{config,zwave-js,mosquitto,camera,backups,recovery,private,media,share,ssl}`
- Generated state and manifests: `/var/lib/orangepi-homeassistant`
- Host configuration: `/etc/orangepi-homeassistant/appliance.json`
- Units: `/etc/systemd/system/orangepi-homeassistant*.service`

The runtime code directory is installed as a versioned release and selected by
an atomic `current` symlink. A failed upgrade can switch the symlink back. The
installer never deletes old releases or previous state.

## Safety and idempotence

- Refuse non-Linux hosts, non-root apply, symlinked destination ancestors,
  populated state not bearing the appliance marker, and path escapes.
- Refuse to manage or overwrite a unit/file not recorded by this installer.
- Never invoke package managers, disk utilities, mount tools, network tools,
  Docker, or systemctl from `host install`.
- Copy through a staging directory, verify the public source scan and file
  hashes, then rename into place.
- Use mode `0700` for private configuration/state roots and `0644` only for
  public units and manifests.
- Record source commit/version, installed paths, hashes, and pre-existing-file
  decisions without host identifiers or credentials.
- `host plan` and `host install --dry-run` make no changes and are usable over
  the existing unprivileged SSH session.

## Service model

The initial unit starts only Home Assistant through the existing Docker daemon.
It uses the pinned image, host networking, persistent `/config`, bounded logs,
`no-new-privileges`, and `unless-stopped`. The CLI production gate continues to
allow only explicit blank onboarding until a deliberate activation/cutover.

Z-Wave JS UI, MQTT, camera, vision, backup scheduling, and kiosk are installed
only as disabled definitions or added in later slices. This prevents absent
hardware and untested browser/session assumptions from breaking the first HA
startup.

## Rollback

Before service startup, rollback is simply removal of installer-owned public
files and restoration of any recorded previous symlink; private state is kept.
After startup, stop/disable the appliance unit, restore the previous release
selection, and retain `/srv/homeassistant` for inspection. The installer never
touches the cyberdeck services, Docker packages, display stack, SSH, networking,
boot files, or storage layout, so those do not require rollback.

## Validation

Automated tests cover dry-run purity, destination guards, collision refusal,
idempotent reinstall, staged release hashing, config/path generation, unit
content, and preservation of pre-existing private state. A disposable-root
integration test exercises apply without root or systemd by targeting a
synthetic Linux root.

On the Orange Pi, validation proceeds in this order:

1. run `host plan` unprivileged;
2. transfer a deterministic public source package to `/tmp`;
3. run the public scanner and verify its checksum;
4. apply the host install with interactive elevation while retaining SSH;
5. inspect installed files and generated configuration;
6. start blank HA only;
7. verify HTTP health, persistence across container recreation, restart policy,
   log sanity, and service recovery after a deliberate reboot.

No boot-media write or production Home Assistant/Z-Wave cutover is part of this
slice.
