# Setup review and recommendations

Scope: this review covers the repository's Home Assistant configuration (packages, dashboards, the `opiha_apps` custom component, docs). Live entity state was not reachable from the review environment, so entity-level advice is derived from what the packages reference. Web sources were treated as untrusted data: only widely documented practices (official HA docs, the community `homeassistant-ai/skills` best-practices guide) were used, and no third-party scripts were run or installed.

## Current inventory (from config)
- Infra: gateway, two DCs, WAN, TP-Link switch (ping), 3 UniFi APs; OPNsense work in progress.
- Vehicles: Ioniq 5 N (kia_uvo), Dodge Charger EV (uconnect); Wallbox Pulsar Plus.
- People/notify: person.jd, person.sam, two mobile_app notifiers.
- Appliance: vision person sensor, free storage, disk guard, nightly auto-updates (hassio + hacs), custom Apps panel, 4 storage dashboards.
- Pending: Z-Wave stick migration, Tuya reauth, camera validation.

## Applied in this change
- `packages/recorder_tuning.yaml`: 14-day local retention, noisy-entity excludes (camera/image/HomeOps automation states, printer and light mirrors).
- `packages/logger_tuning.yaml`: silences Meshtastic, Cync, Roomba, Moonraker, Music Assistant and Waze retry spam (thousands of identical lines per day).
- `packages/notifications.yaml`, `packages/backup_health.yaml`: deployed to the live host.
- `packages/telemetry_export.yaml` + `examples/telemetry/`: off-box long-term history. See [DATA-RETENTION.md](DATA-RETENTION.md).

## Recommended next steps (ordered by value / effort)
1. **Notification fan-out**: replace the hard-coded `notify.mobile_app_*` lists in four packages with one `notify.group` (or a script) so adding a phone is a one-line change.
2. **Backup health**: alert when the last successful backup is >36 h old (sensor `sensor.backup_last_successful_automatic_backup`) and copy encrypted backups off-box (NAS/cloud). Test a restore quarterly (see `docs/BACKUP.md`).
3. **Auto-update safety**: the nightly updater restarts Core unattended. Consider limiting it to a monthly Core cadence (hold Core for ~1 week after release) and keeping the pre-update backup.
4. **Charger/EV**: use Wallbox smart charging with off-peak tariff schedule; add a "plugged in but not charging" and "charge complete" notification; add `input_datetime` for a ready-by time.
5. **Presence**: combine phone trackers with UniFi device trackers (`person` multi-source) to reduce false away states; use Bermuda/BLE room presence later only if needed.
6. **Network observability**: add UniFi client-count and WAN throughput sensors (or SNMP from OPNsense) and an AdGuard/Pi-hole blocked-percent sensor; alert on DC replication/DNS failures via a `dns`/`ping` check, not only ICMP.
7. **Security hardening**: already has TOTP, ip_ban. Add a login-failure notification (`persistent_notification` trigger / `http` ban events), keep HA off WAN (use Tailscale/Nabu Casa), and pin HACS integrations after review.
8. **Camera/vision**: once the camera works, add Frigate-style zones/events or a person-detected automation (lights/kiosk wake) using `binary_sensor.orange_pi_person`; a Coral/NPU path is optional.
9. **Lighting**: Adaptive Lighting (HACS) and motion/occupancy scenes for the `lights` dashboard; use purpose-specific triggers/conditions (2026.7+) instead of template triggers where available.
10. **Hygiene**: use Watchman to find dead entity references; migrate any `device_id` usage to `entity_id`; convert repeated templates into blueprints; keep a `git` copy of YAML (already done) in addition to full backups.
11. **Kiosk**: dim/blank the display via `binary_sensor.orange_pi_person` plus a night schedule to extend panel life.

## Cautions
- Do not install HACS items without checking maintainers, stars and recent commits; avoid scripts that pipe `curl` to a shell.
- Prefer pinned versions; auto-updating custom integrations is the highest-risk part of the nightly job.
