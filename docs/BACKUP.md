# Backup overview

This appliance has two intentionally separate backup paths:

- Use a native Home Assistant backup for the first migration from HAOS or
  another supervised installation. Restore it through HA's onboarding UI.
- Use the signed, age-encrypted OPIHA appliance bundle for subsequent
  appliance recovery after the household has moved here.

Do not pass a native HA backup to `opiha restore`; it is a different format.
Do not place an age identity, signing private key, or backup output anywhere
below `/srv/homeassistant`, because managed state is included in appliance
bundles. Store private recovery material on protected off-box media. The
on-device validation keys and blank-state archive used during bring-up are
temporary test artifacts, not the household recovery set.

The live Orange Pi has passed creation, detached Ed25519 signing, age
encryption, signature verification, decryption, archive validation, service
quiescing, and HA restart using blank state. An actual applied household
restore remains pending.

See [Recovery](RECOVERY.md) for commands, storage rules, restore staging,
rollback behavior, and scheduled off-box backups. See
[Migration](MIGRATION.md) for the native HA backup path.
