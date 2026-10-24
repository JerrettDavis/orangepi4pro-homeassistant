# Changelog

## 0.3.0-alpha.7

Found by running every installable official add-on on the device:

- Host-networked add-ons can reach `http://supervisor/` (extra `nat OUTPUT` rule; the shim accepts this host as a peer).
- `network/info` and `network/interface/<name>/info` report the host's real interfaces; `supervisor/ping` exists.
- Schema rules from YAML block scalars (Piper's voice list) parse; TCP and UDP of the same port number may share a host port.
- MQTT discovery fills Home Assistant's form from its own schema (the real form needs fields the first version omitted).
- The shim notices if its bound address disappears and rebinds.

## 0.3.0-alpha.6

- Add-ons: Home Assistant WebSocket relay (`ws://supervisor/core/websocket`) with token swap, and MQTT discovery that
  registers the add-on's broker through Home Assistant's config-flow API.
- Reading Home Assistant's config directory (even read-only) now needs explicit approval, because it holds secrets.

## 0.3.0-alpha.5

- The Add-ons tab no longer warns that the add-on API is unavailable before any add-on has been installed.

## 0.3.0-alpha.4

- **Add-ons**: a new Add-ons tab installs Home Assistant add-ons from repositories you add, without the Supervisor.
  Manifests are parsed and judged (works / reduced / unsupported) before install; privileges are listed and must be
  approved; options come from a generated form validated against the add-on schema. Images are pulled by digest or
  built from their Dockerfile. See `docs/native-apps/ADDONS.md`.
- A Supervisor-style API shim (`http://supervisor/`) serves add-on info/options, the MQTT/MySQL service registry and
  a Home Assistant REST proxy; unimplemented endpoints answer honestly and are recorded.
- Add-ons run on their own bridge (172.30.32.0/23) with Supervisor-style hostnames; ingress works for add-ons,
  including ones that allow only 172.30.32.2.
- New `opiha-apps repo` and `opiha-apps addon` commands; `configure` lifecycle action.

## 0.3.0-alpha.3

- Panel tab bar collapses unselected tabs to icons when the panel is narrow, so all seven tabs fit the 1024 px kiosk.

## 0.3.0-alpha.2

- Deferred reboot/restart actions fire within a second (transient timers defaulted to one-minute accuracy), a failed
  update job no longer blocks the next one, and the Desktop tab no longer errors while loading.
- The seed dashboard is titled "Orange Pi Home" so it does not duplicate the new sidebar entry.

## 0.3.0-alpha.1

- The Home Assistant sidebar entry is now **Orange Pi** with tabs: Overview (live CPU, memory, temperature,
  storage and network), Host (systemd services, journal, hardware), Docker (containers, logs, images),
  Apps (the existing native-app manager), Updates (apt and snap, run as host jobs that survive a restart),
  Terminal (xterm.js shell as the kiosk user) and Desktop (switch the kiosk to the XFCE desktop and back,
  choose the boot default, blank the screen).
- New `/v1/host/*` operations on the loopback manager, reached only through an admin-only HA WebSocket command.
  Destructive actions need `confirm: true`; stop/disable of SSH, the manager, D-Bus and networking is refused.
- The terminal is off until `opiha-apps host-terminal on`, because it is a shell on the host.
- Host install adds a "Return to Home Assistant kiosk" application-menu launcher for desktop mode.

## 0.2.0-alpha.8

- Touch strip buttons are now an icon over a small label (Refresh, Home, Restart) instead of large text, and
  the strip no longer flickers open on the wrong side when it closes.

## 0.2.0-alpha.7

- Touch strip: the handle stays put when the strip opens (it moves to the end the strip grows away from),
  the strip falls back to the side that fits instead of overflowing, and the collapsed width is measured
  rather than the stale window size, which fixes the jump on collapse and the snap-back when dragging.

## 0.2.0-alpha.6

- Kiosk touch strip is position aware: it grows rightwards from the handle in the left half of the screen and
  leftwards in the right half, so the handle no longer jumps when it is dragged near an edge.

## 0.2.0-alpha.5

- Kiosk touch strip restyled to match the dark Home Assistant theme: `#111111` tile, `#262a2e` keys with
  `#3a3f45` borders, blue accent handle and pressed state (same palette as the on-screen keyboard).

## 0.2.0-alpha.4

- On-screen keyboard: new `OrangePiHA` Onboard theme (dark, flat rounded keys, Ubuntu font, Home Assistant
  blue accent, orange for locked modifiers) in `config/onboard/`. `keyboard-session.sh` installs it for the
  session user and selects it, and sets background transparency to 0 so the page no longer shows through.
- The floating keyboard toggle button follows the theme too (dark tile, blue/grey key glyph, no "O"/"B"
  letters). Onboard fixes that button's overall opacity in code, so it stays slightly translucent.

## 0.2.0-alpha.3

- Kiosk touch strip: narrower minimized handle, and the handle can be dragged to reposition the strip
  (a tap still expands it). The position is kept on screen and remembered in
  `~/.config/opiha/kiosk-controls-position.json`; delete that file to return to bottom centre.

## 0.2.0-alpha.2

- Forward Node-RED's `Node-RED-API-Version` and `Node-RED-Deployment-Type` request headers through the
  reviewed ingress allowlist. Found on-device: without them the editor received the legacy `/flows`
  format and failed with "Error adding flows".
- Add kiosk touch controls (Reload, Home, Restart browser) with `controls-*` admin commands.
- Includes the kiosk display-sleep releases 0.1.0-alpha.13 and 0.1.0-alpha.14 (below).

## 0.2.0-alpha.1

- Add the native Docker app manager (`opiha-apps`, also `opiha apps`) and the admin-only
  `opiha_apps` Home Assistant panel/ingress integration for a reviewed catalog:
  Node-RED, ESPHome, Mosquitto, Z-Wave JS UI and go2rtc, pinned by multi-arch index digest.
- Add fixed `apps-*` restricted-admin commands, image overlay/audit coverage and CI checks.
- Z-Wave and camera apps remain inactive pending hardware verification.

## 0.1.0-alpha.14

- Align the release and hardware guides with the deployed two-minute X11 DPMS
  behavior and cover non-fatal failures of each display-power hint.

## 0.1.0-alpha.13

- Let the X11 touchscreen kiosk display turn off after 120 seconds of inactivity
  through DPMS while leaving touch wake as a physical acceptance check.

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
