# Non-destructive host deployment implementation plan

**Goal:** Add and validate a conservative live-host installer, stage it on the
Orange Pi, and prepare the exact privileged commands needed to start blank Home
Assistant without changing the cyberdeck platform.

**Base branch:** `main`

## Task 1: Define host layout and planning model

**Files:** `src/opiha/host.py`, `tests/test_host.py`

- Add failing tests for the canonical host paths, planned changes, Linux-root
  validation, symlink/path escape refusal, and collision detection.
- Implement immutable layout/change-plan data structures and read-only plan.
- Verify with `pytest tests/test_host.py` and commit.

## Task 2: Implement staged, idempotent install

**Files:** `src/opiha/host.py`, `tests/test_host.py`

- Add failing tests for synthetic-root apply, release hashes, atomic current
  selection, private modes, preservation of marked state, and refusal of
  unowned populated destinations.
- Implement apply without package manager, Docker, systemctl, mount, network,
  or boot operations.
- Verify focused tests and commit.

## Task 3: Expose guarded CLI commands

**Files:** `src/opiha/cli.py`, `tests/test_cli_services.py`, `docs/CLI.md`

- Add `opiha host plan` and `opiha host install [--root] [--apply]`.
- Require root only for applying to `/`; synthetic roots remain testable.
- Verify CLI dry-run/apply behavior and commit.

## Task 4: Add live-host service and runtime configuration

**Files:** `systemd/orangepi-homeassistant.service`, host installer templates,
`tests/test_host.py`

- Generate the requested `/srv/homeassistant` and `/var/lib/orangepi-homeassistant`
  layout while adapting the existing appliance config/Compose machinery.
- Install but do not enable/start a Home-Assistant-only unit.
- Prove unit ordering, rollback instructions, and no kiosk/camera/Z-Wave start.
- Verify focused and full tests; commit.

## Task 5: Reconcile documentation and validation

**Files:** `README.md`, `docs/HOST-INSTALL.md`, `docs/ROLLBACK.md`,
`docs/QUICKSTART.md`, `reports/VALIDATION.md`

- Document exact plan/apply/start/rollback commands and validation tiers.
- Mark the image overlay as image-root tooling, not the first live-host path.
- Run `scripts/validate.py --images`; commit.

## Task 6: Stage and validate on the Orange Pi

- Build the deterministic source package, record SHA-256, copy it to `/tmp`,
  verify checksum and public scan remotely.
- Run `opiha host plan` against the live root and save sanitized evidence.
- Test whether an authenticated root SSH session is available without changing
  state. If not, stop immediately before `sudo ... host install --apply` and
  provide the single interactive command; never request or log a password.
- If elevation is available, apply the installer, inspect the manifest, start
  blank HA, and run persistence/restart/health checks while preserving SSH.
- Update validation documentation with only observed results and commit.

## Task 7: Review and land

- Review the complete diff against the design and live constraints.
- Fix all critical/important findings with tests.
- Run the full Linux validation suite on the final tree.
- Merge/publish only after the exact final tree is green.
