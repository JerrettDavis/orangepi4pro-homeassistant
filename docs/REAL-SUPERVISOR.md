# Running the real Home Assistant Supervisor on the Orange Pi

Production Home Assistant on this appliance now runs under the actual Supervisor (2026.10.3), not under the compose
stack. The Supervisor is unsupported on third-party Linux; this is a "supervised"-style install and the Supervisor reports
`healthy: true, supported: false` (reasons: AppArmor not in the vendor kernel, not Home Assistant OS, no OS Agent, Docker
configuration, connectivity check, systemd journal). Apps (add-ons), the store, backups, discovery and ingress are the
real ones.

## How it is wired

* The Supervisor runs as the `hassio_supervisor` container (restart `always`) with Docker, D-Bus, udev and
  `/usr/share/hassio` mounted. It creates the `hassio` network (172.30.32.0/23), its plugins (DNS, CLI, audio, multicast,
  observer) and the `homeassistant` container.
* Home Assistant's real config directory (`/srv/homeassistant/ha`, 2026.9.3) is **bind-mounted in place** at
  `/usr/share/hassio/homeassistant` (and the share, media and ssl folders), not copied. `/etc/fstab` carries the mounts.
* `/usr/share/hassio/homeassistant.json` pins Home Assistant to the version on disk. Without that pin the Supervisor
  installs the newest core and would migrate the database. Update the core deliberately, with a backup.
* `/run/supervisor` must exist (`/etc/tmpfiles.d/supervisor.conf`).
* `orangepi-homeassistant.service` has a drop-in (`supervisor.conf`) that starts only the HTTPS proxy
  (`/usr/local/sbin/opiha-proxy-only`); the old Home Assistant container is no longer started.
* `/etc/orangepi-apps/real-supervisor` makes this repository's add-on manager stand down (no shim, no iptables redirects,
  no installs), because both would want 172.30.32.2. The host panel (Overview, Host, Docker, Updates, Terminal) is unchanged;
  use Home Assistant's own Apps page for add-ons.

## Rollback

`/srv/cyberdeck-home/pre-supervisor/rollback.sh` (written during the cutover, with copies of the unit files, configs,
iptables and NetworkManager state) removes the Supervisor containers and network, the fstab lines and the drop-in, deletes
the marker, and starts the compose stack again on the same config.

## Things to know

* The Supervisor re-creates the Wi-Fi connection profile as "Supervisor wlan0" (same SSID, DHCP) and may manage DNS.
* Home Assistant takes several minutes to start (large recorder database); the Supervisor starts boot-time apps only once
  it reports ready, so apps appear a few minutes after boot.
* The trial that proved this out is in `scripts/supervisor-trial/`.
