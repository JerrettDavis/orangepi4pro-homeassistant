# Touchscreen kiosk

The validated cyberdeck display stack is LightDM, Xorg `:0`, and XFCE under the
existing graphical account. The appliance reuses that session. It does not
install Openbox, change autologin, start another X server, or replace touch
configuration.

The static user unit `orangepi-homeassistant-kiosk.service` runs Firefox inside
the existing graphical user's systemd session, as required by the Firefox Snap.
It waits for X11 and local Home Assistant, launches a
credential-free loopback URL in kiosk mode, and restarts after browser failure.
The persistent Firefox profile is private runtime state below the user's
`snap/firefox/common` directory and must be included in the encrypted recovery
bundle later.

At kiosk launch, X11 screen-saver blanking is disabled and DPMS is enabled with
standby and suspend disabled. DPMS turns the display off after 120 seconds of
inactivity by default; a touch on the physical touchscreen should wake it.
Confirm both blanking and touch wake on the actual panel before accepting this
behavior. An X11 configuration or another session component may override the
timeout after launch.

## On-screen keyboard

`orangepi-homeassistant-keyboard.service` runs the host's existing Onboard
keyboard in the same XFCE/X11 session. It starts hidden, appears when an
editable control receives focus through AT-SPI, and hides when requested. A
small floating Onboard button remains above the full-screen browser for manual
show/hide; the keyboard itself is not permanently visible. The kiosk unit
starts the keyboard first so Firefox does not retain focus from before Onboard
began listening.

The live 1024x600 layout uses a 205-pixel-tall keyboard at the bottom of the
screen. The service is independently controllable:

```bash
sudo -n /usr/local/sbin/opiha-admin keyboard-start
sudo -n /usr/local/sbin/opiha-admin keyboard-restart
sudo -n /usr/local/sbin/opiha-admin keyboard-status
sudo -n /usr/local/sbin/opiha-admin keyboard-journal
sudo -n /usr/local/sbin/opiha-admin keyboard-stop
```

For maintenance, create `~/.config/opiha/keyboard.disabled` as the graphical
user and stop the service. Remove that marker before starting it again. The
manual toggle helper is
`/opt/orangepi-homeassistant/current/scripts/keyboard-toggle.sh` and uses
Onboard's session D-Bus interface without storing credentials.

For the observed host:

```bash
sudo -n /usr/local/sbin/opiha-admin kiosk-daemon-reload
sudo -n /usr/local/sbin/opiha-admin kiosk-start
sudo -n /usr/local/sbin/opiha-admin kiosk-status
sudo -n /usr/local/sbin/opiha-admin kiosk-journal
sudo -n /usr/local/sbin/opiha-admin kiosk-stop
```

The observed cyberdeck kernel has `CONFIG_SQUASHFS_XATTR` disabled. The unit
sets `SNAP_REEXEC=0` so Firefox uses Ubuntu's capability-bearing distro
`snap-confine` instead of re-executing the copy inside the newer `snapd` snap.
This is a host-specific compatibility setting, not a relaxation of Firefox's
Snap confinement.

## Touch controls (reload, home, restart)

The full-screen browser has no address bar, reload button or update control.
`orangepi-homeassistant-kiosk-controls.service` (a user unit, installed disabled
like the keyboard) shows a small always-on-top handle at the bottom centre of
the screen. Drag the handle to move the strip anywhere on screen (the position is remembered in
`~/.config/opiha/kiosk-controls-position.json`; delete it to return to bottom centre). Tapping it reveals **Reload** (hard reload, which also picks up a
new custom panel script), **Home** (back to the local HA URL) and **Restart
browser** (restarts the kiosk unit, which also lets snapd apply a pending
Firefox update). The strip never takes keyboard focus and collapses after eight
seconds. It runs only fixed command vectors (`xdotool`, `systemctl --user`) and
silences the snapd "update available" popup through XFCE's do-not-disturb so it
cannot cover the page header. Disable it by creating
`~/.config/opiha/kiosk-controls.disabled`. Control it with
`opiha-admin controls-start|controls-stop|controls-restart|controls-status`.
It needs `xdotool` and `python3-gi` (listed in `image/install-dependencies.sh`).

## Validation on the live Orange Pi

The Firefox process remained active across multiple observations and rendered
the HA onboarding/restore page at 1024x600. Stopping the kiosk removed Firefox
without stopping HA; starting it created a new Firefox process and HA remained
healthy. A captured X11 screenshot provides visual evidence without containing
credentials or household state.

Physical touch interaction was performed by the operator on the Orange Pi on
2026-10-21. The services remain deliberately disabled at boot until the operator
chooses to enable them; manual start and crash recovery are validated.

Onboard 1.4.1 was validated on the live Orange Pi against Firefox: a real
AT-SPI focus transition to the Home Assistant username field displayed the
keyboard above the kiosk, and the D-Bus toggle hid it again. Physical tapping
of the floating toggle remains a human acceptance check.

Stopping the kiosk does not stop Home Assistant, XFCE, touch, or SSH. To prevent
an intentional start during maintenance, create
`~/.config/opiha/kiosk.disabled` as the graphical user; remove it before the
next start. The service is initially static and is not enabled at boot until a
display/reboot acceptance test is explicitly approved.

No HA token, password, or authenticated URL is stored in the unit or process
arguments. Complete login once with a dedicated non-administrator HA account;
the browser profile retains that session. Browser/keyring changes can still
require reauthentication after restore.
