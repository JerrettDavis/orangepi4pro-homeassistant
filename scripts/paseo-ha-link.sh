#!/usr/bin/env bash
# Link the Paseo Home Assistant add-on to this machine's own Paseo daemon (the
# paseo-fleet systemd user service), so the add-on UI has a "this machine" host and
# workspace. Idempotent. Run on the Orange Pi as the fleet user:
#   bash scripts/paseo-ha-link.sh
# The add-on gets its own SSH key, authorized here with a forwarding-only restriction
# to the daemon port (no shell, no other ports).
set -euo pipefail

CONTAINER="${PASEO_HA_CONTAINER:-$(sudo docker ps --format '{{.Names}}' | grep -E '^app_.*_paseo$' | head -1)}"
LABEL="${PASEO_HA_HOST_LABEL:-orangepi-ha}"
PORT="${PASEO_HA_DAEMON_PORT:-6767}"
USER_NAME="$(id -un)"
WORKSPACE="${PASEO_HA_WORKSPACE:-$HOME/paseo-workspaces}"
KEY=/data/home/.ssh/id_paseo_fleet
HOME_DIR=/data/home/.paseo

[ -n "$CONTAINER" ] || { echo "Paseo add-on container not found" >&2; exit 1; }
GATEWAY="$(sudo docker exec "$CONTAINER" sh -c "ip route | awk '/default/ {print \$3; exit}'")"
[ -n "$GATEWAY" ] || { echo "cannot determine add-on gateway" >&2; exit 1; }
inpod() { sudo docker exec "$CONTAINER" "$@"; }
mkdir -p "$WORKSPACE"

inpod sh -c "mkdir -p /data/home/.ssh && chmod 700 /data/home/.ssh
  [ -f $KEY ] || ssh-keygen -q -t ed25519 -N '' -C paseo-ha-addon -f $KEY
  printf 'Host %s\n  User %s\n  IdentityFile %s\n  IdentitiesOnly yes\n' '$GATEWAY' '$USER_NAME' '$KEY' > /data/home/.ssh/config
  chmod 600 /data/home/.ssh/config"

PUB="$(inpod cat "$KEY.pub")"
mkdir -p ~/.ssh && touch ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys
if ! grep -qF "${PUB%% paseo-ha-addon*}" ~/.ssh/authorized_keys; then
  echo "restrict,port-forwarding,permitopen=\"127.0.0.1:$PORT\" $PUB" >> ~/.ssh/authorized_keys
fi

CONN="ssh://$USER_NAME@$GATEWAY?daemonPort=$PORT"
if ! inpod paseo host ls --home "$HOME_DIR" --json | grep -q "\"label\": \"$LABEL\""; then
  inpod paseo host add "$CONN" --label "$LABEL" --meta platform=linux \
    --meta labels=linux,arm64,home-assistant,bare-metal --home "$HOME_DIR"
fi
inpod paseo --host "$CONN" project create "$WORKSPACE" --json >/dev/null
sleep 5
inpod paseo host ls --home "$HOME_DIR"
