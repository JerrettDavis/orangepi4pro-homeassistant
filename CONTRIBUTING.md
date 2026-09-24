# Contributing

Use Python 3.10+ and `pip install -e '.[test]'`. Run `scripts/test.sh`, `scripts/scan-public.py` and, when Docker is available, `scripts/docker-smoke.sh`. Changes to restore or image logic need negative tests and a documented rollback case.

Keep application code stdlib-only except optional runtime OpenCV. Do not add unconditional downloads, floating container tags, plaintext production backups, fabricated HA/HACS state files, controller-reset commands or implicit production activation. Preserve the lab isolation boundary and never overwrite restored HA configuration with seed YAML.

Tests use synthetic household labels and placeholder strings only. `.local`, `.build`, caches, `.env`, backups, identities and real inventories must remain untracked. No private data should be used as a fixture. New public source paths require an explicit update to the release/overlay allowlist and review of what they can copy.

When adding an NPU backend, identify exact SDK/driver versions and licenses, and include a correctness/performance benchmark on the actual A733. Keep CPU fallback and never treat device-file existence as proof of functioning inference.

Upstream commands and schemas must be verified against official documentation/source. Do not assume the generic image repository exposes a hook merely because a proposed plan mentions one.
