# Home Assistant add-ons without the Supervisor

The Orange Pi panel has an **Add-ons** tab that installs packages from Home Assistant add-on repositories
(the same `config.yaml` / `build.yaml` / `Dockerfile` format the Supervisor reads). It does **not** run the
Supervisor, which is unsupported on a Container install. It reproduces what an add-on needs from it.

Design and reasoning: `docs/superpowers/specs/2026-10-23-addon-support-design.md`.

## What works

| Supervisor feature | Here |
|---|---|
| Repositories | Add any `https://` git repository. Suggested: official add-ons, Community Hass.io Add-ons, ESPHome, Zigbee2MQTT. Shallow clone, no submodules, no hooks, refreshed only when you ask. |
| Manifest parsing | `config.yaml/yml/json`; both the old (`addon_config`, `addons`) and new (`app_config`, `local_apps`) map names. Parsed on the Orange Pi: all 24 official add-ons (4 "works", 18 "reduced" with the reasons shown, 2 refused for needing the Docker API or host PID namespace; host D-Bus is an explicit grant). |
| Images | `image:` add-ons are pulled for `linux/arm64` and locked to their digest. Add-ons with only a `Dockerfile` are built on the device with `BUILD_FROM`/`BUILD_ARCH` (needs 4 GiB free). |
| `/data/options.json` | Written from the options form; validated against the add-on `schema` (`str`, `int(a,b)`, `bool`, `list(a|b)`, `match(re)`, `email`, `url`, `port`, `password`, nested lists/dicts, `?` optional). |
| Directory maps | `/share`, `/media`, `/ssl`, `/backup`, `/addons`, add-on config, and Home Assistant's config directory (`/homeassistant`, or the path the add-on asks for). |
| Ports | Published to `127.0.0.1` only, unless you tick "reachable from my LAN". |
| Audio | Add-ons that declare `audio` get the host's ALSA sound devices (`/dev/snd`, with the owning group) once you approve the "sound devices" privilege. Verified on the Pi: the Assist microphone add-on sees both sound cards, including the ES8389 capture codec. There is no PulseAudio server. |
| `http://supervisor/` | A shim on the add-on network answers `addons/self/{info,options,options/config,options/validate,stats}`, `info`, `core/info`, `host/info`, `supervisor/info`, `network/info`, `services/{mqtt,mysql}` (publish and read) and `core/api/...` (proxied to Home Assistant), `core/websocket` (a real WebSocket relay: the add-on authenticates with its own `SUPERVISOR_TOKEN`, the relay authenticates to Home Assistant with your token, and frames flow both ways) and `discovery` for MQTT and Wyoming (the service is registered through Home Assistant's own config-flow API; verified on the Pi: the Piper add-on's own announcement created a loaded Wyoming entry and a `tts.piper` entity). Each add-on has its own `SUPERVISOR_TOKEN`. |
| Add-on to add-on names | Each add-on gets the Supervisor's hostname (`core-mosquitto`, `<hash>-<slug>`), so existing configs that point at those names keep working. |
| Ingress | Add-ons that declare `ingress` open inside the panel through the same admin-only proxy as the reviewed apps. The mount prefix is stripped and `X-Ingress-Path` is supplied. Add-ons that allow only `172.30.32.2` work because the host side of the add-on bridge *is* `172.30.32.2`. Dynamic ingress ports (`ingress_port: 0`) are supported. |
| Lifecycle | Install, start, stop, restart, configure, update and remove use the same plan, approval, journal and rollback flow as the reviewed apps. A failed update restores the previous image, manifest and data. |
| Backup and restore | Per add-on, in the Add-ons tab (**Backup**, **Restore…**) or `opiha-apps app backup|restore <slug>`: the add-on is stopped, its data and options are packed into a private, hash-checked archive under `addon-backups/`, and it is started again. Restore verifies the hash, accepts only regular files under the add-on's own directories, keeps the current data as a rollback copy, and leaves the install decisions (image, ports, privileges) unchanged. Verified on the Pi with dnsmasq. `opiha-apps backup` still covers the whole manager state (it includes add-on records, data and tokens; encrypt it). Cloned repositories and the shared `/share`, `/media`, `/ssl` folders are in neither. |

## Measured on the Orange Pi

