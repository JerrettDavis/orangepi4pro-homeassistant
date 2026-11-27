#!/usr/bin/env bash
# Keeps the root filesystem well below full. Run hourly by opiha-diskguard.timer, and on demand from the Orange Pi
# panel (Storage tab) as `opiha-disk-guard light|deep`.
#
#   auto  (default) always runs the cheap cache cleanup; also prunes Docker harder at OPIHA_DISK_PRUNE (75%).
#   light cache cleanup only: apt, snap revisions, journal, user caches, Docker build cache and dangling images.
#   deep  light + unused Docker images, stopped non-managed containers, old HA automatic backups, autoremove.
#
# Target is a 25-33% free buffer; 85% is the emergency alert. Never touches the recorder database, the newest
# automatic backups, running containers, or Supervisor-managed (hassio_*, addon_*, app_*) containers.
set -uo pipefail
mode="${1:-auto}"
prune_at="${OPIHA_DISK_PRUNE:-75}"
keep_backups="${OPIHA_KEEP_BACKUPS:-3}"
backup_dir="${OPIHA_BACKUP_DIR:-/srv/homeassistant/ha/backups}"
used() { df --output=pcent / | tail -1 | tr -dc '0-9'; }
have() { command -v "$1" >/dev/null 2>&1; }

before="$(used)"
case "$mode" in
  auto) deep=0; (( before >= prune_at )) && deep=1 ;;
  light) deep=0 ;;
  deep) deep=1 ;;
  *) echo "usage: $0 [auto|light|deep]" >&2; exit 2 ;;
esac
echo "mode=$mode deep=$deep root=${before}%"

apt-get clean || true
rm -rf /var/lib/snapd/cache/* 2>/dev/null || true
if have snap; then
  snap list --all | awk '/disabled/{print $1, $3}' | while read -r name rev; do
    snap remove "$name" --revision="$rev" || true
  done
fi
journalctl --vacuum-size=100M || true
find /var/log -type f \( -name '*.gz' -o -name '*.[0-9]' \) -mtime +7 -delete 2>/dev/null || true
for home in /home/* /root; do
  rm -rf "$home/.npm/_cacache" "$home/.cache/pip" "$home/.cache/pypoetry" "$home/.cache/node-gyp" 2>/dev/null || true
done

if have docker && docker info >/dev/null 2>&1; then
  docker builder prune -af || true
  docker image prune -f || true
  if (( deep )); then
    docker ps -a --filter status=exited --filter status=created --format '{{.Names}}' \
      | grep -Ev '^(hassio_|addon_|app_)' | xargs -r docker rm || true
    docker image prune -af || true
    docker network prune -f || true
  else
    docker image prune -af --filter until=168h || true
  fi
fi

if (( deep )); then
  apt-get -y autoremove --purge || true
  if [[ -d "$backup_dir" ]]; then
    # Only HA's own rotated automatic backups; manual and pre-update backups are left alone.
    ls -1t "$backup_dir"/[Aa]utomatic_backup_*.tar 2>/dev/null | tail -n +"$((keep_backups + 1))" | xargs -r rm -v || true
  fi
fi

echo "root ${before}% -> $(used)%"
