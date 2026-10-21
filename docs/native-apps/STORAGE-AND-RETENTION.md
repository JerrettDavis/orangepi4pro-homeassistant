# Storage layout and retention (Orange Pi cyberdeck appliance)

Observed on the live appliance (2026-10-21): the 49 GB root filesystem was 98 % full. The largest consumers were the Home Assistant recorder database (~11.7 GB) and HA automatic backups (~11.8 GB, five archives) under `/srv/homeassistant/ha`, followed by Docker/containerd (~9 GB) and old disabled snap revisions (~1.1 GB). The NVMe has separate partitions for the cyberdeck HOME (`/srv/cyberdeck-home`, ~30 GB free) and an image cache; they are left intact.

## What this integration changes

| Item | Where | Reversal |
|---|---|---|
| App state, jobs, rollbacks, app data | `/srv/orangepi-apps` is a bind mount of `<HOME partition>/opiha/apps` (`nofail`, requires the HOME mount) | Remove the one marked line from `/etc/fstab`, `umount`, copy data back |
| sysstat retention | `HISTORY=5`, `COMPRESSAFTER=1` in `/etc/sysstat/sysstat` (the 47 MB zram `/var/log` was 92 % full of sysstat files) | Restore the saved copy |
| Container logs for apps | Docker `json-file`, 5 MB × 2 per app, set at container creation | n/a |
| Existing HA/proxy containers | Already capped at 10 MB × 3 | unchanged |

The manager refuses app operations when the state filesystem has less than 2 GiB free and keeps 2 GiB of memory outside the sum of app ceilings.

## Moving HA automatic backups off the root filesystem (needs explicit approval)

Copy `/srv/homeassistant/ha/backups` to `<HOME>/opiha/ha-backups`, verify every archive with `sha256sum -c`, then only after that delete the originals and add a bind mount for `/srv/homeassistant/ha/backups`:

```
<HOME>/opiha/ha-backups /srv/homeassistant/ha/backups none bind,nofail,x-systemd.requires-mounts-for=<HOME> 0 0
```

Restart HA through the existing control (`opiha-admin restart`) so the container sees the mount. Deleting the originals is irreversible and is deliberately left to an administrator decision.

## Recorder audit (core data keeps maximum retention)

A one-hour sample of the 54 000 state rows written per hour showed ~40 000 (≈ 75 %) came from twelve OPNsense gateway throughput sensors updating about once per second (`sensor.*_interface_*_inbytes/outbytes/inpkts/outpkts_*`). They are metrics, not core household data. Options, in order of preference:

1. Lengthen that integration's polling interval (no loss of core data).
2. Add those entities to `recorder: exclude:` (note this also stops their long-term statistics).
3. Keep `purge_keep_days` for everything else unchanged; do not shorten retention of core entities.

No recorder setting was changed by this work. Separately, `configuration.yaml` contains two top-level `homeassistant:` keys; YAML keeps only the last, so `media_dirs` is ignored. That predates this change and was left untouched.
