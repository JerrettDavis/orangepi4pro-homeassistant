# Open work

Single list of everything still open, so nothing is lost between sessions. Items marked **(you)** need the
operator present (interactive sudo, hardware or a decision).

## Orange Pi / Home Assistant
- [ ] Revoke the temporary `NOPASSWD: ALL` grant: `sudo -n /usr/local/sbin/opiha-revoke-autonomy` **(you)**
- [ ] Tap-test the draggable touch strip (0.2.0-alpha.3) and decide whether to enable it at boot **(you)**
- [ ] Non-admin HA user check of the Apps panel on the production panel **(you)**
- [ ] Add-on and Z-Wave migrations; attach the Z-Wave stick and preserve keys/store/NVM first **(you)**
- [ ] Tuya reauthentication **(you)**
- [ ] Delete the archived old stack once migration is accepted **(you)**
- [ ] Camera validation: no V4L2 or media-controller endpoint enumerates yet **(you)**
- [ ] CPU person detector on real camera frames (blocked on camera)
- [ ] README wording: Openbox -> XFCE
- [ ] Image build from a clean cyberdeck base (no base image supplied) **(you)**
- [ ] Spare-media flash and boot/power-cycle recovery (no disposable destination identified) **(you)**

## OPNsense dual-VLAN (HA single-homed at 10.0.0.19, least-privilege VLAN)
Spec and 8-task plan are in `docs/superpowers/` on branch `opnsense-ha-dual-vlan`.
- [ ] Task 1 gate: reviewer GO/NO-GO on the staged dead-man guard bootstrap; then run the bootstrap with the
      operator present for interactive sudo **(you)**
- [ ] Harmless installed lifecycle/reboot/PF/GUI + fresh-SSH proof closes Gate 1
- [ ] Tasks 2-8 of the approved plan
- [ ] Rotate the exposed OPNsense Google Drive backup passphrase via a separately authorized workflow **(you)**
- [ ] Create the sanitized fresh-history `opnsense-deadman` repo per its public-repo design; keep it
      experimental until OPNsense 26.7.4_1 qualification
- OPNsense 26.7 removed safepoint APIs: never use old savepoint recipes.
