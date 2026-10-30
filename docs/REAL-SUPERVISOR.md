# Running the real Home Assistant Supervisor on the Orange Pi

Production Home Assistant on this appliance now runs under the actual Supervisor (2026.10.5), not under the compose
stack. The Supervisor is unsupported on third-party Linux; this is a "supervised"-style install and the Supervisor reports
`healthy: true, supported: false` (reason: unsupported host OS).
Apps (add-ons), the store, backups, discovery and ingress are the
real ones.

## How it is wired

* The Supervisor runs as the `hassio_supervisor` container, started by systemd, with Docker, D-Bus, udev and
  `/usr/share/hassio` mounted. It creates the `hassio` network (172.30.32.0/23), its plugins (DNS, CLI, audio, multicast,
  observer) and the `homeassistant` container.
* Home Assistant's real config directory (`/srv/homeassistant/ha`, 2026.9.3) is **bind-mounted in place** at
  `/usr/share/hassio/homeassistant` (and the share, media and ssl folders), not copied. `/etc/fstab` carries the mounts.
* `/usr/share/hassio/homeassistant.json` pins Home Assistant to the version on disk. Without that pin the Supervisor
  installs the newest core and would migrate the database. Update the core deliberately, with a backup.
* `/run/supervisor` must exist (`/etc/tmpfiles.d/supervisor.conf`).
* `orangepi-homeassistant.service` is disabled and stopped. Its older drop-in (`supervisor.conf`) started the standalone
  HTTPS proxy; Supervisor now starts both Core and the proxy app. The old `opiha-proxy-1` container is stopped with
  Docker restart policy `no` and retained for rollback.
* `/etc/orangepi-apps/real-supervisor` makes this repository's add-on manager stand down (no shim, no iptables redirects,
  no installs), because both would want 172.30.32.2. The host panel (Overview, Host, Docker, Updates, Terminal) is unchanged;
  use Home Assistant's own Apps page for add-ons.

* Host logs: `systemd-journal-remote` (Ubuntu package) provides `systemd-journal-gatewayd`; its socket listens on
  `/run/systemd-journal-gatewayd.sock` (drop-in `10-supervisor.conf`) and is mounted into `hassio_supervisor`.
  That clears the Supervisor's `systemd_journal` unsupported reason.
* OS Agent: the official `os-agent` 1.14.0 `.deb` (home-assistant/os-agent, arm64) provides the `io.hass.os` D-Bus
  service. The Supervisor then lists `os_agent`, `journal`, `resolved`, `timedate` and `disk` host features.
* Docker: `/etc/docker/daemon.json` sets `"log-driver": "journald"` (the Supervisor requires it; applies to containers
  created afterwards). `hassio_supervisor` has restart policy `no` and is started by `hassio-supervisor.service`
  through the official supervised-installer launcher at `/usr/local/sbin/hassio-supervisor`, configured by
  `/etc/hassio.json`. The `20-official-launcher.conf` service drop-in selects this launcher. It recreates the container
  when Supervisor updates its `latest` image tag. A bare `docker start -a` restarts the old container and caused the
  October 26 update rollback; do not restore that command.
* NetworkManager: `/etc/NetworkManager/conf.d/20-connectivity.conf` enables the connectivity check.
* Unsupported reason left: `os` (the Orange Pi Ubuntu-based OS is unsupported). The standalone proxy's `software`
  warning was resolved by migrating it to the community app. AppArmor is now enabled as described below.
* Supervisor backups use `/usr/share/hassio/backup`, bind-mounted from the existing
  `/srv/cyberdeck-home/opiha/ha-backups` directory in `/etc/fstab`. This makes the pre-Supervisor backups visible and
  keeps new archives on the larger HOME partition instead of filling the root partition.
  A full post-repair backup completed on October 29 (slug `e4113790`), including Core, both installed apps, shared
  folders and Supervisor configuration. Host systemd units, fstab and the proxy's separate configuration still require
  host-level backup; a Supervisor archive does not replace that.
* Sysstat history lives at `/srv/cyberdeck-home/sysstat` (`SA_DIR` in `/etc/sysstat/sysstat`). Keeping its monthly
  files in the 50 MB RAM log partition filled `/var/log` and prevented useful journal history from being retained.
  The unused standalone `dnsmasq.service` is disabled; host DNS uses NetworkManager's configured resolvers and
  Supervisor manages its own CoreDNS container.
* The dormant camera build tree was checksum-verified and relocated to `/opt/cyberdeck-tools/ov5647`, with
  `/home/jd/ov5647` retained as a symlink. This recovers root space needed for Supervisor's backup free-space check.
* Startup previously exceeded the Supervisor's roughly ten minute readiness wait with the large recorder database
  (about 11 GB), producing "assuming a fatal startup error" before Core eventually answered. The October 29 Core
  restart reached `RUNNING` in about one minute; inspect current logs before attributing a future startup failure to
  database size. Boot-time apps wait for Core readiness.

