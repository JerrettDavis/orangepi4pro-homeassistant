# Home Assistant add-ons without the Supervisor

The Orange Pi panel has an **Add-ons** tab that installs packages from Home Assistant add-on repositories
(the same `config.yaml` / `build.yaml` / `Dockerfile` format the Supervisor reads). It does **not** run the
Supervisor, which is unsupported on a Container install. It reproduces what an add-on needs from it.

Design and reasoning: `docs/superpowers/specs/2026-10-23-addon-support-design.md`.

## What works

| Supervisor feature | Here |
|---|---|
| Repositories | Add any `https://` git repository. Suggested: official add-ons, Community Hass.io Add-ons, ESPHome, Zigbee2MQTT. Shallow clone, no submodules, no hooks, refreshed only when you ask. |
| Manifest parsing | `config.yaml/yml/json`; both the old (`addon_config`, `addons`) and new (`app_config`, `local_apps`) map names. Checked on all 24 official add-ons on the Orange Pi: 14 work, 7 run with reduced capability, 2 are refused (host D-Bus / Docker API). |
| Images | `image:` add-ons are pulled for `linux/arm64` and locked to their digest. Add-ons with only a `Dockerfile` are built on the device with `BUILD_FROM`/`BUILD_ARCH` (needs 4 GiB free). |
| `/data/options.json` | Written from the options form; validated against the add-on `schema` (`str`, `int(a,b)`, `bool`, `list(a|b)`, `match(re)`, `email`, `url`, `port`, `password`, nested lists/dicts, `?` optional). |
| Directory maps | `/share`, `/media`, `/ssl`, `/backup`, `/addons`, add-on config, and Home Assistant's config directory (`/homeassistant`, or the path the add-on asks for). |
| Ports | Published to `127.0.0.1` only, unless you tick "reachable from my LAN". |
| `http://supervisor/` | A shim on the add-on network answers `addons/self/{info,options,options/config,options/validate,stats}`, `info`, `core/info`, `host/info`, `supervisor/info`, `network/info`, `services/{mqtt,mysql}` (publish and read) and `core/api/...` (proxied to Home Assistant). Each add-on has its own `SUPERVISOR_TOKEN`. |
| Add-on to add-on names | Each add-on gets the Supervisor's hostname (`core-mosquitto`, `<hash>-<slug>`), so existing configs that point at those names keep working. |
| Ingress | Add-ons that declare `ingress` open inside the panel through the same admin-only proxy as the reviewed apps. The mount prefix is stripped and `X-Ingress-Path` is supplied. Add-ons that allow only `172.30.32.2` work because the host side of the add-on bridge *is* `172.30.32.2`. Dynamic ingress ports (`ingress_port: 0`) are supported. |
| Lifecycle | Install, start, stop, restart, configure, update and remove use the same plan, approval, journal and rollback flow as the reviewed apps. A failed update restores the previous image, manifest and data. |
| Backup | `opiha-apps backup` includes add-on records, data and tokens (it is private state; encrypt it). Cloned repositories and the shared `/share`, `/media`, `/ssl` folders are not included. |

## What does not, and what is said instead

* **`/discovery`** returns an explicit error: it needs the Supervisor integration inside Home Assistant.
  Add-ons that announce themselves (Mosquitto) still run and publish their MQTT service; add the integration in HA by hand.
* **`/core/websocket`** is not implemented (501). Add-ons that need it (Node-RED community add-on, AppDaemon) will not fully work.
* No HAOS, host D-Bus, host audio, AppArmor profiles, Supervisor backups or add-on store auto-updates.
* Add-ons that need the host D-Bus, host PID namespace, Docker API or an architecture other than aarch64 are marked
  **Unsupported** and cannot be installed. Everything else is **Works** or **Reduced**, with the reasons shown first.
* Every request to an endpoint the shim does not implement is recorded in `shim-unimplemented.json` in the state
  directory, so gaps are visible rather than guessed.

## Trust

Repositories are executable code you chose to run. Nothing is granted implicitly:

* Anything beyond a plain container (`host_network`, `full_access`, extra capabilities, devices, write access to
  Home Assistant's config/ssl/backup/addons folders, Home Assistant API use) is listed and each item must be ticked
  before a plan can be reviewed. Without the grant the install is refused server-side too.
* The plan is bound to the exact source: if the repository changes between planning and approval, the job refuses.
* Containers run as root inside Docker with Docker's default capability set (minus `NET_RAW`), `no-new-privileges`
  and memory/PID limits, on their own bridge (`opiha-addons`, 172.30.32.0/23). They can reach your LAN.
* An installed add-on never starts by itself until you start it once.

## Home Assistant API access

`core/api` requests need a long-lived access token (Profile → Security). Paste it into **Add-ons → Home Assistant
access**; it is stored in the manager's private state directory and used only for add-ons that declare
`homeassistant_api`. Without it those requests get a clear 503.

## Host networking detail

The reverse proxy on the host owns port 80, so the shim listens on `172.30.32.2:8180` and an iptables rule
(`nat PREROUTING -i opihaadd0 -d 172.30.32.2 --dport 80 -j REDIRECT --to-ports 8180`) is installed and re-checked
every 30 seconds by the manager. It touches only traffic from the add-on bridge to that address.

## Command line

```
opiha-apps repo add https://github.com/home-assistant/addons
opiha-apps repo addons <repo-id>
opiha-apps addon <repo-id> <folder> --options-file opts.json            # plan only
opiha-apps addon <repo-id> <folder> --options-file opts.json --apply --confirm-network-access
opiha-apps app start|stop|restart|remove|configure <slug>
```