Every installable official add-on was installed and started on the device (default or plausible options), watched for
45 seconds and removed. A throwaway Home Assistant on the same host stood in for HA so the WebSocket relay and MQTT
discovery could be exercised end to end.

| Result | Add-ons |
|---|---|
| **Run steadily** (12) | File editor (ingress, REST and WebSocket through the shim), Mosquitto (HA's MQTT integration connects to it through discovery), MariaDB (publishes its MySQL service), dnsmasq (answers real DNS queries), Samba (binds the Wi-Fi interface, `smbd`/`nmbd` up), Piper, Whisper, openWakeWord, Speech-to-Phrase, Assist microphone, VLC, deCONZ (web part; no radio attached) |
| **Run and do their job, then stop** (5) | RPC shutdown (run-once by design), Let's Encrypt (needs a real domain), Git pull (needs a real repository), CEC scan and Silicon Labs flasher (no adapter attached) |
| **Need something this test could not give** (3) | nginx Proxy Manager (needs a real domain and certificate before nginx will start), Silicon Labs multiprotocol and OpenThread border router (need a radio) |
| **Not exercised** (2) | DuckDNS (rejected the placeholder domain) and Z-Wave JS (needs a controller) |
| **Refused before install** (1) | SSH & Web Terminal (Docker API). Matter Server is installable behind the host D-Bus grant (not yet run on the device). |

Of the 20 add-ons that could be started, 17 ran or completed as designed and 3 need real hardware or a real domain.
An earlier version of this table listed dnsmasq, Samba and nginx Proxy Manager as unexplained failures; those were
caused by the test harness filling optional lists and options with placeholder values, not by the shim. The run also
exposed and fixed real bugs: host-networked add-ons could not reach the API, `network/info` was empty, block-scalar
schema rules (Piper) failed to parse, TCP and UDP of the same port number were treated as a clash, `supervisor/ping`
was missing, and a shim bound to a vanished address never rebound.

After a simulated "API not ready at boot" (shim stopped, autostart add-on restarting), the add-on crash-looped and
recovered on its own when the shim came back.

## What does not, and what is said instead

* **Discovery** works for MQTT and Wyoming (Piper, Whisper, openWakeWord; needs the Home Assistant access token),
  filling Home Assistant's own form from its schema, and for Z-Wave JS, Matter Server and the OpenThread border router
  (registered by their URL; covered by unit tests, not yet run against a live controller). Other services answer 501.
* The HA WebSocket relay and REST proxy need the long-lived access token; without it they say so rather than failing silently.
* No HAOS, the Supervisor's own D-Bus services (NetworkManager, rauc; the host's system bus can be granted), a PulseAudio server (raw ALSA is provided), AppArmor profiles, the Supervisor's own backup *file format* (backups here are this project's own archives) or automatic add-on updates. The Add-ons tab does show "update X available" for an installed add-on when its (refreshed) repository offers a newer version; applying it is still a reviewed update.
* Add-ons that need the host PID namespace, Docker API or an architecture other than aarch64 are marked
  **Unsupported** and cannot be installed. Everything else is **Works** or **Reduced**, with the reasons shown first.
* Every request to an endpoint the shim does not implement is recorded in `shim-unimplemented.json` in the state
  directory, so gaps are visible rather than guessed.

## Trust

Repositories are executable code you chose to run. Nothing is granted implicitly:

* Anything beyond a plain container (`host_network`, `full_access`, extra capabilities, devices, any access to
  Home Assistant's config folder even read-only (it holds secrets), write access to ssl/backup/addons, Home Assistant API use) is listed and each item must be ticked
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
every 30 seconds by the manager. A second rule (`nat OUTPUT`, DNAT to the same port) serves add-ons that use host
networking. They touch only traffic to that one address. The listener also checks it is still reachable and rebinds if the
bridge is recreated. Peers must be on the add-on subnet or be this host itself.

## Command line

```
opiha-apps repo add https://github.com/home-assistant/addons
opiha-apps repo addons <repo-id>
opiha-apps addon <repo-id> <folder> --options-file opts.json            # plan only
opiha-apps addon <repo-id> <folder> --options-file opts.json --apply --confirm-network-access
opiha-apps app start|stop|restart|remove|configure <slug>
```
