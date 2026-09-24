# Delivery validation: 0.1.0-alpha.1

Prepared for local testing on **September 23, 2026 (America/Chicago)**.

## Result

**86 passed, 1 skipped, 0 failures, 0 errors.**

The delivered source was exercised on Linux x86_64 using Python 3.13.5. The JUnit result is in `test-results.xml`; structured scope and tool availability are in `validation.json`.

```bash
./scripts/test.sh -q --junitxml=reports/test-results.xml
python3 scripts/scan-public.py
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
| Vision | Debounce/expiry tests and actual OpenCV HOG inference on a blank synthetic frame passed |
| Image overlay and sanitation | Applied to synthetic rootfs directories; known boot fixture preserved; private paths not copied |
| Image-builder safety | Dry-run and bad-input guards passed; no loop-mounted full image was built |
| Source packaging | Allowlist/exclusion, private-key-pattern rejection, deterministic archive tests passed |
| YAML, Python, Bash | YAML parsing, Python compilation and all Bash syntax checks passed |

`systemd-analyze verify` was attempted. It reported absent target installation executables and `docker.service` in this container. That is an **incomplete host-service check**, not a passing boot/systemd integration test.

## Not executed or not implemented

No Docker image pull, container startup, ARM64 container execution, privileged image-apply build, Orange Pi boot, NVMe/SD boot-chain validation, real camera, display/touch session, real Z-Wave controller, external database migration or PowerShell export was tested here. The Docker smoke test and hardware acceptance runbooks are included for those next steps.

No A733 NPU inference backend is implemented. HOG is a CPU baseline, not a validated occupancy/security model. HACS releases were not downloaded or authenticated here. Native Home Assistant backup upload is documented as a user-operated supported path; this repository does not implement private HA restore APIs.

No flashable `.img` is included. No repository or artifacts have been pushed to GitHub. No real household state, keys, credentials, container images, HACS archives or camera footage are included in this source delivery.

## What these results justify

This is a tested **source alpha for local rehearsal and controlled hardware bring-up**, not a certified appliance release. Passing unit/in-process tests does not establish safe operation of the user's existing integrations. Run the real Docker smoke test, a stopped-state import rehearsal, and a spare-media signed recovery drill before decommissioning the Hyper-V VM.

The shipped CI matrix is configured for Python 3.10, 3.12 and 3.13 and installs age for the encryption test. Those GitHub jobs have **not** run merely because their workflow files exist.
