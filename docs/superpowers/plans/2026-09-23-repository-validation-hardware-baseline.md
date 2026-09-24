# Repository Validation and Hardware Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add safe, testable hardware inventory and validation commands, then document the sanitized live Orange Pi baseline from observed evidence.

**Architecture:** A new `opiha.hardware` module owns command execution, parsers, sanitization, and storage ancestry. The existing CLI exposes a `hardware` command group and delegates to that module. A separate validation script composes existing tests and registry-manifest checks without coupling live hardware to normal CI.

**Tech Stack:** Python 3.10+, argparse, pathlib, subprocess, pytest, Docker Buildx registry inspection, Bash, Markdown

**Spec:** `docs/superpowers/specs/2026-09-23-repository-validation-hardware-baseline-design.md`

## Global Constraints

- Default inventory output must be safe to commit and must exclude IP/MAC addresses, UUIDs, serial numbers, hostnames, private usernames, credentials, and Z-Wave key material.
- Private inventory requires an explicit output path outside the repository and mode `0600` on POSIX.
- Inventory is read-only: no installs, mounts, service changes, Docker mutations, or boot/storage writes.
- Hardware tests remain separate from ordinary CI.
- Linux is authoritative for appliance behavior.
- A missing optional command is represented as unavailable, not as success or a crash.
- No current root, boot, or EFI parent disk may ever be considered a flash candidate.

## Review Focus

- Malicious or unexpected command output must not bypass sanitization or inject secrets into public inventory; Task 1 tests credential-shaped values and nested structures.
- Partition ancestry must remain safe for NVMe, MMC, device-mapper, and ambiguous inputs; Task 2 tests mounted and unresolved parents.
- Private output paths using symlinks or repository descendants must be refused; Task 3 tests both cases.
- Registry indexes contain attestation manifests marked `unknown/unknown`; Task 4 tests that they neither count as ARM64 nor cause a valid ARM64 entry to be missed.
- Live commands may fail with permission denied or be missing; Tasks 1 and 3 test explicit unavailable/error reporting without mutation.

---

### Task 1: Hardware parsers and public sanitization

**Files:**
- Create: `src/opiha/hardware.py`
- Create: `tests/test_hardware.py`

**Interfaces:**
- Produces: `redact(value: object) -> object`, `parse_lsblk(text: str) -> list[dict]`, `parse_findmnt(text: str) -> dict[str, str]`, `parse_devices(text: str) -> list[str]`, `CommandResult`.
- Consumes: `ApplianceError` from `opiha.common`.

- [ ] **Step 1: Write failing sanitizer and parser tests**

