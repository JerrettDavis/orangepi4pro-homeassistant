# Home Assistant add-on support without the Supervisor

Status: design, approved implicitly by the `/goal` directive to proceed without questions. Calls the author made on the owner's behalf are marked **[call]**.

## Intent

The Apps panel offers five hand-reviewed apps. The owner wants the much larger Home Assistant add-on ecosystem (the packages the Supervisor installs) on this Container-install appliance. The Supervisor itself is unsupported on third-party systems and stays out. We replicate what an add-on needs from it:

1. read an add-on repository and its manifests,
2. run the add-on's container with the options, mounts, ports and devices it declares,
3. give it the Supervisor-facing contract (`/data/options.json`, `SUPERVISOR_TOKEN`, `http://supervisor/...`, ingress),
4. show it in the panel with install, configure, start/stop, update, logs, backup.

## Goals

- Add custom repositories by git URL, plus pre-seeded official (`home-assistant/addons`) and community repos.
- Parse `config.yaml|json`, `build.yaml|json`, `repo.yaml` and report per add-on: **works**, **works with reduced capability** (named reasons) or **unsupported** (named reasons) before the user installs.
- Run `image:` add-ons by pulling the arch image; build Dockerfile-only add-ons locally when the Pi has the space.
- A Supervisor API shim covering what `bashio` and typical add-ons call: `addons/self/{info,options,options/config,stats}`, `info`, `core/info`, `host/info`, `services/{mqtt,mysql}`, `discovery`, `core/api` and `core/websocket` proxied to HA.
- Generalised ingress for any add-on declaring `ingress: true`, using `ingress_port`, `ingress_entry`, and `X-Ingress-Path`.
- Panel UI: Store (repos, search, add-on detail with capability report), Installed (reuse the existing app card), Configure (form generated from the add-on `schema`).
- Keep the existing plan, approval, journalled update, rollback and backup model. Add-ons are one more kind of managed app.

## Non-goals

- Running the real Supervisor, supervised-mode detection, HAOS update/OS control, the Supervisor's own backup format and restore UI.
- Add-ons that need AppArmor profiles, D-Bus with the host's NetworkManager/rauc/udisks, `host_dbus`, or audio through PulseAudio from the host. Reported unsupported (audio and Bluetooth may come later per-adapter).
- A "store" that installs on one click without showing privileges.

## Anti-goals (would be a failure even if it technically runs)

- A browser, or a repo's manifest, being able to hand a container arbitrary host power silently. `privileged`, `full_access`, `host_network`, `docker_api`, device passthrough and `SYS_*` capabilities are never granted by default; they appear in the plan and need a distinct confirmation for that install.
- The manager gaining a way to touch HA Core, the kiosk or the proxy (existing rule stays).
- Fabricating compatibility: an API the shim does not implement returns 404/`result: error`, not a fake success.
- Starting third-party code at install time or on host boot without explicit start (existing rule stays).

## Constraints

- Appliance: ARM64, ~5.8 GiB RAM, **~6.8 GiB free disk**. Image builds and big add-ons must pass the existing memory/disk budget; a build needs a larger free-space floor (**[call]** 4 GiB) and runs one at a time.
- Runtime dependencies: Python stdlib plus PyYAML (present on the Pi, 5.4.1; code must work on 5.x and 6.x), `git` and `docker` CLIs. Only `yaml.safe_load`.
- Existing stack: `src/opiha_apps` (manager, engine, catalog, server), HA custom component `opiha_apps` (panel, ingress), vanilla JS panel. Build on these; do not fork them.
- Security posture of `docs/native-apps/SECURITY.md` must be updated honestly: the catalog is no longer closed. The trust boundary becomes "repositories the administrator added".

## How it gets made (author's calls)

