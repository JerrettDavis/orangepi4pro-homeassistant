# Local testing

## Prerequisites

Use Linux or WSL2, Python 3.10+, and Docker Engine with Compose v2.24 or newer. Use the Linux Engine inside WSL2 for the documented test path; Home Assistant's official Container instructions exclude Docker Desktop from supported deployments. The generated env-file object uses modern Compose syntax. Keep working state on a Linux filesystem for permissions and consistent behavior. On Windows, prefer WSL for all runtime and image operations; the PowerShell script is only an export convenience.

```bash
cd orangepi4pro-homeassistant
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
./scripts/test.sh
```

`scripts/test.sh` is the authoritative Linux validation entry point. It runs
the public-source scanner, Python tests and compilation, shell syntax checks,
configuration rendering, and deterministic source packaging. Optional tools
such as `age` and OpenCV are reported as explicit skips when absent. Add
`--images` to inspect each pinned registry index for a `linux/arm64` manifest;
add `--docker-smoke` only when a real Docker daemon is available and a
container start is intended.

Install `age` and `openssl` to exercise encryption and signatures. `python3-opencv` is only required for vision; tests skip optional native dependencies when absent and report the skip. Do not mistake a skipped test for a pass.

## No Docker required: inspect the generated plan

```bash
./bin/opiha init --mode lab
./bin/opiha doctor
./bin/opiha render > .local/compose-preview.json
python3 -m json.tool .local/compose-preview.json
```

`init` only creates a new private workspace. It does not overwrite an existing one or start a container. Commands use `.local/appliance.json` by default. Put `--config PATH` **before** the command to choose another workspace.

For the existing Orange Pi, preview the dedicated live-host layout instead:

```bash
./bin/opiha host plan
./bin/opiha host install
```

Both commands are read-only in this form. See [host installation](HOST-INSTALL.md)
before using the explicit `sudo ... host install --apply` path.

## Blank HA smoke test

```bash
./bin/opiha up
# http://127.0.0.1:18123
./bin/opiha status
./bin/opiha down
```

Or run `./scripts/docker-smoke.sh`: it creates an independent workspace under `.local/smoke`, uses port 28123, waits for an HTTP response, and stops/removes its containers afterward. That is a container startup test, not an integration or hardware acceptance test.

To run independent labs:

```bash
./bin/opiha --config .local/second/appliance.json init --mode lab
./bin/opiha --config .local/second/appliance.json configure --lab-port 18124
./bin/opiha --config .local/second/appliance.json up
```

Lab project names include a hash of the data directory so one lab does not replace another. Even when the config contains optional feature settings, lab Compose omits Z-Wave, MQTT and camera hardware services. HA uses an internal bridge and a loopback UI port, never `network_mode: host` in lab mode.

Docker's network isolation is a practical rehearsal safeguard, not a guarantee against a malicious container or host-local service interaction. Use a separate disconnected environment for an absolute no-device-side-effects requirement. Never switch a restored lab to appliance mode merely to make unavailable integrations green while production is still running.

## Rehearse with an offline config copy

A real copy contains credentials. Keep it outside Git, never upload it to a public issue, and don't point the command at a mounted live database.

```bash
# Example only: set this to the version from the SOURCE VM, not automatically to the default.
SOURCE_HA_VERSION=2026.9.3
./bin/opiha configure --ha-version "$SOURCE_HA_VERSION"

./bin/opiha inventory --ha-config /private/export/ha-config --output .local/before.json
./bin/opiha import-config --source /private/export/ha-config --source-stopped
# The preceding command previews basic source/version checks without replacing state.
./bin/opiha import-config --source /private/export/ha-config --source-stopped --apply --replace
./bin/opiha inventory --output .local/after-import.json
./bin/opiha compare .local/before.json .local/after-import.json
./bin/opiha sqlite-check
./bin/opiha up
```

Import stops/removes target project containers before changing state. The `--source-stopped` flag is your attestation about the **source copy**; it cannot prove a remote writer has stopped. Imported production credentials are not anonymized. Integration setup failures caused by quarantine are expected; inventory parity is the first rehearsal objective.

`--offline --source-stopped` is available when Docker is not installed, but only use it after independently stopping every writer. It is not a faster way to ignore running containers.

## Exercise the appliance format without encryption (lab only)

```bash
./bin/opiha down
./bin/opiha backup --output .local/rehearsal.tar.gz --plaintext --offline --source-stopped
./bin/opiha restore --bundle .local/rehearsal.tar.gz --offline --source-stopped
# Add --apply --replace to commit a verified restore; it remains stopped afterward.
```

Production backups require an age recipient. Do not use a plaintext lab bundle as your long-term household backup. See [recovery](RECOVERY.md) for encryption, signatures and USB recovery.

## Diagnostics UI

```bash
./bin/opiha serve
# http://127.0.0.1:8099/?stay=1
```

The page is read-only and auto-refreshes. Without `?stay=1`, it forwards to the configured dashboard after HA responds repeatedly. It is not an upload endpoint and does not expose a Docker socket. A responding login page is not proof that all integrations work; use `live-check` and the manual acceptance list.

## What not to infer from a successful PC test

No Linux x86 test proves the A733 kernel boots, its camera is usable, a display session starts, ARM64 custom-integration dependencies exist, or the USB stick works. Image building needs Linux mount/loop permissions and a trusted base image. The delivered validation report separates these tests explicitly.
