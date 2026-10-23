# Orange Pi panel: host control inside Home Assistant

The sidebar entry **Orange Pi** (admin only) replaces the old "Orange Pi Apps" entry. It is the nearest thing this
Container install has to the HAOS Supervisor screens, and lets the touchscreen kiosk stand in for the desktop.

| Tab | What it does |
|---|---|
| Overview | Live CPU, memory, temperatures, storage, network; failed services; reboot-required; reboot / shut down; screen off |
| Host | Every systemd service (start, stop, restart, enable, disable, logs), the journal, block devices and USB |
| Docker | Containers (start, stop, restart, logs, remove), images, volumes, networks, prune dangling images |
| Apps | The native-app manager from `docs/native-apps/` |
| Updates | `apt` and snap updates run as a host job (`opiha-host-job`) that survives a panel or manager restart; reboot prompt |
| Terminal | xterm.js shell on the host, with touch keys (Esc, Tab, Ctrl+C, arrows) |
| Desktop | Switch the kiosk to the XFCE desktop and back, choose the boot default, blank/wake the screen |

## How it is built

`panel.js` is the shell; each tab is a module in `homeassistant/custom_components/opiha_apps/`. Tabs call one
admin-only HA WebSocket command, `opiha_apps/host`. The integration forwards it to the loopback root manager
(`orangepi-apps.service`, `POST /v1/host/<operation>`) using the server-side bearer token, which never reaches the
browser. `src/opiha_apps/hostctl.py` validates every field and runs fixed argument vectors, never a shell.
Anything that writes outside the manager's sandbox (apt, enabling units, power, the kiosk user's files) runs through
`systemd-run`, so it executes in PID 1's context. Reboots and restarts of the manager itself are scheduled two to
three seconds out so the HTTP reply is delivered first.

## Safety rules

- Destructive actions need `confirm: true` and the panel asks first.
- `ssh`, `orangepi-apps`, `dbus`, `systemd-logind`, `journald`, networkd/NetworkManager and `systemd-resolved` can be
  restarted but never stopped or disabled from the panel.
- Containers belonging to the HA stack or the Apps tab cannot be removed from the Docker tab.
- An HA administrator can therefore do almost anything on the host. The kiosk account must be an administrator to see
  the panel, so give the kiosk a dedicated admin account and treat physical access accordingly.

## Terminal (opt-in)

A host shell is the strongest control, so it ships off. On the host:

```bash
sudo python3 /opt/orangepi-apps/current/bin/opiha-apps host-terminal on   # --user NAME to change the account
sudo systemctl restart orangepi-apps.service
```

The shell runs as `host_user` (default `orangepi`, the kiosk account) through `systemd-run --pty` with a PAM login
session; it has whatever `sudo` that account has. At most three sessions exist, each is closed 60 seconds after the
panel stops polling it, and `host-terminal off` removes the capability.

## Desktop and kiosk

The kiosk is a full-screen Firefox over the existing XFCE session, so "desktop" simply stops the kiosk and touch strip
(the on-screen keyboard keeps running). To return, press *Return to kiosk* in the panel from any browser, or open
**Return to Home Assistant kiosk** in the XFCE applications menu (installed by `opiha host install`). The boot
preference is the existing `~/.config/opiha/kiosk.disabled` marker, so *Boot into desktop* creates it and starting the
kiosk removes it again.

## Updates

`apt-get upgrade` is never run implicitly. Refresh, review the list, then upgrade. Kernel, bootloader and board
packages on this device come from the vendor image, so review held and upgradable lists before confirming.
