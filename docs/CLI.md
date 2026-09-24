# CLI reference

Run `./bin/opiha --help` or `./bin/opiha COMMAND --help` for exact flags. An installed host wrapper selects `/etc/opiha/appliance.json`; the repository command defaults to `.local/appliance.json`. Global `--config` goes before the subcommand.

| Command | Behavior |
|---|---|
| `init --mode lab\|appliance` | Create new empty managed state/config; refuse existing state |
| `configure` | Set explicit versions/timezone/URLs/device paths/feature switches; no implicit restart |
| `render` | Print Compose JSON; no container start |
| `up [--onboarding]` | Start HA and eligible peripherals; enforce production gate |
| `down` | Remove managed containers, preserve state |
| `activate --confirm-cutover` | Arm production startup after source shutdown |
| `deactivate` | Stop containers and disarm |
| `doctor`, `status` | Inspect prerequisites/hardware or HTTP/storage/vision observations |
| `hardware inventory [--output PATH] [--private]` | Collect public-sanitized host inventory; private output requires a path outside the repository |
| `hardware camera`, `hardware zwave`, `hardware storage` | Inspect one hardware area without changing the host |
| `host plan [--root /]` | Report the exact live-host filesystem changes; read-only |
| `host install [--root /] [--apply]` | Dry-run by default; stage a release and private layout without starting/enabling services |
| `serve`, `vision` | Run native read-only UI or optional detector |
| `lock-images --platform` | Pull, verify architecture and pin image refs to registry digests |
| `inventory [--ha-config] --output` | Private offline registry/component report |
| `compare BEFORE AFTER` | Compare identity inventories; nonzero on mismatch |
| `live-check --token-file --output` | Read HA API health/entities using a private file token |
| `sqlite-check [--database]` | Read-only quick check; prefer stopped state |
| `zwave-audit [--store]` | Report recognized key fields/lengths, not values |
| `mqtt-init [--username]` | Initialize new private loopback broker credentials |
| `backup --output --recipient` | Quiesce, hash, encrypt and restart previous services |
| `restore --bundle` | Validate/decrypt, dry-run unless `--apply`; `--replace` acknowledges replacement |
| `import-config`, `import-zwave` | Import a stopped raw directory; preserve other components |
| `repair-restore --apply --source-stopped` | Recover interrupted directory transaction; remain disarmed |
| `signing-keygen --private --public` | Generate Ed25519 keys without overwriting files |
| `vendor-hacs --version` | Fetch specific public HACS release/lock |
| `recover --media --trust-key --confirm-unattended` | Signed encrypted fresh-state appliance recovery |

`--offline --source-stopped` bypasses Docker coordination only with explicit operator attestation that all writers are already stopped. It is not safe against a running host service or remote file writer. Production `backup` does not allow plaintext output.

Version overrides are intentionally explicit. A source HA downgrade is refused; an upgrade during restore/import requires `--allow-version-change`. Prefer exact versions and separate migration from upgrades.

## Script entry points

| Script | Purpose |
|---|---|
| `scripts/test.sh` | Pytest, Bash syntax, Python compilation |
| `scripts/docker-smoke.sh` | Real blank HA container startup, HTTP response and teardown |
| `scripts/cache-images.py` | Public software-only OCI/Docker image cache |
| `scripts/load-cache.py` | Verify and install matching cached images on the target |
| `scripts/Export-HyperVConfig.ps1` | Export a genuinely available stopped HA config share |
| `scripts/scan-public.py` | Check source release allowlist for known private content patterns |
| `scripts/package.py` | Produce allowlisted ZIP/tar.gz source archives and SHA256 file |
| `image/overlay.py` | Public overlay onto mounted rootfs or explicit live host |
| `image/build-from-base.sh` | Guarded copy-and-overlay `.img` builder, dry-run by default |
| `image/scrub.py`, `image/audit-rootfs.py` | Defense-in-depth clean image sanitation and known-pattern audit |

All image apply/install commands should be reviewed before privileged execution. No script automates flashing a physical disk.
