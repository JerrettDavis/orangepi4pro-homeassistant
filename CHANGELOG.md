# Changelog

## 0.1.0-alpha.12

- Enable Firefox's XInput2 path so one-finger drags on the X11 touchscreen
  scroll Home Assistant instead of selecting page text.

## 0.1.0-alpha.8

- Disable snapd self re-execution for the kiosk on the custom kernel, whose
  SquashFS build cannot expose the launcher capabilities stored in the snap.
- Add a fixed restricted-admin command for kiosk journal diagnostics.

## 0.1.0-alpha.7

- Allow the Firefox Snap launcher to perform its required confinement capability transition.

## 0.1.0-alpha.6

- Treat unsupported X11 screen-saver and DPMS controls as non-fatal kiosk hints.
- Emit a clear launch diagnostic before handing control to Firefox.

## 0.1.0-alpha.5

- Run the Firefox Snap kiosk in the existing graphical user's systemd manager.
- Safely remove the installer-owned legacy system kiosk unit during upgrade.

## 0.1.0-alpha.4

- Make installed public release directories traversable by the unprivileged kiosk user.

## 0.1.0-alpha.3

- Added an XFCE/Xorg Firefox kiosk that preserves the working cyberdeck display stack.
- Added fixed restricted-admin commands for independent kiosk operation.

## 0.1.0-alpha.2

- Added the non-destructive live-host installer and restricted administrative wrapper.
- Fixed blank Home Assistant onboarding restarts after HA creates its initial auth store.

## 0.1.0-alpha.1

Initial source delivery: private-state appliance CLI, guarded migrations, loopback/private service topology, CPU presence baseline, native kiosk, signed/encrypted recovery, public clean-base image overlay, optional software cache, tests, CI and runbooks. Hardware, Docker, PowerShell and full image-apply validation remain explicitly outstanding in the delivery report.
