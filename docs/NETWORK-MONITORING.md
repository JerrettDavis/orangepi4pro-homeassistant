# Critical infrastructure monitoring

Package: `homeassistant/packages/network_monitor.yaml` (automation
`infra_critical_alerts` + `input_boolean.infra_alert_self_test`).
Dashboard: `/dashboard-network/0` (storage mode; cards below were added to the top of the view).

## What is watched (from HA's vantage point)

| Target | Source entity | Down when |
|---|---|---|
| Gateway JDH-GATEWAY-00 (10.0.0.1) | `binary_sensor.10_0_0_1` (Ping) | off for 2 min |
| jdh-dc-00 (10.0.0.100) | `binary_sensor.10_0_0_100` (Ping) | off for 2 min |
| jdh-dc-01 (10.0.0.101) | `binary_sensor.10_0_0_101` (Ping) | off for 2 min |
| Internet (1.1.1.1) | `binary_sensor.1_1_1_1` (Ping) | off for 2 min, only while gateway is up |
| Switch TP-Link (10.0.0.41) | `binary_sensor.10_0_0_41` (Ping) | off for 2 min |
| AP-00/01/02 (10.0.0.240-242) | `device_tracker.jdh_ap_0x` (UniFi) | not_home for 2 min |

Ping entries are UI config entries (Settings > Integrations > Ping), friendly names set in the
entity registry. RTT sensors were enabled for the four ping hosts.

**Switches:** only the TP-Link at 10.0.0.41 was discoverable (LAN web probe + MAC vendor). Any other switch is not covered. To add one:
create a Ping entry, add a `_down`/`_up` trigger pair to the automation, and a tile pair to the dashboard.

## Alerts
Down: persistent notification (local fallback) + high-priority push (`ttl: 0`, channel `infra_alerts`)
to `notify.mobile_app_jd_s23_ultra` and `notify.mobile_app_samsung_s23_ultra`.
Recovery: dismisses the notification and pushes "back after N min down".
Self-test: turn `input_boolean.infra_alert_self_test` off (alert after 2 min), on (recovery).

Limitation: a push cannot reach phones if the outage also cuts their path to HA; the persistent
notification and the red dashboard banner are the local indicators.

## Dashboard cards (added at top of view 0)
A conditional red banner (any target down), a 2-column `grid` titled "Critical Infrastructure" holding
a green `tile` / red "— DOWN" `tile` conditional pair per target, and a "Latency & Self-test" entities card.
Verified at 390x844, 844x390, 768x1024, 1920x1080 and 1024x600.
