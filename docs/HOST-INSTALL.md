# Install on an existing Orange Pi image

Start with the known-good A733 kernel/boot/NVMe/display baseline from your own repositories. Do not test a new kernel during household cutover. This installer supports Ubuntu/Debian userspace, but it cannot establish that a particular vendor release has all required repositories and packages.

## Inspect first

```bash
uname -a
cat /etc/os-release
lsblk -f
ls -l /dev/serial/by-id/ /dev/video* 2>/dev/null || true
./bin/opiha hardware inventory
python3 image/overlay.py --target-root / --live
./image/install-dependencies.sh
```

The first overlay command and dependency command are dry runs. Neither flashes a device. Applying the overlay enables its systemd unit links for subsequent boot, but does not immediately start them.

On the observed cyberdeck host, `age`, FFmpeg, and Python OpenCV are missing;
camera and Z-Wave device paths are absent; and Docker daemon inspection
requires interactive elevation. Keep the current SSH session open, review the
dependency dry run, and capture private recovery evidence before applying it.

## Explicit installation

Review the scripts before running them as root. Keep another working administrative session and a recovery route. The dependency script adds Docker's official apt repository. It does not silently remove conflicting Docker packages or upgrade the kernel.

```bash
sudo ./image/install-dependencies.sh --apply
sudo python3 image/overlay.py --target-root / --live --apply --enable-kiosk
sudo systemctl daemon-reload
sudo systemctl start opiha-firstboot.service

sudo opiha configure --ha-version YOUR_SOURCE_RELEASE --timezone America/Chicago
sudo systemctl start opiha-status.service
sudo opiha doctor
```

Omit `--enable-kiosk` for a headless first test. Kiosk mode uses LightDM/Openbox with a locked local `opiha-kiosk` account. It needs a working X11 graphics/touch stack. The installer includes Debian Chromium when available. On Ubuntu, it **does not claim to configure a working browser Snap inside an offline chroot**: supply and test Chromium or Firefox in the base image first.

First boot creates the service users and private data directories, generates unique host SSH keys, checks for optional signed recovery media, and publishes a sanitized runtime config. Public image defaults never contain household configuration or private keys.

## Choose onboarding or import

For a fresh HA UI:

```bash
sudo opiha up --onboarding
# http://ORANGE_PI_HOST:8123 on the trusted LAN
```

After onboarding/restore, explicitly activate the appliance so future service starts are permitted:

```bash
# Only after the original HA instance and conflicting service endpoints are stopped.
sudo opiha activate --confirm-cutover
sudo systemctl restart opiha-stack.service
```

For a stopped raw import, follow [migration](MIGRATION.md); do not start a connected restored copy while production is running. The presence of an imported/restored state marker blocks the onboarding bypass.

The default HA endpoint is plain HTTP on loopback for the kiosk and health checks; production HA itself uses host networking. If your imported YAML enables native HTTPS, restore `/ssl` too and explicitly configure a correct local URL/trusted certificate arrangement. The tools do not disable certificate verification. A certificate without a loopback SAN may require a reviewed reverse-proxy or local-name setup beyond this alpha's loopback health URL constraint. Do not remove household TLS settings automatically merely to make a health check green.

## Optional features

```bash
sudo opiha configure --zwave-device '/dev/serial/by-id/YOUR_REAL_ID' --enable zwave
sudo opiha configure --camera-device /dev/video0 --enable camera
sudo opiha mqtt-init --username opiha
sudo opiha configure --enable mqtt
sudo systemctl restart opiha-stack.service
sudo systemctl restart opiha-vision.service
```

Use only features you actually need. `mqtt-init` creates a private account/password file, using `mosquitto_passwd` natively or from the selected broker container. It does not install/start an extra host broker. The broker's port is loopback-only, so this is not automatically a LAN MQTT replacement. Existing LAN clients need a deliberate bind/firewall/auth policy or should continue using their current broker during phase one.

Restarting the stack republishes runtime settings for diagnostics/vision. The vision unit skips startup when camera is disabled. A new camera feature enabled on an already-booted host needs an explicit vision restart, as above.

## Start the kiosk

```bash
sudo systemctl start lightdm.service
sudo systemctl start opiha-kiosk.service
```

Confirm that the actual default boot target starts the display manager. The overlay does not change the host's default target globally. On a dedicated appliance, after testing the desktop, you can choose `sudo systemctl set-default graphical.target`. On an existing cyberdeck, review its current display-manager setup instead of replacing it blindly.

Create a dedicated non-admin HA user and log into the kiosk once. Its browser profile is private persisted state and is included in appliance backups. No long-lived access token is embedded in a dashboard URL. Browser encryption/keyring state is platform-dependent, so restoring a profile does not guarantee its session survives; reauthentication may occasionally be necessary.

## Logs and operations

```bash
sudo journalctl -u opiha-firstboot -u opiha-stack -u opiha-status --since today
sudo journalctl -u opiha-kiosk -u opiha-vision --since today
sudo opiha render
sudo opiha down
```

Docker logs can contain integration credentials or household details. Review/redact before posting. Do not expose diagnostics/admin ports or the Docker socket to the Internet. Configure remote HA access using your chosen supported method separately.

Do not enable the scheduled backup timer until you have configured a real off-box destination and tested a restore. See [recovery](RECOVERY.md).
