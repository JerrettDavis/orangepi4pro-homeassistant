# Household dashboards

The Lights, Desktops, Vehicle leases and Home Operations dashboards are
generated from `scripts/dashboard_defs/` and stored as Lovelace storage-mode
dashboards in Home Assistant. Built output is committed in
`homeassistant/dashboards/storage/`.

Required frontend plugins (already installed from HACS): Mushroom, button-card.

```bash
python scripts/dashboards.py build              # regenerate the committed JSON
HOMEASSISTANT_URL=http://ha-host:8123 HOMEASSISTANT_TOKEN=... \
  python scripts/dashboards.py deploy [lights desktops vehicles home-operations]
```

`deploy` saves each live dashboard to `.local/dashboard-backups/` first
(git-ignored), creates a dashboard that does not exist, then saves the new
config. To roll back, save the backup JSON with `lovelace/config/save`.

## Lights

One tile per physical fixture, grouped by room. Govee strips expose a cloud
entity, a duplicate MQTT entity and up to 30 segment entities; SmartThings,
TP-Link and Tuya duplicate the same switches and bulbs. Only the canonical
entity is shown. Wall switches that feed smart bulbs (HS200/HS220 → Govee
bulbs) are drawn above their bulbs, with the "off at the wall" state called
out. The Device map tab lists what is shown and what is left out. The entity
registry is not modified; hide or disable the duplicates there if desired.
