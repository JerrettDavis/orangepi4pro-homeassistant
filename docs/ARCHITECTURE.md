# Architecture and operational contract

## Separate code from household state

Public code is installed under `/opt/orangepi4pro-homeassistant`. Public defaults and a public signature-verification key may live under `/etc/opiha`. The real `/etc/opiha/appliance.json` is created on the target, not shipped in the image. Household component directories live under `/srv/opiha`, operational journals/activation markers under `/var/lib/opiha`, and read-only service observations under `/run/opiha`.

The overlay allowlists public directories. It does not copy `.local`, `.git`, tests, reports, private key files or a live HA config from the development workstation. Source release packaging uses a separate explicit allowlist. These are guardrails, not proof that arbitrary new source files cannot contain a secret; review additions before publishing.

A complete household backup is private even after tokens are encrypted: filenames, entity identifiers, media, log fragments and device IDs reveal information. Inventory strips integration data/token fields but remains private operational metadata.

## Runtime configuration

`opiha init` creates validated JSON with explicit HA/versioned image refs, directories, feature flags and camera/vision settings. Production paths and mode are never adopted from a restored portable manifest. Configuration changes do not restart services implicitly. `systemctl restart opiha-stack` republishes sanitized settings and starts HA first, then enabled peripherals.

Compose is emitted as JSON, a YAML subset. The explicit empty env file avoids loading an unrelated working-directory `.env`. Unsafe interpolation/control characters are rejected in managed paths and hardware device paths. No whole-host privileged container, Docker socket mount or blanket `/dev` passthrough is used.

| Service | Exposure | Persistence |
|---|---|---|
| HA lab | no host port; internal Docker network | private lab `state/ha` |
| HA appliance | host network, normally port 8123 | `/srv/opiha/ha`, `ssl`, `media`, `share` |
| Z-Wave UI | loopback 8091 and 3000 | stopped/imported JS UI store |
| MQTT | loopback 1883, authenticated | local broker config and data |
| go2rtc | loopback 1984 / 8554 | private camera config |
| status | native loopback 8099, GET only | ephemeral aggregate JSON |
| vision | native RTSP client, no listener | ephemeral person metadata |
| kiosk | native unprivileged browser | private persistent profile |

Loopback protects against ordinary LAN access, not against another privileged process on the host. A local browser session is a home-control capability. Use a dedicated account and consider physical access, SSH policy and host patching.

## State transitions

```text
new image → private directories → optional signed recovery → cache validation
     └→ fresh HA onboarding                          └→ armed recovered state
          ↓ one-time setup/cutover                              ↓
     explicit activation ──────────────────────────────→ start HA
                                                            ↓
                                                   optional peripherals
                                                            ↓
                                                    status / kiosk / vision
```

Normal manual restore and raw import always remove the production activation marker. `up --onboarding` is only allowed on new unauthenticated non-restored state. Signed unattended recovery is a deliberate exception, gated by a baked public trust key, empty state and explicit configured removable-media discovery.

The implementation does not stop a remote HA VM, remote Z-Wave service, or external database for you. Operator confirmation is not proof of remote shutdown. The cutover checklist is therefore part of the safety contract.

## Snapshot and replacement semantics

The backup lock serializes CLI mutations. Snapshot creation pauses local native state writers and removes Compose containers so a daemon restart policy cannot revive a writer. It preserves the set of previously running services and restarts them after the snapshot operation. Docker operations are mocked in unit tests and need a real-host acceptance test.

Restore verifies outside the active tree, then renames current state to a retained rollback directory and stages the new directory into place with a journal. It does not merge registries into a live HA process. Repair refuses normal startup while the transaction is unfinished. Filesystem failure, disk loss, interrupted external database operations and controller firmware are outside this directory-level transaction.

## Why no Supervisor or HAOS port

The supported managed-Linux route is HA Container. Local host GUI/camera services fit that division. HAOS is an appliance OS with a different ownership model, and this code does not claim an official A733 HAOS port. HA Container has no Supervisor apps; functions such as MQTT or Z-Wave JS are separate services with their own backups and versions.

See [upstream sources](SOURCES.md) for the externally verified API and support assumptions. No upstream dependency releases were bundled into this source archive or tested against a real ARM64 Docker daemon in the delivery environment.
