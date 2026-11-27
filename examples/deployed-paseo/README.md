# Paseo public recovery settings

`daemon-configs.json` captures the public configuration of the four enabled
fleet daemons and the HA add-on after the November 27, 2026 relay repair.
It is an inventory of per-daemon settings, **not** a single Paseo config file.
Use the supported `daemon config set` command to merge settings into an
existing installation. Never overwrite identity, host registrations or
provider logins with a public snapshot.

The HA add-on also requires `relay: true` in its Supervisor options; those
options are in `examples/deployed-homeassistant/addon_options/`. Provision the
fleet from its private inventory as described in `docs/PASEO-FLEET.md`, then
opt in to relay on each daemon. Run the Docker CLI as UID/GID 1000, not root.
Its daemon listens on the container interface through its existing deployment
override, but the published host port remains loopback-only and password
protected. Do not copy bare-metal listen settings over that override.

Pairing URLs, local credentials, identity keypairs, SSH keys, API keys and
Docker passwords are deliberately absent. Preserve them in private backups.
The repair retained the existing identities, providers, workspaces and host
registrations and verified authenticated project listing through all five
encrypted relay connections.
