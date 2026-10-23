#!/bin/sh
# Leave the desktop and go back to the full-screen Home Assistant kiosk, which also makes the kiosk the boot default again.
rm -f "$HOME/.config/opiha/kiosk.disabled" "$HOME/.config/opiha/kiosk-controls.disabled"
exec systemctl --user start orangepi-homeassistant-kiosk.service orangepi-homeassistant-kiosk-controls.service