```python
from opiha import hardware

def test_redact_removes_private_identifiers_recursively():
    source = {"address": "192.0.2.12", "mac": "00:11:22:33:44:55",
              "uuid": "11111111-2222-3333-4444-555555555555",
              "serial": "SECRET-SERIAL", "hostname": "private-host",
              "nested": ["token=secret-value", {"safe": "aarch64"}]}
    text = str(hardware.redact(source))
    for secret in ("192.0.2.12", "00:11:22:33:44:55", "11111111-2222-3333-4444-555555555555",
                   "SECRET-SERIAL", "private-host", "secret-value"):
        assert secret not in text
    assert "aarch64" in text

def test_parse_lsblk_accepts_json_and_preserves_ancestry():
    rows = hardware.parse_lsblk('{"blockdevices":[{"name":"nvme0n1","path":"/dev/nvme0n1","type":"disk","children":[{"name":"nvme0n1p3","path":"/dev/nvme0n1p3","type":"part","pkname":"nvme0n1","mountpoints":["/"]}]}]}')
    assert rows[1]["parent"] == "/dev/nvme0n1"
    assert rows[1]["mountpoints"] == ["/"]
```

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest tests/test_hardware.py -q`
Expected: collection fails because `opiha.hardware` does not exist.

- [ ] **Step 3: Implement minimal parsers and sanitizer**

Implement `CommandResult` as a frozen dataclass with `argv`, `returncode`,
`stdout`, and `status` fields. `parse_lsblk` must JSON-decode the document,
walk every `children` list depth-first, normalize `pkname` to a `/dev/...`
parent, and always return a list-valued `mountpoints`. `redact` must recurse
through dictionaries, lists, tuples, and strings; sensitive dictionary keys
become `"redacted"`, while address-, UUID-, credential-, hostname-, and
serial-shaped substrings in free text are replaced with `[redacted]`.

- [ ] **Step 4: Run focused and full tests**

Run: `pytest tests/test_hardware.py -q && pytest -q`
Expected: hardware tests and the existing suite pass.

- [ ] **Step 5: Commit**

```bash
git add src/opiha/hardware.py tests/test_hardware.py
git commit -m "feat: add sanitized hardware inventory parsers"
```

### Task 2: Storage ancestry and flash safety classification

**Files:**
- Modify: `src/opiha/hardware.py`
- Modify: `tests/test_hardware.py`

**Interfaces:**
- Consumes: normalized rows from `parse_lsblk`.
- Produces: `protected_disks(rows: list[dict], mounts: dict[str, str]) -> set[str]`, `classify_flash_target(path: str, rows: list[dict], mounts: dict[str, str]) -> dict`.

- [ ] **Step 1: Write failing storage safety tests**

```python
def test_current_root_parent_disk_is_rejected():
    rows = fixture_rows()
    result = hardware.classify_flash_target("/dev/nvme0n1", rows, {"/": "/dev/nvme0n1p3", "/boot": "/dev/nvme0n1p2"})
    assert not result["safe"]
    assert "root" in result["reasons"]

def test_mounted_sd_is_rejected_even_when_not_boot_disk():
    rows = fixture_rows(with_mounted_sd=True)
    result = hardware.classify_flash_target("/dev/mmcblk1", rows, {"/": "/dev/nvme0n1p3"})
    assert not result["safe"]
    assert "mounted" in result["reasons"]

def test_ambiguous_or_non_disk_target_is_rejected():
    assert not hardware.classify_flash_target("/dev/missing", fixture_rows(), {})["safe"]
    assert not hardware.classify_flash_target("/dev/nvme0n1p3", fixture_rows(), {})["safe"]
```

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest tests/test_hardware.py -q`
Expected: failures report missing `classify_flash_target`.

- [ ] **Step 3: Implement conservative ancestry classification**

Implement `classify_flash_target` with an initially unsafe result containing
the path and an empty reasons list. Require exactly one normalized row with
that path and `type == "disk"`. Walk each `/`, `/boot`, and `/boot/efi`
source through parent links until a disk is reached; unresolved or cyclic
ancestry adds `ambiguous`. Matching a protected disk adds the corresponding
`root`, `boot`, or `efi` reason. Any mountpoint on the disk or descendants
adds `mounted`. Set `safe` only when the reasons list remains empty.

- [ ] **Step 4: Run focused and full tests**

Run: `pytest tests/test_hardware.py -q && pytest -q`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/opiha/hardware.py tests/test_hardware.py
git commit -m "feat: add conservative block device safety model"
```

### Task 3: Hardware CLI and secure output

**Files:**
- Modify: `src/opiha/cli.py`
- Modify: `src/opiha/hardware.py`
- Modify: `tests/test_hardware.py`
- Modify: `tests/test_cli_services.py`
- Modify: `docs/CLI.md`

**Interfaces:**
- Consumes: parsers, redaction, and storage classification from Tasks 1-2.
- Produces: `collect_inventory(private: bool = False, runner=run_command) -> dict`, `write_inventory(result: dict, output: Path, private: bool) -> None`, CLI commands `hardware inventory|camera|zwave|storage`.

- [ ] **Step 1: Write failing CLI and output-safety tests**

```python
def test_hardware_inventory_cli_emits_sanitized_json(monkeypatch, capsys):
    monkeypatch.setattr(hardware, "collect_inventory", lambda private=False: {"architecture": "aarch64", "address": "redacted"})
    assert cli.main(["hardware", "inventory"]) == 0
    assert '"architecture": "aarch64"' in capsys.readouterr().out

