# Install alongside the existing cyberdeck OS

This is the first deployment path. It preserves the observed kernel, DTB,
bootloader, NVMe layout, networking, SSH, LightDM, Xorg, XFCE, and touchscreen
stack. It does not install packages, replace Docker, edit boot assets, enable a
service, start a container, or alter the display session.

## 1. Inspect and plan without elevation

From a verified source package on the Orange Pi:

```bash
./bin/opiha hardware inventory
./bin/opiha host plan
./bin/opiha host install
```

`host install` is also a dry run unless `--apply` is present. Review the plan.
The first plan should create a versioned release below
`/opt/orangepi-homeassistant`, private state below `/srv/homeassistant`,
generated state below `/var/lib/orangepi-homeassistant`, one private config,
and one disabled systemd unit. It must report all mutation flags as false.

Do not proceed if the plan reports a collision. The installer refuses existing
units/configuration/releases it cannot prove it owns, populated state without
its marker, and symlinked destination ancestors.

## 2. Apply files only

Keep the current SSH session open and retain a separate administrative/recovery
path. Then run:

```bash
sudo ./bin/opiha host install --apply
sudo systemctl daemon-reload
sudo systemctl cat orangepi-homeassistant.service
sudo /opt/orangepi-homeassistant/current/bin/opiha \
  --config /etc/orangepi-homeassistant/appliance.json render
```

For ongoing automation without disclosing a sudo password, use the reviewed
one-time bootstrap instead of granting passwordless shell or Docker access:

```bash
sudo ./scripts/bootstrap-admin.sh "$(id -un)"
sudo -n /usr/local/sbin/opiha-admin daemon-reload
```

The bootstrap applies the same guarded host install, installs a root-owned
wrapper, validates a sudoers drop-in with `visudo`, and grants the invoking SSH
user passwordless access to that wrapper only. The wrapper accepts exactly one
fixed command from: `daemon-reload`, `start`, `stop`, `restart`, `status`,
`render`, `doctor`, `compose-ps`, or `journal`. It cannot run a shell, accept a
path, install packages, change networking/boot/storage, enable services, or
reboot the host. Remove `/etc/sudoers.d/orangepi-homeassistant` to revoke it.

At this point no container or appliance service has started. Confirm camera,
Z-Wave, and MQTT features are false and the rendered Compose document contains
only `homeassistant`.

The older `image/overlay.py` path is for clean image roots. Do not use it for
the first live-host deployment: its image-oriented first-boot units and kiosk
configuration are intentionally broader than this conservative installer.
Likewise, do not run `image/install-dependencies.sh --apply` on the observed
host; Docker is already working and the optional camera/backup dependencies are
not needed for blank HA.

## 3. Start blank Home Assistant deliberately

The installed unit has no `[Install]` section and cannot silently enable itself.
Start it only after inspecting the generated configuration:

```bash
sudo systemctl start orangepi-homeassistant.service
sudo systemctl status orangepi-homeassistant.service --no-pager
sudo docker compose \
  --env-file /var/lib/orangepi-homeassistant/empty.env \
  --project-directory /var/lib/orangepi-homeassistant \
  -p opiha -f /var/lib/orangepi-homeassistant/compose.json ps
curl --fail --show-error --head http://127.0.0.1:8123/
```

Open `http://ORANGE_PI_HOST:8123` only from the trusted LAN. This is blank
onboarding state, not the production household restore. The production VM and
Z-Wave server remain authoritative.

Validate persistence by recording a harmless onboarding/config marker, stopping
and recreating the container through the appliance CLI, and confirming the
marker remains. Validate restart behavior before choosing to add a separate
boot-time enablement unit in a later reviewed change.

## Deferred on this host

- Kiosk integration must reuse the active LightDM/XFCE/Xorg session; no Openbox
  autologin change is authorized.
- Camera/go2rtc/vision remain disabled until a real V4L2/media device exists.
- Z-Wave remains disabled until the existing controller is deliberately moved,
  backed up, and identified by `/dev/serial/by-id`.
- `age`, FFmpeg, and OpenCV installation is deferred to the backup/camera slices.
- No SD, NVMe, eMMC, or SPI write is part of host installation.

See [rollback](ROLLBACK.md) before applying and the [live baseline](LIVE-HARDWARE-BASELINE.md)
for the protected devices and current validation status.

## HTTPS proxy and time synchronization

The optional `proxy` feature runs the pinned, multi-architecture Nginx Proxy
Manager image with host networking. Its database, generated configuration,
ACME account, and certificates live under `/srv/homeassistant/proxy`; none are
part of the public release. Enable it only after restoring that private state
and configuring Home Assistant to trust the loopback proxy. The feature binds
ports 80, 81, and 443 and therefore requires those host ports to be free.

The live Orange Pi uses Chrony. On 2026-09-24 it reported stratum 3, normal leap
status, and approximately 1 ms system offset; the domain controller comparison
was within 40 ms. The board does not expose a usable RTC, so network time must
be healthy after boot. Check it without changing providers:

```bash
chronyc tracking
chronyc sources -v
date --iso-8601=ns
```
