# Security and data handling

This alpha controls household state and can ultimately control physical devices. Test it on non-production state and spare media first. There is no claim of independent security review or formal verification.

## Boundaries

Public source/images contain no real HA configuration, integration tokens, Z-Wave network keys, Wi-Fi credentials, personal network addresses or private signing/decryption keys. All examples use placeholders. Real config, inventories, archives, media, logs, browser profiles and rollback trees remain private even when an inventory does not print token fields.

Production snapshots require age encryption. Signed unattended recovery additionally requires a public key baked into the image and verifies before decrypting. It only applies to empty state. Manual restore is dry-run by default and retains prior state. Signatures do not provide freshness/anti-replay; operators choose the recovery point.

An encrypted archive and its private key on one USB are readable together by anyone who obtains that USB. That arrangement is convenient recovery media, not protection against physical theft. Store keys separately when that threat matters.

The overlay/source packager use allowlists; image scrubbing only removes known paths. Never publish a used-disk clone or trust a pattern scanner to prove that arbitrary proprietary/private data is absent. Base images, container images, HACS/custom integrations and third-party native SDKs retain their own supply-chain and licensing risks.

Admin endpoints are loopback-only, and status is read-only. Do not expose them through an unreviewed reverse proxy. Docker socket access is root-equivalent and is not given to containers or the diagnostic service. HA Container uses the host network in appliance mode for normal discovery. Its authentication and the host/network firewall remain necessary.

The kiosk user is unprivileged at the OS level, but its HA session can perform that HA user's actions. Prefer a dedicated non-admin account. The CPU person detector is not suitable for authentication, unlocking, security alarms or safety decisions.

## Operational limitations

The CLI cannot prove a remote VM/service is stopped. Source-stop/cutover flags are operator attestations. Concurrent HA instances can duplicate actions. A restored Z-Wave store still needs the correct original controller and network keys. No script resets/re-pairs a mesh.

Backups stop local state writers briefly; interrupted processes, filesystem failures, external databases and firmware changes require their own safeguards. `--offline` is only for an already-stopped state. Do not use it to bypass errors from a live Docker daemon.

Image builders require root and a trusted input. They execute apt and Python inside a trusted base filesystem. Do not run image builds for untrusted pull requests on a privileged self-hosted runner. Clean-base attestation is required, but cannot technically establish the provenance of arbitrary inputs.

## Reporting

Do not attach backups, `.storage`, database files, radio keys or raw logs to public issues. Start with a minimal synthetic reproduction and redacted version/command output. Arrange a private disclosure channel with the repository owner before transmitting a potential secret-bearing report. No address or security service is invented here.