## AppArmor

The vendor kernel (5.15.147-sun60iw2-cyberdeck) has `CONFIG_SECURITY_APPARMOR=y` but its built-in `CONFIG_LSM` list omits
`apparmor`, so it was never active. Adding `lsm=landlock,lockdown,yama,loadpin,safesetid,integrity,apparmor,bpf apparmor=1`
to the kernel arguments enables it (`/sys/module/apparmor/parameters/enabled` = `Y`, 50 Ubuntu profiles in enforce mode,
snap Firefox kiosk and the container stack unaffected). Landlock, Yama, lockdown, loadpin and safesetid are not compiled in
and are ignored.

Where the arguments come from matters: this Pi boots from the **SD card's** `/boot/boot.scr` (the script U-Boot reads
first), which then boots the NVMe system. The arguments are assembled on the `docker_optimizations` line of
`boot.cmd`, so the AppArmor arguments were appended there and the script recompiled with
`mkimage -C none -A arm -T script -d boot.cmd boot.scr`. The NVMe copies (`/boot`, `/boot/efi`) and `grub.cfg` carry the
same change, but only the SD card's script is read on this hardware. Backups of every file touched are in
`/boot/backups/pre-apparmor-*` and `/mnt/opisd-check/boot/backups/pre-apparmor-*`; restore the three files and reboot to undo.

## Rollback

`/srv/cyberdeck-home/pre-supervisor/rollback.sh` (written during the cutover, with copies of the unit files, configs,
iptables and NetworkManager state) removes the Supervisor containers and network, the fstab lines and the drop-in, deletes
  the marker, and starts the compose stack again on the same config.

## Supervisor-managed HTTPS proxy

The community Nginx Proxy Manager app (`a0d7b954_nginxproxymanager`, 4.1.1) owns ports 80, 81 and 443, with automatic
startup and watchdog enabled. Its container is `app_a0d7b954_nginxproxymanager`. Configuration, the SQLite database,
certificate renewal settings and the existing deploy hook live in
`/usr/share/hassio/app_configs/a0d7b954_nginxproxymanager`; app-private state (including the preserved JWT keys) lives in
`/usr/share/hassio/apps/data/a0d7b954_nginxproxymanager`. Both belong in Supervisor app backups. A post-migration
app backup completed successfully on October 29 (slug `91b5713f`), supplementing the earlier full backup.

The proxy reaches Core at `172.30.32.1:8123`, the host's hassio bridge address; loopback would address the proxy app
itself. Generated configuration and certificate renewal paths use `/config`, replacing the standalone image's `/data`.
The migration preserved the database's users, authentication records and certificates. Both HTTPS names returned 200,
the unauthenticated API returned 401, the served TLS fingerprint matched the original, and a Certbot DNS-01 staging
renewal passed with the deploy hook gracefully reloading Nginx. No host reboot was performed.

For a proxy-only rollback, stop the app and set its boot mode to manual before starting `opiha-proxy-1`; the two cannot
own the same ports. The original `/srv/homeassistant/proxy/data` is untouched. Re-enable its systemd unit and Docker
restart policy only if deliberately reverting to the standalone proxy. Private migration snapshots and the original
service settings are in `/srv/cyberdeck-home/ha-repairs-20261029`.

## Things to know

* Google Home 1.14.0 requires `glocaltokens==0.10.0`, whose minimum gRPC version conflicts with Core 2026.9.3's
  constraints. The installed compatible release is Google Home 1.13.3 with `glocaltokens==0.7.6`; install dependencies
  using Core's `homeassistant/package_constraints.txt`. Do not bypass those constraints to force a newer release.
  The manifest allows Core to install these dependencies again when it recreates its container.
* The Supervisor re-creates the Wi-Fi connection profile as "Supervisor wlan0" (same SSID, DHCP) and may manage DNS.
* Home Assistant takes several minutes to start (large recorder database); the Supervisor starts boot-time apps only once
  it reports ready, so apps appear a few minutes after boot.
* The trial that proved this out is in `scripts/supervisor-trial/`.

## Automatic updates

`homeassistant/packages/auto_updates.yaml` installs Core patch releases, Supervisor, apps and HACS updates at 03:30
local time (after a partial backup), skipping major-version jumps and notifying instead. Supervisor/app `auto_update`
flags are off so that automation is the only updater. This host has no Home Assistant OS, so there is no OS update
entity; Ubuntu security/updates are applied by `unattended-upgrades`, whose `apt-daily-upgrade.timer` is pinned to 03:45
(`/etc/systemd/system/apt-daily-upgrade.timer.d/window.conf`). It never reboots automatically; the vendor kernel is
only changed deliberately.
