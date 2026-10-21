# Separate HA and native-app recovery

A native Home Assistant backup, the older `opiha-state-v1` bundle and this layer's `opiha-native-apps-v1` bundle are different formats. Do not unpack one as another. This command does not replace HA's supported backup/restore UI and does not include the original Compose services.

Keep three recovery inputs: your existing HA/appliance backup, this native-app bundle, and private site configuration such as `/etc/orangepi-apps/config.json`, mount credentials and key locations. The manager token can be regenerated and linked to HA by reinstalling; do not publish it. Application options and digest pins are stored with app data, while host-specific manager paths/budgets are not automatically applied from a bundle.

## Keys outside Git

Install `age` and OpenSSL on the actual host. Store keys on private media:

```bash
install -d -m 0700 /private/opiha-keys
age-keygen -o /private/opiha-keys/identity.txt
age-keygen -y /private/opiha-keys/identity.txt
# The last command prints the PUBLIC age recipient.
openssl genpkey -algorithm ED25519 -out /private/opiha-keys/signing-private.pem
openssl pkey -in /private/opiha-keys/signing-private.pem \
  -pubout -out /private/opiha-keys/signing-public.pem
chmod 600 /private/opiha-keys/*
```

## Create an encrypted bundle

```bash
sudo python3 /opt/orangepi-apps/current/bin/opiha-apps backup \
  --output /mounted-private-backup/native-apps.tar.age \
  --recipient age1YOUR_PUBLIC_RECIPIENT \
  --signing-key /private/opiha-keys/signing-private.pem
```

Select a real mounted off-box destination and verify it is mounted before running; this command does not enforce a particular off-box mount policy. It will not overwrite an existing backup. A `.sig` file is emitted alongside the encrypted bundle when signing is requested.

Managed app restart policies are temporarily disabled, running apps stop, and their state is copied. The previously running apps are then resumed before compression/encryption completes. This creates a brief service interruption. HA itself stays running, but MQTT/radio/flow-dependent functions can be interrupted while their app stops. A snapshot/resume failure is reported, not called success.

The archive includes manager ownership identity and each app's private directory, record, settings, credentials and data. It excludes old rollback copies, job logs and the original HA/Compose data. Internal relative symlinks such as npm executables are preserved; escaping links, special files and invalid archive paths are rejected. The current bound is 64 GiB and 250,000 entries; large video archives or toolchain caches need a reviewed backup strategy.

`--plaintext` exists only for an explicitly private local rehearsal. Do not use it for an off-box household backup merely because age is absent.

## Verify and stage recovery

```bash
sudo python3 bin/opiha-apps restore \
  --bundle /private/native-apps.tar.age \
  --identity /private/opiha-keys/identity.txt \
  --signature /private/native-apps.tar.age.sig \
  --trust-key /private/opiha-keys/signing-public.pem \
  --destination /srv/orangepi-apps-recovered
```

This verifies signature, decrypts privately, validates archive/checksums and discards staging. Add `--apply` to retain the recovered state in the **new** destination. An existing destination is refused. No service is started, no running data is replaced, and no controller is reset by restore.

For real recovery, stop the old manager and all managed containers first. Preserve the old state directory. Move the validated recovered directory into the configured state path, retaining ownership identity, and start the manager. Reinstall each saved app without changing its options; this uses its recorded digest. The app remains stopped until you approve Start. This is deliberate, especially for radios. Do not run a recovered clone beside the original production services.

Restore the HA backup through its normal path. When that backup contains this panel but a fresh host lacks the native installer marker, use the matching native-app release:

```bash
sudo python3 bin/opiha-apps install-host --adopt-restored-panel --apply
```

The adoption flag accepts only byte-identical panel files from this release and regenerates the private connection. It is not a force-overwrite switch for arbitrary integrations. Validate HA and restart it once afterward. Reapply the private host settings and verify the configured state path/port/budgets.

## Update failure and rollback

A failed app replacement attempts to restore matching old data and image. Retained snapshots stay private. If an interrupted transaction remains:

```bash
sudo python3 /opt/orangepi-apps/current/bin/opiha-apps repair nodered --apply
```

Run this locally after inspecting the app and storage. It affects only the owned app. Do not delete the journal to bypass a failure. App schema migrations require old data with the old image; do not point an older image at upgraded data and hope. Controller firmware/NVM changes are separate operations outside this rollback mechanism.