def test_private_inventory_refuses_repository_path(tmp_path):
    with pytest.raises(ApplianceError):
        hardware.write_inventory({"private": True}, REPO / "private-inventory.json", private=True)

def test_private_inventory_file_is_mode_0600(tmp_path):
    target = tmp_path / "private.json"
    hardware.write_inventory({"private": True}, target, private=True)
    assert target.stat().st_mode & 0o777 == 0o600
```

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest tests/test_hardware.py tests/test_cli_services.py -q`
Expected: parser rejects `hardware`, and output helper is missing.

- [ ] **Step 3: Implement read-only collection and CLI delegation**

```python
hardware_parser = sub.add_parser("hardware")
hardware_sub = hardware_parser.add_subparsers(dest="hardware_command", required=True)
inventory_parser = hardware_sub.add_parser("inventory")
inventory_parser.add_argument("--output", type=Path)
inventory_parser.add_argument("--private", action="store_true")
for command in ("camera", "zwave", "storage"):
    hardware_sub.add_parser(command)
```

Collection uses fixed argument arrays for `uname`, `lsblk --json`, `findmnt`, `systemctl`, `ip`, `v4l2-ctl`, and tool version probes. It never invokes a shell and stores command failures as status values.

- [ ] **Step 4: Run focused and full tests**

Run: `pytest tests/test_hardware.py tests/test_cli_services.py -q && pytest -q`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/opiha/cli.py src/opiha/hardware.py tests/test_hardware.py tests/test_cli_services.py docs/CLI.md
git commit -m "feat: expose read-only hardware diagnostics"
```

### Task 4: ARM64 manifest and repository validation entry point

**Files:**
- Create: `scripts/validate.py`
- Create: `tests/test_validation.py`
- Modify: `scripts/test.sh`
- Modify: `Makefile`
- Modify: `docs/QUICKSTART.md`

**Interfaces:**
- Produces: `manifest_platforms(raw: str) -> set[str]`, `validate_images(images: dict[str, str], inspector: Callable[[str], str]) -> list[dict]`, `run_checks(commands: list[list[str]]) -> dict`.
- Consumes: image references from `config/image-defaults.json` and existing test/scanner/package commands.

- [ ] **Step 1: Write failing manifest and aggregation tests**

```python
def test_manifest_platforms_ignores_attestations():
    raw = "Platform: linux/amd64\nPlatform: unknown/unknown\nPlatform: linux/arm64/v8\n"
    assert validation.manifest_platforms(raw) == {"linux/amd64", "linux/arm64/v8"}

def test_missing_arm64_is_failure():
    result = validation.validate_images({"fixture": "example.invalid/app:1"}, inspector=lambda _: "Platform: linux/amd64\n")
    assert result == [{"name": "fixture", "image": "example.invalid/app:1", "arm64": False}]

def test_validation_aggregate_preserves_skip_reason():
    summary = validation.summarize([{"name": "age", "status": "skip", "reason": "age not installed"}])
    assert summary["skipped"] == 1
    assert summary["checks"][0]["reason"] == "age not installed"
```

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest tests/test_validation.py -q`
Expected: import fails because `scripts/validate.py` does not exist.

- [ ] **Step 3: Implement validation orchestration**

The script executes fixed commands, emits JSON, and exits nonzero for failed required checks. `--images` performs read-only `docker buildx imagetools inspect`; `--docker-smoke` remains opt-in. Shell syntax covers only files with shell shebangs or `.sh` suffixes.

- [ ] **Step 4: Run focused tests, complete Linux validation, and manifest checks**

Run: `pytest tests/test_validation.py -q && python scripts/validate.py --images`
Expected: tests pass; the summary reports all four images with `arm64: true` and no required failures.

Run: `python scripts/validate.py`
Expected: scanner, compilation, tests, shell syntax, render, and packaging pass; optional checks have explicit reasons.

- [ ] **Step 5: Commit**

```bash
git add scripts/validate.py tests/test_validation.py scripts/test.sh Makefile docs/QUICKSTART.md
git commit -m "feat: add honest repository validation command"
```

### Task 5: Sanitized live baseline and claim reconciliation

