# Research log (Nov 2026)

Method: web searches summarized by a search tool; page contents were treated as untrusted data, no scripts were run or installed. Prices and limits change, so recheck before depending on them. Entity-level advice is derived from repo config only (no live HA access).

## Findings and sources
| Topic | Finding | Source |
|---|---|---|
| Grafana Cloud Free | All free-tier telemetry has 14-day retention; 13-month metrics retention is on the paid plan. Mirror only. | https://grafana.com/products/cloud/free-tier/ |
| Cloudflare R2 | Free: 10 GB-month Standard storage, 1M Class A, 10M Class B ops, free egress. Free tier excludes Infrequent Access. | https://developers.cloudflare.com/r2/pricing/ |
| Oracle Always Free | Always-Free VM/DB/network resources for the life of the account, 10 TB/month outbound. Check the console for exact Ampere/storage limits; idle instances can be reclaimed. | https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm |
| VictoriaMetrics | Prometheus-compatible, ~1-2 bytes/sample, years of retention on one node, ships vmagent (disk-buffered remote write) and needs vmalert for alerting. | https://www.bigiron.cc/guides/time-series-databases-influxdb-vs-victoriametrics-vs-questdb |
| HA best practices | Prefer native constructs over templates, entity_id over device_id, helpers over hard-coded values, a recovery path before changes, and a git config repo does not replace full backups. | https://github.com/homeassistant-ai/skills/blob/main/skills/home-assistant-best-practices/SKILL.md |
| Backblaze B2 / InfluxDB Cloud free | 10 GB free storage (B2); 30-day retention (InfluxDB free). Not re-verified this round. | recalled, verify |

## Decisions
- Local recorder: 14 days. Off-box history: self-hosted VictoriaMetrics (LAN primary, Oracle replica) plus restic to R2/B2. See [DATA-RETENTION.md](DATA-RETENTION.md).
- Free hosted metrics (Grafana Cloud) is not a history store; use only as an optional dashboard mirror.

## Implemented
- `packages/recorder_tuning.yaml`, `packages/telemetry_export.yaml`, `examples/telemetry/*`
- `packages/notifications.yaml` (`notify.household` group), `packages/backup_health.yaml` (stale-backup alert)

## Backlog
See [RECOMMENDATIONS.md](RECOMMENDATIONS.md).
