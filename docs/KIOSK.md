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

Stopping the kiosk does not stop Home Assistant, XFCE, touch, or SSH. To prevent
an intentional start during maintenance, create
`~/.config/opiha/kiosk.disabled` as the graphical user; remove it before the
next start. The service is initially static and is not enabled at boot until a
display/reboot acceptance test is explicitly approved.

No HA token, password, or authenticated URL is stored in the unit or process
arguments. Complete login once with a dedicated non-administrator HA account;
the browser profile retains that session. Browser/keyring changes can still
require reauthentication after restore.
