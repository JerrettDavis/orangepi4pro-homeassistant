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

## Known limits

- Agent CLIs (Claude, Codex, Copilot) are installed on each host but need
  authentication: put API keys in an `env_file`, or log in once per host
  (`paseo-fleet` does not automate interactive OAuth).
- Windows hosts have no resource limits; per-host `limits` apply to Linux, Docker, macOS (nice).
- Linux user services need linger; provisioning enables it and warns when it cannot.
- The Orange Pi Home Assistant host runs the daemon niced and memory capped; keep
  the disk guard in mind (`docs/BACKUP.md`) since agent worktrees consume space.
- Daemons trust the local user; do not enable on shared multi-user machines.
