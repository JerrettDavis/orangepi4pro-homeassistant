# Delivery validation: 0.1.0-alpha.8

Updated after live Orange Pi validation on **September 24, 2026
(America/Chicago)**.

## Result

The authoritative Linux command is green for every required source check and
every pinned image publishes an ARM64 manifest. The current Docker/Linux run
passes 149 tests; age and OpenCV are the two optional local skips. Age is now
installed and runtime-validated on the Orange Pi. OpenCV remains absent because
the board exposes no camera endpoint.

```bash
./scripts/test.sh --images
```

## Executed checks

| Check | Observed result |
|---|---|
| Configuration, path guards and Compose generation | Passed; no Docker daemon involved |
| Quarantine network/device restrictions | Generated-document assertions passed; real daemon test still required |
| Private-state archive round trip | Passed with synthetic `.storage`, private fixtures and recorder-related files |
| Corrupt/malformed archives | Traversal, links, duplicates, checksum mismatch and other negative cases rejected |
| Restore transaction and rollback | Directory replacement, simulated interrupted rename and repair cases passed |
| Ed25519 signatures | Real OpenSSL key generation, signing, verification and tamper rejection passed |
| Age encryption | **Skipped** because `age`/`age-keygen` are not installed here |
| Operational Docker coordination | Mocked stop/resume, disarm and optional-service failure tests passed |
| MQTT credential staging | Native/container command paths tested with simulated password utility; real broker not run |
| Inventory, SQLite and version gates | Passed on synthetic/offline fixtures |
| Diagnostic UI | Real loopback HTTP GET/404/POST rejection requests passed |
| Vision | Debounce/expiry tests passed; actual OpenCV inference is skipped in the current WSL environment |
| Image overlay and sanitation | Applied to synthetic rootfs directories; known boot fixture preserved; private paths not copied |
| Image-builder safety | Dry-run and bad-input guards passed; no loop-mounted full image was built |
| Source packaging | Allowlist/exclusion, private-key-pattern rejection, deterministic archive tests passed |
| YAML, Python, Bash | YAML parsing, Python compilation and all Bash syntax checks passed |

`systemd-analyze verify` was attempted. It reported absent target installation executables and `docker.service` in this container. That is an **incomplete host-service check**, not a passing boot/systemd integration test.

## Live-host observation

Read-only SSH inventory observed the working ARM64 cyberdeck kernel, NVMe
root/boot/EFI roles, LightDM/Xorg display, and native QDtech touchscreen. It
also observed that no camera/media or serial-by-id device exists, the SSH
account initially lacked a restricted administrative path, and the host did
not yet have `age`, FFmpeg, or OpenCV. The restricted wrapper and `age` were
subsequently installed; camera-only dependencies remain deferred. Details are in
[`docs/LIVE-HARDWARE-BASELINE.md`](../docs/LIVE-HARDWARE-BASELINE.md).

## Live-host deployment

Versioned releases through `0.1.0-alpha.8` were checksum-verified, installed
under `/opt/orangepi-homeassistant/releases`, and selected atomically. Private
state remains under `/srv/homeassistant` and generated deployment state under
`/var/lib/orangepi-homeassistant`. The installer did not replace boot assets,
the kernel, device tree, networking, SSH, LightDM, XFCE, or touch support.

## Live ARM64 Home Assistant runtime

The guarded host installer and restricted administrative wrapper were applied
interactively on the observed Orange Pi. The installed Compose render contained
only Home Assistant `2026.9.3`; Z-Wave, MQTT, camera, vision, and kiosk remained
disabled. No packages, boot assets, network configuration, mounts, or existing
cyberdeck services were changed.

The pinned ARM64 image pulled successfully and blank Home Assistant reached a
healthy container state. Its onboarding endpoint responded from both loopback
and the trusted LAN. A full systemd stop/down followed by container recreation
and start succeeded while retaining the `/srv/homeassistant/ha` bind. After
recreation, the onboarding endpoint responded again and the container returned
to healthy state. At observation time the host retained roughly 4.8 GiB
available RAM, negligible swap use, and roughly 32 GiB free root storage.

The first recreation exposed an onboarding gate that mistook HA's automatically
created `.storage/auth` file for imported production state. `0.1.0-alpha.2`
removes that false signal while retaining the explicit `restored.json` and
activation gates; a regression test covers the behavior. The corrected release
passed the complete local and GitHub Actions validation matrices before the
successful on-device recreation.

The appliance unit is intentionally static and not enabled at boot. Docker's
socket is enabled, but host-reboot recovery has not been claimed or tested;
boot enablement remains a separate reviewed step after kiosk/display behavior
and rollback are ready.

## Live kiosk and recovery tooling

The existing LightDM/Xorg/XFCE session launches Firefox 152 through a user
systemd service. The custom kernel lacks SquashFS xattrs, so the unit disables
snapd self re-execution and uses Ubuntu's capability-bearing distro launcher.
Firefox remained active, rendered the HA restore screen at 1024x600, and passed
independent stop/start testing while HA stayed healthy. Physical touch input
still requires a human acceptance tap.

On-device recovery validation created a signed age-encrypted blank-state
bundle, verified its signature, decrypted and validated its archive, and
confirmed HA returned healthy after the coordinated container recreation. The
test identity and archive remain root-only temporary validation artifacts and
are not production recovery material.

The host was subsequently moved from the isolated device WLAN to the primary
trusted WLAN using a staged NetworkManager profile and timed fallback. The new
profile has higher autoconnect priority while the prior profile remains an
enabled fallback. After the move, DHCP routing, local DNS, external HTTPS,
SSH, and the Home Assistant LAN endpoint were validated. Home Assistant stayed
healthy throughout. SSIDs, credentials, addresses, MACs, and profile UUIDs are
intentionally omitted from public evidence.

## Not executed or not implemented

No privileged image-apply build, spare-media appliance boot, real camera
stream, physical kiosk touch, real Z-Wave controller, external database
migration, or production HA restore has been tested. The Docker smoke test and
remaining hardware acceptance runbooks remain required.

No A733 NPU inference backend is implemented. HOG is a CPU baseline, not a validated occupancy/security model. HACS releases were not downloaded or authenticated here. Native Home Assistant backup upload is documented as a user-operated supported path; this repository does not implement private HA restore APIs.

No flashable `.img` is included. The source repository is public on GitHub, but
no release image or private artifact has been published. No real household
state, keys, credentials, container images, HACS archives or camera footage are
included in this source delivery.

## What these results justify

This is a tested **source alpha for local rehearsal and controlled hardware bring-up**, not a certified appliance release. Passing unit/in-process tests does not establish safe operation of the user's existing integrations. Run the real Docker smoke test, a stopped-state import rehearsal, and a spare-media signed recovery drill before decommissioning the Hyper-V VM.

The GitHub CI matrix for Python 3.10, 3.12 and 3.13 has run successfully on the
public repository. CI installs age for the encryption test; it does not claim
Orange Pi hardware coverage.
