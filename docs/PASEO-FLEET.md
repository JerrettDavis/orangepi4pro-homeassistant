# Paseo fleet: farm agent work across machines

One **hub** (your workstation) talks to a Paseo daemon on every other machine.
Everything is driven by `scripts/paseo-fleet.py` from an inventory; nothing is
hand-configured on any host.

| Host kind | Mechanism |
|---|---|
| Windows bare metal | Pinned Node + `@getpaseo/cli` under `%LOCALAPPDATA%\paseo-fleet`, Scheduled Task at logon |
| Linux / Raspberry Pi / Orange Pi | Same pinned install under `~/.local/share/paseo-fleet`, systemd **user** service (linger enabled) |
| macOS | Same install, launchd LaunchAgent |
| Docker | Official `ghcr.io/getpaseo/paseo:<version>` + pinned agent CLIs, compose project `paseo-fleet-<id>`, optional bind-mounted workspace |

Security model: every daemon listens on `127.0.0.1` only. Remote hosts are reached
through the hub's SSH client (`ssh://user@host?daemonPort=N`, key auth, no ports
opened). Docker publishes `127.0.0.1:<port>` and is password protected; the generated
password lives in `.local/paseo-fleet/secrets/<id>.password`. Node downloads are
SHA-256 verified against nodejs.org's `SHASUMS256.txt`; Paseo and agent CLI versions are
pinned in the inventory.

## Inventory

Copy `config/paseo-fleet.example.json` to `.local/paseo-fleet/inventory.json`
(gitignored: it holds real hostnames). Fields per host: `id`, `platform`
(`windows|linux|macos|docker`), `transport` (`local|ssh`), `ssh` (`user@host`),
`daemon_port`, `labels`, `workspace_root`, `workspace_mount` (docker host path bound to
`/workspace`), `limits` (`memory`, `cpus`, `nice`; applied to systemd/docker/launchd),
`env_file` (API keys installed 0600 as the daemon environment; plain `KEY=VALUE` lines),
`enabled`. Exactly one local non-docker host is the `hub`.

Current layout: hub `workspace_root` = `G:\git`; docker `workspace_mount` = `G:\agents`;
remote hosts use `~/paseo-workspaces`.

## Workflow

```powershell
python scripts\paseo-fleet.py validate
python scripts\paseo-fleet.py plan --host jdh-pi-02      # secrets redacted
python scripts\paseo-fleet.py provision                  # all enabled hosts, idempotent
python scripts\paseo-fleet.py register                   # saves hosts in the hub daemon
python scripts\paseo-fleet.py workspaces --repos         # workspace roots + local git repos as projects
python scripts\paseo-fleet.py status
python scripts\paseo-fleet.py dispatch --label arm64 "run the tests and fix failures"
```

`make fleet-up` runs provision, register and workspaces. Re-running upgrades in place
after you bump versions in the inventory. Add a machine by adding an inventory entry
and re-running; the macOS entry in the example only needs `enabled: true` once the
machine is reachable over SSH.

## Home Assistant add-on as a hub

The Paseo add-on inside Home Assistant is its own hub daemon with its own host list.
`scripts/paseo-ha-link.sh` (run on the Orange Pi, idempotent) gives it a host for the
machine it runs on and that machine's `~/paseo-workspaces` as a project:

```powershell
(Get-Content scripts\paseo-ha-link.sh -Raw) -replace "`r`n","`n" | ssh jd@homeassistant 'bash -s'
```

It generates an SSH key inside the add-on (`/data/home/.ssh/id_paseo_fleet`, persisted and
backed up with the add-on), authorizes it in `~/.ssh/authorized_keys` with
`restrict,port-forwarding,permitopen="127.0.0.1:6767"` (tunnel to the daemon only, no
shell), and registers `ssh://<user>@<add-on gateway>?daemonPort=6767` as host `orangepi-ha`.
Add further machines later with `paseo host add ... --home /data/home/.paseo` inside the
add-on, using the same key and an `~/.ssh/config` entry per host.

**Workstation (no inbound port).** `scripts/paseo-ha-workstation-link.ps1` runs a logon
scheduled task (`paseo-ha-reverse-tunnel`) holding `ssh -R 127.0.0.1:16767:127.0.0.1:6767`
to the Orange Pi, extends the add-on key's `permitopen` to port 16767, and registers
host `jdh-pro-05` plus a single workspace (`G:\git`, no per-repo projects) in the
add-on. Trade-off: anything with a login on the Orange Pi can reach the workstation
daemon on that loopback port. The host shows offline while the workstation is off or logged out.

## Relay configuration and recovery

Relay access is an explicit opt-in; the fleet still binds bare-metal daemons
to loopback and Docker publishes only a loopback host port. The deployed fleet
and HA add-on have relay enabled. No public inbound port or wildcard CORS
origin is needed. The relay carries the encrypted connection; treat pairing
URLs and QR codes as credentials, and never commit or paste them into logs.

On each bare-metal host, run the CLI as the **same user that runs its daemon**:

```text
paseo daemon config set daemon.relay.enabled true
paseo daemon reload --json
```

In the HA add-on, the **relay option in Supervisor is authoritative**:
set it to `true` in the add-on configuration and restart only that add-on.
A saved `daemon.relay.enabled: true` cannot override an add-on environment
setting that forces relay off. Keep existing providers, host registrations,
workspaces, identity keys and credentials; do not replace the entire config
to change one setting.

The fleet Docker image runs as UID/GID 1000 (`paseo`). Edit its config as that
user, not root:

```powershell
docker exec --user 1000:1000 --env HOME=/home/paseo paseo-fleet-jdh-pro-05-docker paseo daemon config set daemon.relay.enabled true
docker exec --user 1000:1000 --env HOME=/home/paseo paseo-fleet-jdh-pro-05-docker paseo daemon reload --json
```

The November 27 restart loop was caused by root-owned, mode-0600
`/home/paseo/.paseo/config.json` and `cli-client-id`. Recovery backed up those
two files privately and restored their owner to `1000:1000`, keeping mode
0600. It did not delete the volume, regenerate identity keys, reset passwords,
or expose the daemon publicly. If the container cannot stay up, use a temporary
container from the **existing fleet image**, with its existing home volume
mounted and networking disabled, to repair only those ownerships. Never use
world-readable/writable permissions as a workaround.

After repair, `paseo-fleet.py status` should report every enabled host up and
the HA add-on's `paseo host ls` should show its Pi and workstation online.
Check relay operation with an authenticated `project ls --json` using a fresh
pairing URL kept private. A local `/api/health` response alone does not prove
the relay works. Password-protected Docker daemons still require their existing
`PASEO_PASSWORD` over the relay. The 0.15.0 `daemon status` provider enumeration
can exceed its 1500 ms request timeout even after a successful relay connection;
do not reset a working configuration solely for that timeout.

Public recovery settings are in `examples/deployed-paseo/`; identities,
pairing material, provider login state and Docker passwords remain private.

## Known limits

- Agent CLIs (Claude, Codex, Copilot) are installed on each host but need
  authentication: put API keys in an `env_file`, or log in once per host
  (`paseo-fleet` does not automate interactive OAuth).
- Windows hosts have no resource limits; per-host `limits` apply to Linux, Docker, macOS (nice).
- Linux user services need linger; provisioning enables it and warns when it cannot.
- The Orange Pi Home Assistant host runs the daemon niced and memory capped; keep
  the disk guard in mind (`docs/BACKUP.md`) since agent worktrees consume space.
- Daemons trust the local user; do not enable on shared multi-user machines.
