# Data retention and off-box history

Goal: keep **14 days** on the Orange Pi (the live database was 3 GB at 14 days before noisy camera/image/automation states were excluded; 30 days would crowd the 49 GiB root disk) and ship everything else off-box for as long as possible, at no cost.

## Free sinks, verified (Nov 2026)
| Sink | Free allowance | Fit |
|---|---|---|
| Grafana Cloud Free | 10k series, 50 GB logs, **14-day retention** (13 months is paid) | Dashboards/alerting mirror only. Not a history store. |
| Cloudflare R2 | 10 GB-month, 1M writes, 10M reads, free egress | Encrypted restic repo for config and DB snapshots. |
| Backblaze B2 | 10 GB; egress free up to 3x stored | Second copy for the same restic repo. |
| Oracle Cloud Always Free | Ampere A1 VM + block storage (about 200 GB total, check console), 10 TB/month egress | Offsite VictoriaMetrics replica. Idle reclamation is a risk: never the only copy. |
| LAN box / Hyper-V VM at home | Disk size only | **Primary** sink; unlimited retention, local Grafana. |

InfluxDB Cloud free tier retention is also 30 days, so it does not extend history.

## Design
```
HA (30 d recorder + forever long-term statistics)
 ├─ /api/prometheus ──► vmagent (disk-buffered) ──► VictoriaMetrics LAN (primary, retention 10 y)
 │                                            └──► VictoriaMetrics Oracle (offsite replica)
 ├─ ship-state.sh config (daily) ─► restic ─► Cloudflare R2
 ├─ ship-state.sh db (weekly)    ─► restic ─► Backblaze B2 (second repo)
 └─ opiha-backup (age+signed bundle) ─► off-box mount (docs/RECOVERY.md)
```
VictoriaMetrics stores roughly 1-2 bytes/sample. Example: 3,000 series at 30 s is about 17 MB/day, about 6 GB/year, so 10 years fits easily on one disk.

## Files
- `homeassistant/packages/recorder_tuning.yaml`: 14-day purge, excludes noisy entities.
- `homeassistant/packages/telemetry_export.yaml`: Prometheus endpoint with a domain filter to cap series.
- `examples/telemetry/`: vmagent config and compose (Pi), sink compose, `ship-state.sh`.

## Rollout
1. Create an HA long-lived token for a dedicated non-admin user; save to `secrets/ha_token` (mode 0600). Verify `curl -H "Authorization: Bearer $(cat secrets/ha_token)" http://127.0.0.1:8123/api/prometheus | head`.
2. Stand up the LAN sink first, pin image tags in `.env`, put it behind TLS/auth or Tailscale. Then Oracle replica.
3. Start vmagent, confirm `ha_*` series arrive, then confirm buffering by stopping the sink for 10 minutes.
4. Create R2/B2 buckets with scoped keys, `restic init`, store the restic password in two places off-box (loss means loss of all data), run `ship-state.sh config` then `db`, and **test a restore**.
5. Track series count (`count({__name__=~"ha_.*"})`); trim `telemetry_export.yaml` if above ~8k if you also want Grafana Cloud as a mirror.

## Cautions
- Never ship secrets: exclude `secrets.yaml` and `.storage/auth*` from the config repo or accept that restic encryption is the only protection. Prefer excluding them and relying on the signed appliance bundle.
- Free-tier terms change; recheck before depending on them. Keep at least two independent copies.
