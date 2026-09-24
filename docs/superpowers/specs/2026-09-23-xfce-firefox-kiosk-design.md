# XFCE Firefox kiosk design

## Goal

Show the local Home Assistant UI on the working Orange Pi touchscreen without
replacing LightDM, Xorg, XFCE, the autologin account, touch drivers, or the
cyberdeck desktop configuration.

## Session integration

Install a static systemd template unit instantiated with the existing graphical
username. The unit runs unprivileged as that user, targets display `:0`, uses
the user's LightDM Xauthority file and session bus, and starts only after the
display manager and Home Assistant unit. It does not start a second X server or
change LightDM configuration.

The kiosk script waits for both X11 and the local HA HTTP endpoint, disables
screen blanking for the appliance panel, then launches the already-installed
Firefox Snap in kiosk mode. The browser profile lives below the graphical
user's Snap-writable home and never in Git or a public image. The launch URL is
credential-free. Firefox/HA crashes cause systemd to restart the kiosk.

## Maintenance and safety

The restricted administrative wrapper gains only fixed
`kiosk-start`, `kiosk-stop`, and `kiosk-status` operations for the known
instance. The service remains static during initial validation; boot enablement
is a later explicit step. Stopping kiosk leaves SSH, HA, and the XFCE desktop
running. A sentinel file in the graphical user's config directory prevents
launch for local maintenance.

## Validation

Fixture tests verify unit isolation, fixed admin vectors, credential-free
launch, Snap-compatible profile location, and maintenance behavior. On-device
validation confirms Firefox joins the active Xorg session, stays running,
reaches HA, can be independently stopped/restarted, and leaves touch/XFCE/SSH
intact. Visual/touch confirmation remains a human hardware check.