**Files:**
- Create: `docs/LIVE-HARDWARE-BASELINE.md`
- Modify: `README.md`
- Modify: `reports/VALIDATION.md`
- Modify: `docs/HARDWARE.md`
- Modify: `docs/HOST-INSTALL.md`
- Modify: `docs/NEXT-STEPS.md`
- Modify: `scripts/scan-public.py`
- Modify: `tests/test_release.py`

**Interfaces:**
- Consumes: live inventory schema and validation tiers from Tasks 1-4.
- Produces: public hardware baseline and stronger scanner protection for local identifiers.

- [ ] **Step 1: Write failing public-scanner tests for baseline-sensitive identifiers**

```python
@pytest.mark.parametrize("value", [
    "10.23.45.67", "00:11:22:33:44:55", "UUID=11111111-2222-3333-4444-555555555555",
    "AGE-SECRET-KEY-1" + "A" * 40,
])
def test_source_scanner_blocks_private_machine_identifiers(tmp_path, monkeypatch, value):
    scanner = load_scanner(monkeypatch)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/LIVE-HARDWARE-BASELINE.md").write_text(value)
    _, issues = scanner.scan(tmp_path)
    assert issues
```

- [ ] **Step 2: Run scanner tests and verify RED**

Run: `pytest tests/test_release.py -q`
Expected: IP, MAC, or UUID cases fail because the scanner does not yet detect them.

- [ ] **Step 3: Harden scanner and write evidence-based documentation**

The baseline records device roles rather than local IDs; it names the exact kernel/DTB versions, native touch path, absent camera/serial/NPU nodes, missing host dependencies, Docker permission boundary, failed pre-existing dnsmasq unit, resource snapshot, and repository differences. Every capability uses the spec's validation tiers.

- [ ] **Step 4: Run full validation and public scan**

Run: `python scripts/validate.py --images`
Expected: all required checks pass, all four images report ARM64, and public scan reports zero issues.

- [ ] **Step 5: Commit**

```bash
git add docs/LIVE-HARDWARE-BASELINE.md README.md reports/VALIDATION.md docs/HARDWARE.md docs/HOST-INSTALL.md docs/NEXT-STEPS.md scripts/scan-public.py tests/test_release.py
git commit -m "docs: record sanitized Orange Pi hardware baseline"
```

### Task 6: Live sanitized inventory verification

**Files:**
- Modify only if a verified defect is found: `src/opiha/hardware.py`, `tests/test_hardware.py`, `docs/LIVE-HARDWARE-BASELINE.md`

**Interfaces:**
- Consumes: installed source checkout copied to a temporary remote directory and the `hardware inventory` command.
- Produces: local private evidence of a successful live run; no raw live output is committed.

- [ ] **Step 1: Package the committed source and copy it to a temporary user-owned path on the Orange Pi**

Run: `python scripts/package.py --output <temporary-local-output>` followed by `scp` to a unique `/tmp/opiha-validation-*` directory.
Expected: package creation and transfer succeed without including `.git`, `.local`, or private state.

- [ ] **Step 2: Run public inventory unprivileged on the Orange Pi**

Run: `ssh <host> 'python3 /tmp/opiha-validation-*/bin/opiha hardware inventory'`
Expected: JSON output reports AArch64, the custom cyberdeck kernel, protected NVMe roles, native touch, absent camera and serial devices, and permission-limited Docker server status without local addresses or IDs.

- [ ] **Step 3: Scan captured output locally for forbidden identifiers**

Run: `python scripts/scan-public.py <temporary-capture-directory>`
Expected: zero issues; targeted searches find no live IP, MAC, UUID, disk serial, or hostname.

- [ ] **Step 4: Run final supported-platform validation**

Run: `python scripts/validate.py --images`
Expected: all required checks pass and optional skips are explicit.

- [ ] **Step 5: Commit only verified corrections, if any**

```bash
git add src/opiha/hardware.py tests/test_hardware.py docs/LIVE-HARDWARE-BASELINE.md
git commit -m "fix: align hardware inventory with live Orange Pi"
```

If no corrections are needed, record the live command and evidence in the execution ledger without creating an empty commit.