- **[call]** Add-ons are modelled as catalog entries synthesised from manifests, slug `addon-<repo8>-<slug>` truncated to the existing 32-char slug rule, so lifecycle/plan/record/backup code keeps working. The static `CATALOG` stays as "reviewed" entries and takes precedence; they are labelled **Reviewed**, add-ons **Community/Unreviewed**.
- **[call]** Repositories are cloned with `git clone --depth 1` over https only (no ssh, no `file://`, no submodules, no hooks), into `data_dir/repos/<sha8-of-url>/`, refreshed only on explicit user action.
- **[call]** The Supervisor shim is a separate small HTTP listener inside the manager process, bound to the docker bridge gateway IP and addressed as `supervisor` via `--add-host supervisor:<gateway>` on every add-on container. Each add-on gets its own random `SUPERVISOR_TOKEN`; the shim maps token→add-on and exposes only that add-on's own data. HA access (`core/api`) uses a long-lived HA token the admin supplies once; absent it, those calls return an explicit error.
- **[call]** Reuse the HA ingress proxy by generalising its adapter table from fixed apps to a manifest-derived one (port, entry path, strip prefix, `X-Ingress-Path`). No HTML rewriting engine.
- **[call]** Options from the schema are validated server-side with the Supervisor's schema grammar subset (`str`, `int`, `float`, `bool`, `email`, `url`, `port`, `password`, `list(a|b)`, `match(re)`, nested dict/list, trailing `?` optional, ranges `int(1,10)`) and written to `/data/options.json`.

## Compatibility mapping (manifest field → behaviour)

| Field | Behaviour |
|---|---|
| `image` (`{arch}`) | pull `linux/arm64`, lock to digest |
| no `image`, `Dockerfile`, `build.yaml` | `docker build` with `BUILD_FROM`, `BUILD_ARCH`, `BUILD_VERSION`; size/time gate; unsupported if base images absent |
| `arch` | must include `aarch64` |
| `map: config/ssl/share/media/addons/backup/homeassistant_config/all_addon_configs` + `:rw/:ro` | bind mounts under managed dirs; `config`→`/config` is HA's config dir read/write per mode (explicit in plan) |
| `ports`, `ports_description` | loopback publish only unless admin opts a port onto the LAN (shown in plan) |
| `host_network` | unsupported by default; opt-in per install |
| `devices`, `uart`, `usb`, `gpio` | only `/dev/serial/by-id` and explicit admin-chosen devices |
| `privileged`, `full_access`, `docker_api`, `kernel_modules` | opt-in per install, shown as high-risk |
| `homeassistant_api`, `hassio_api`, `hassio_role` | shim; role `default/homeassistant/manager/admin` governs the endpoints exposed |
| `ingress`, `ingress_port`, `ingress_entry`, `panel_*` | generalised ingress and panel link |
| `services` / `discovery` | `mqtt` resolved from the managed Mosquitto if installed; else error |
| `boot`, `startup`, `watchdog`, `init`, `stage`, `apparmor`, `options`, `schema`, `environment`, `tmpfs`, `timeout` | honoured where meaningful; AppArmor ignored with a warning |

## Phases

1. Manifest parser, capability report, schema validation, repo store. (pure code, fully unit-tested)
2. Runtime: spec translation, `/data` + options.json, build/pull, journalled install through the existing manager.
3. Supervisor shim.
4. Ingress generalisation.
5. Panel Store UI, docs, security doc, CHANGELOG, version bump.
6. Live validation on the Pi with a small, real add-on set (e.g. Mosquitto broker add-on, File editor, Samba/SSH if they pass the report) and honest reporting of what does not work.

## Left to the builder

Exact JSON shapes for new API routes, UI layout details, test fixtures (use real manifests from `home-assistant/addons` as fixtures), and the order of phases 3–4 if a blocker appears.

## Risks

- Disk (6.8 GiB free) limits builds; mitigated by the floor and by preferring `image:` add-ons.
- Upstream add-ons assume Supervisor behaviours we do not implement; the report must say so up front rather than failing at runtime.
- Third-party repos are executable code: the plan screen and docs say so plainly.
