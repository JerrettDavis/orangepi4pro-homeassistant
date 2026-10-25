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

* Host logs: `systemd-journal-remote` (Ubuntu package) provides `systemd-journal-gatewayd`; its socket listens on
  `/run/systemd-journal-gatewayd.sock` (drop-in `10-supervisor.conf`) and is mounted into `hassio_supervisor`.
  That clears the Supervisor's `systemd_journal` unsupported reason.
* OS Agent: the official `os-agent` 1.14.0 `.deb` (home-assistant/os-agent, arm64) provides the `io.hass.os` D-Bus
  service. The Supervisor then lists `os_agent`, `journal`, `resolved`, `timedate` and `disk` host features.
* Docker: `/etc/docker/daemon.json` sets `"log-driver": "journald"` (the Supervisor requires it; applies to containers
  created afterwards). `hassio_supervisor` has restart policy `no` and is started by `hassio-supervisor.service`
  (`docker start -a`), as the supervised installer does.
* NetworkManager: `/etc/NetworkManager/conf.d/20-connectivity.conf` enables the connectivity check.
* Unsupported reasons left: `apparmor` (the vendor kernel has none), `os` (not Home Assistant OS) and `software`
  (the HTTPS proxy container is not Supervisor-managed). Down from seven before the hardening.
* Startup: with this recorder database (about 11 GB) Home Assistant needs more than the Supervisor's roughly ten minute
  readiness wait, so after a boot the Supervisor logs "assuming a fatal startup error" and raises a `fatal_error` issue,
  then carries on once Home Assistant answers. Boot-time apps start after that. Trimming the database would fix it.

## Rollback

`/srv/cyberdeck-home/pre-supervisor/rollback.sh` (written during the cutover, with copies of the unit files, configs,
iptables and NetworkManager state) removes the Supervisor containers and network, the fstab lines and the drop-in, deletes
the marker, and starts the compose stack again on the same config.

## Things to know

* The Supervisor re-creates the Wi-Fi connection profile as "Supervisor wlan0" (same SSID, DHCP) and may manage DNS.
* Home Assistant takes several minutes to start (large recorder database); the Supervisor starts boot-time apps only once
  it reports ready, so apps appear a few minutes after boot.
* The trial that proved this out is in `scripts/supervisor-trial/`.
