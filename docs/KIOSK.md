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

## Validation on the live Orange Pi

The Firefox process remained active across multiple observations and rendered
the HA onboarding/restore page at 1024x600. Stopping the kiosk removed Firefox
without stopping HA; starting it created a new Firefox process and HA remained
healthy. A captured X11 screenshot provides visual evidence without containing
credentials or household state.

Physical touch interaction has not yet been performed by a human. The service
also remains deliberately disabled at boot until that acceptance tap is
complete; manual start and crash recovery are validated.

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
