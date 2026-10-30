#!/usr/bin/env bash
# Prunes regenerable caches when the root filesystem passes a threshold.
# Never touches Home Assistant data, backups, or in-use container images.
set -euo pipefail
threshold="${OPIHA_DISK_THRESHOLD:-80}"
used() { df --output=pcent / | tail -1 | tr -dc '0-9'; }

before="$(used)"
if (( before < threshold )); then
  echo "root ${before}% < ${threshold}%: nothing to do"
  exit 0
fi

apt-get clean
rm -rf /var/lib/snapd/cache/*
snap list --all | awk '/disabled/{print $1, $3}' | while read -r name rev; do
  snap remove "$name" --revision="$rev" || true
done
journalctl --vacuum-size=100M || true
docker image prune -f || true

echo "root ${before}% -> $(used)%"
