# Backups and recovery

## Keep formats separate

| File | Meaning | Restore path |
|---|---|---|
| Native Home Assistant backup | HA's backup format, possibly encrypted with HA's backup key | HA onboarding/backup UI |
| `state.tar.age` | This repository's encrypted `opiha-state-v1` archive | `opiha restore` or signed first-boot recovery |
| `state.tar.age.sig` | Detached Ed25519 signature of a domain-separated SHA256 digest of the encrypted archive | Verified using a public trust key |
| `identity.txt` | Private age decryption identity | Separate private recovery medium, never public image/Git |

The archive manifest contains per-file sizes and SHA256 hashes. Extraction rejects path traversal, links, duplicate/unlisted entries and size-limit violations. Encryption protects confidentiality; a signature provides sender authentication. Hashes inside an unsigned archive alone do not prove who created it.

## Key setup

Create keys outside the repository except the public trust key:

```bash
mkdir -p /private/opiha-keys
chmod 700 /private/opiha-keys
age-keygen -o /private/opiha-keys/identity.txt
age-keygen -y /private/opiha-keys/identity.txt
# Save the printed PUBLIC recipient, beginning age1...

./bin/opiha signing-keygen \
  --private /private/opiha-keys/signing-private.pem \
  --public config/recovery-trust.pem
```

A public age recipient can be stored on the appliance to make encrypted backups; the decrypting identity need not be there. The private signing key belongs in private appliance storage or another controlled signing process, not in the image. Never copy a real identity into an example or GitHub Actions log.

## Create a consistent appliance backup

```bash
sudo opiha backup \
  --output /mounted-private-backup/state.tar.age \
  --recipient age1YOUR_ACTUAL_PUBLIC_RECIPIENT \
  --signing-key /private/opiha-keys/signing-private.pem
```

The CLI checks the managed state directory, removes running Compose containers to prevent Docker restart policies from restarting writers during a snapshot, pauses active kiosk/vision services, archives state, encrypts, signs, and restarts the previously running services. This creates a **brief service interruption**. It is not an online HA backup implementation. HA's own scheduled backups can complement it.

A snapshot covers:

```text
ha/       Complete /config, including registries, auth, HACS and recorder files
zwave/    Z-Wave JS UI persistent store
mqtt/     Local broker config/password hashes/data
camera/   Private go2rtc configuration
ssl/      Local /ssl material
media/    Files actually stored in the managed media directory
share/    Files actually stored in the managed share directory
private/  Generated credentials and explicitly placed private appliance material
kiosk/    Persistent browser profile (minus ephemeral locks/caches)
```

It does not recursively follow symlinks or capture external database/NAS contents. Back up external stores with their own consistency mechanisms. Dependency/bytecode/cache directories and HA logs are excluded; custom components themselves are retained. Media can make archives large. The alpha limit is 128 GiB uncompressed and 200,000 files; review before using it as a video archive solution.

The bundle contains portable service settings, not host paths or its production activation marker. It does not include arbitrary `/etc` policy, Wi-Fi settings, fstab, external SSH keys, a reverse proxy, the system browser keyring or `/etc/opiha/backup.json`. Those must be declared in your separate private site-provisioning process. This alpha intentionally does not restore untrusted arbitrary OS configuration as root.

## Manual restore: verify before commit

```bash
sudo opiha restore \
  --bundle /private/state.tar.age \
  --identity /private/opiha-keys/identity.txt \
  --signature /private/state.tar.age.sig \
  --trust-key /etc/opiha/recovery-trust.pem
```

This decrypts/validates in private temporary storage without replacing state. For the actual restore:

```bash
sudo opiha restore \
  --bundle /private/state.tar.age \
  --identity /private/opiha-keys/identity.txt \
  --signature /private/state.tar.age.sig \
  --trust-key /etc/opiha/recovery-trust.pem \
  --apply --replace --apply-settings
```

The target's mode and host directories are never imported from the archive. A lab stays quarantined and loses optional hardware feature enablement. Version checks reject downgrades and normally require the same HA version. `--allow-version-change` permits an explicitly approved upgrade, not a downgrade. Imported state stays disarmed and containers stopped.

Atomic replacement retains the previous state beside the current directory as `*.rollback-TIMESTAMP`. Reserve enough free storage for encrypted input, decrypted staging, current state and rollback. Protect the rollback as sensitive data. It does not automatically expire in this alpha.

If a filesystem failure interrupts replacement, startup refuses while the restore journal exists. After independently ensuring all writers are stopped:

```bash
sudo opiha repair-restore --apply --source-stopped
```

This restores the prior directory when possible and leaves production disarmed. It does not recover a corrupted disk or restore an external database. Review logs/state before reactivation.

## Signed USB first-boot recovery

The public image must contain the corresponding `recovery-trust.pem`. Prepare a private removable filesystem labeled **OPIHA_RECOVERY**, containing exactly the selected recovery inputs:

```text
state.tar.age
state.tar.age.sig
identity.txt
```

Choose the current signed backup explicitly. This alpha verifies signatures but does not implement an anti-replay counter or automatically select the newest archive from a backup catalog.

Stop the old production HA and Z-Wave server. Flash the reviewed clean-base appliance image to the intended media using your existing known-good flashing procedure. Insert the private recovery USB and existing controller, then boot. First boot mounts that label read-only with `nosuid,nodev,noexec`, verifies the signature before decryption, validates the archive/version, restores portable settings, and arms startup on **empty fresh state only**. It never silently replaces an already configured household.

A cached image must match the restored software versions. Device paths and camera mode still need to match the same hardware. The image does not magically make an unsupported camera or browser work. Network connectivity should initially be supplied by wired DHCP; private Wi-Fi provisioning is not implemented in this release.

Remove and protect recovery media after success. **Putting the private identity and encrypted archive on the same USB removes confidentiality against someone who steals that USB.** It only separates secrets from the public image. For stronger protection, use manual recovery with a separately held identity or implement an authenticated external key-retrieval mechanism. No private key is copied into the public image by these scripts.

## Scheduled off-box backups

Create a root-owned, mode-0600 `/etc/opiha/backup.json` using `examples/backup-policy.example.json` as the shape. Replace every placeholder. The mountpoint must be an actual mounted off-box destination; the script refuses to silently fall back to the local disk when it is absent.

```bash
sudo systemctl start opiha-backup.service
# Check the produced encrypted archive and rehearse its restore first.
sudo systemctl enable --now opiha-backup.timer
```

The timer runs around 03:30 with randomized delay. The example is not pre-enabled because the repository cannot know your off-box mount or recipient. Mount credentials and this policy are outside the appliance bundle in this alpha. No automatic pruning is performed: set a tested retention policy that cannot delete the only working recovery point.

## Safe upgrade and rollback rule

Take a matched software-version/state recovery point before changing HA or Z-Wave versions. Keep the previous software cache/image with that backup. Rolling back only the image after a schema migration can be unsafe. Restore the matching pre-upgrade state as well. An NVM/controller firmware change is a separate operation with its own rollback plan.
