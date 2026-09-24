# Flashing safety gate

No flash has been performed on the live Orange Pi. Its NVMe disk owns the
working root, boot, EFI, and additional valuable partitions and is never a
valid destination while that system is running. The mounted SD card is also
not considered disposable until its owner and recovery purpose are proven.

The current release builds an appliance overlay from an explicitly supplied
clean base image. It does not yet ship a dedicated `opiha image flash` command.
Do not substitute an unguarded `dd` command and call that implemented.

Before any future writer is allowed to run, capture and compare:

```bash
findmnt /
findmnt /boot
lsblk -o NAME,PATH,SIZE,TYPE,FSTYPE,LABEL,UUID,MOUNTPOINTS,MODEL,SERIAL
```

The implementation must reject the parent disk of `/`, the parent disk of
`/boot`, every mounted destination, non-block devices, and destinations smaller
than the image. A dry run must show the resolved path, model, size, mount state,
image size, and image SHA-256 without opening the destination for writing.

After a future approved write, flush buffers, reread the partition table,
verify filesystem signatures, mount expected filesystems read-only, and confirm
the appliance release, kernel, DTB, and boot configuration are present. Retain
the source image checksum and a written-data verification result.

There is intentionally no copy-paste flash command in this document yet. A
safe spare target has not been positively identified, and the guarded flash
subcommand remains unimplemented. See [Image build](IMAGE-BUILD.md) for the
non-destructive regular-file build workflow.
