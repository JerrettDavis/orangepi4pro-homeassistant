# Real Supervisor trial

`up.sh <dir>` runs the actual Home Assistant Supervisor (2026.10.3) next to production, isolated in its own network
namespace with its own Docker daemon and storage, so production Docker, ports and Home Assistant are untouched.
`down.sh` stops it.

Measured on the Orange Pi 4 Pro (Ubuntu 22.04, kernel 5.15, no AppArmor): the Supervisor starts and reports
`healthy: true, supported: false` (unsupported: apparmor, os, os_agent, docker_configuration, connectivity_check,
systemd_journal). Its DNS, CLI, audio, multicast and observer plugins start, the store lists the official, ESPHome,
Music Assistant and Community repositories (96 add-ons), `core_mosquitto` installed and started through the Supervisor
API, announced itself to Home Assistant and the Supervisor, and Home Assistant core ran under it. `/run/supervisor`
must exist on the host. Memory is the limit: the full stack plus production needs about 3 GB.

This is a trial, not a migration. Moving production Home Assistant under the Supervisor is a separate, reversible
cutover that needs its own backup and approval.
