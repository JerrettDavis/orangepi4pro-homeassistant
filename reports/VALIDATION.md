# Delivery validation: 0.1.0-alpha.1

Prepared for local testing on **September 23, 2026 (America/Chicago)**.

## Result

The authoritative Linux/WSL command is green for every required source check
and every pinned image publishes an ARM64 manifest. Optional `age`,
`age-keygen`, and OpenCV checks are explicitly skipped in the current WSL
environment because those tools are absent. Generated reports in this
directory predate the live-host pass and are retained only as alpha-delivery
artifacts; current command output is authoritative until they are regenerated.

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
account cannot access the Docker daemon without interactive elevation, and the
host lacks `age`, FFmpeg, and OpenCV. Details are in
[`docs/LIVE-HARDWARE-BASELINE.md`](../docs/LIVE-HARDWARE-BASELINE.md).

## Not executed or not implemented

No appliance container startup, ARM64 container execution, privileged
image-apply build, spare-media appliance boot, real camera stream, kiosk
session, real Z-Wave controller, external database migration, or production
HA restore has been tested. The Docker smoke test and hardware acceptance
runbooks remain required.

No A733 NPU inference backend is implemented. HOG is a CPU baseline, not a validated occupancy/security model. HACS releases were not downloaded or authenticated here. Native Home Assistant backup upload is documented as a user-operated supported path; this repository does not implement private HA restore APIs.

No flashable `.img` is included. No repository or artifacts have been pushed to GitHub. No real household state, keys, credentials, container images, HACS archives or camera footage are included in this source delivery.

## What these results justify

This is a tested **source alpha for local rehearsal and controlled hardware bring-up**, not a certified appliance release. Passing unit/in-process tests does not establish safe operation of the user's existing integrations. Run the real Docker smoke test, a stopped-state import rehearsal, and a spare-media signed recovery drill before decommissioning the Hyper-V VM.

The shipped CI matrix is configured for Python 3.10, 3.12 and 3.13 and installs age for the encryption test. Those GitHub jobs have **not** run merely because their workflow files exist.
