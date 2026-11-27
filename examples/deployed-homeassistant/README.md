# Deployed configuration recovery snapshot

Captured from the running Pi on November 27, 2026. These are **reviewable
recovery inputs**, not a second automatically applied seed. They preserve
the deployed automations, scripts, scenes, MQTT definitions, packages,
ESPHome firmware configurations, dashboard layouts/resources and add-on
options. Existing seed defaults remain under `homeassistant/`.

The exporter replaces inline credential fields with named `!secret`
references, preserves existing `!secret`/`!include` tags, and never exports
`secrets.yaml`. Restore the original values privately under the replacement
names before using these files. Each ESPHome device needs its own private
API encryption key and OTA/AP passwords. Webhook IDs are credentials too.
Add-on option YAML is a template: Supervisor does not resolve HA `!secret`
tags, so provision any replacements privately through its supported UI/API.

Restore a verified full Supervisor backup first whenever possible. Do not
replace a restored config with this snapshot, duplicate its automations, or
edit live HA `.storage` files. Dashboard YAML here represents the data from
storage-mode dashboards; import their `config` through the dashboard raw
editor, and register resources/dashboards through the UI/API. Integration
entries, account links, users, certificates and keys require private backups.
Entity IDs and device IDs must match the restored registries or be remapped.

The snapshot intentionally reflects the deployed configuration, not every
proposed local change: for example, the seed's explicit MFA/IP-ban block was
not present in the running configuration at audit time. Review
`docs/HA-AUTH-HARDENING.md` and `docs/AUTHENTIK-SSO.md` before changing auth.

Refresh from an offline private capture, never from an unfiltered home
directory:

```powershell
python scripts\export-deployed-yaml.py --source PRIVATE_CAPTURE --destination NEW_REVIEW_DIRECTORY
```

The exporter requires PyYAML (the existing test extra). Review all output:
field-name redaction is not proof that arbitrary embedded secrets are absent.
The checked-in export was also compared against captured credential values.
No telemetry sink was deployed; the uncommitted telemetry proposal is not
part of this recovery snapshot.
