# Supervisor host recovery inputs

These non-secret settings were checked against the running Orange Pi on
November 27, 2026. They supplement a private Supervisor backup, not replace
the official supervised installer or provision a supported HA OS image.

| Repository file | Host destination |
|---|---|
| `docker-daemon.json` | Merge into `/etc/docker/daemon.json` |
| `hassio.json` | `/etc/hassio.json` |
| `supervisor-tmpfiles.conf` | `/etc/tmpfiles.d/supervisor.conf` |
| `network-connectivity.conf` | `/etc/NetworkManager/conf.d/20-connectivity.conf` |
| `99-auto-updates` | `/etc/apt/apt.conf.d/99-auto-updates` |
| `apt-upgrade-window.conf` | `/etc/systemd/system/apt-daily-upgrade.timer.d/window.conf` |
| `journal-gateway.conf` | `/etc/systemd/system/systemd-journal-gatewayd.socket.d/10-supervisor.conf` |
| `supervisor-launcher.conf` | `/etc/systemd/system/hassio-supervisor.service.d/20-official-launcher.conf` |
| `lightdm-autologin.conf` | `/etc/lightdm/lightdm.conf.d/22-orangepi-autologin.conf` |

Review host-specific users, paths and timezone before installation. Back up
existing files and merge rather than blindly overwriting unrelated settings.
The launcher is provided by the official supervised installer. Also restore
`config/hassio-supervisor-apparmor.conf` as documented in
`docs/REAL-SUPERVISOR.md`, then run `systemctl daemon-reload`.
Do not restart Docker casually: it interrupts HA and the add-ons.

The active app-manager code and kiosk user units matched files already in
this repository or its history. The deployed panel/storage/disk-guard changes
are preserved in the main source tree. The older compose deployment remains
an intentional historical release, not a reason to overwrite the live stack.

Vendor OS packages, generated runtime/cache files, old rollback copies,
personal Codex sessions, SSH authorization/host trust, certificates, account
storage and private network mounts are not public recovery assets. Preserve
those separately with a host backup. Bootloader/AppArmor kernel arguments
and data mounts still need the host recovery steps in `docs/REAL-SUPERVISOR.md`.
