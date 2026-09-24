# Restricted administrative automation

Never send, store, log, or paste the sudo password into this repository or an
automation transcript. The supported mechanism is a single interactive sudo
bootstrap followed by a root-owned fixed-command wrapper.

From the verified source package on the Orange Pi:

```bash
sudo ./scripts/bootstrap-admin.sh "$(id -un)"
sudo -n /usr/local/sbin/opiha-admin daemon-reload
```

The sudoers rule authorizes only `/usr/local/sbin/opiha-admin`. That executable
is root-owned and delegates to code in the root-owned selected release. It
requires exactly one allowlisted word and never evaluates input through a
shell. Arbitrary arguments and commands such as `shell`, `reboot`, `enable`,
or paths are rejected.

Available commands:

| Command | Fixed operation |
|---|---|
| `daemon-reload` | Reload systemd unit metadata |
| `start`, `stop`, `restart` | Operate only `orangepi-homeassistant.service` |
| `status` | Read that unit's status without a pager |
| `render` | Render the installed appliance Compose document |
| `doctor` | Run installed appliance diagnostics |
| `compose-ps` | List only the fixed `opiha` Compose project |
| `journal` | Read the last 300 unit log lines from the last 30 minutes |
| `kiosk-start`, `kiosk-stop`, `kiosk-status` | Operate only the validated `orangepi` XFCE kiosk instance |
| `keyboard-start`, `keyboard-stop`, `keyboard-restart`, `keyboard-status` | Operate only the validated `orangepi` Onboard instance |

Revocation requires one interactive administrative action:

```bash
sudo rm /etc/sudoers.d/orangepi-homeassistant
sudo rm /usr/local/sbin/opiha-admin
```

The wrapper is intentionally extended only through reviewed repository changes.
It does not grant passwordless `sudo`, a root shell, Docker group membership,
or general `systemctl`/`docker` access.
