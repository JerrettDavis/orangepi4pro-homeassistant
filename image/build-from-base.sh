#!/usr/bin/env bash
# Modify only a regular-file COPY of a trusted, boot-tested, clean Orange Pi image.
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
base= checksum= output= part= cache= pubkey= trust= apply=0 deps=0 kiosk=0 attest=0
usage() { echo 'build-from-base.sh --base clean.img --sha256 HASH --root-partition N --output new.img [--install-dependencies] [--enable-kiosk] [--ssh-public-key FILE] [--recovery-trust-key FILE] [--container-cache DIR] --attest-clean-base --apply'; }
while (($#)); do
  case "$1" in
    --base) base=$2; shift 2;; --sha256) checksum=$2; shift 2;; --root-partition) part=$2; shift 2;;
    --output) output=$2; shift 2;; --container-cache) cache=$2; shift 2;; --ssh-public-key) pubkey=$2; shift 2;;
    --recovery-trust-key) trust=$2; shift 2;; --apply) apply=1; shift;;
    --install-dependencies) deps=1; shift;; --enable-kiosk) kiosk=1; shift;; --attest-clean-base) attest=1; shift;;
    --help|-h) usage; exit 0;; *) usage >&2; exit 2;;
  esac
done
[[ -n "$base" && -n "$checksum" && -n "$output" && "$part" =~ ^[1-9][0-9]*$ ]] || { usage >&2; exit 2; }
[[ "$checksum" =~ ^[a-fA-F0-9]{64}$ ]] || { echo 'Expected a full SHA256' >&2; exit 2; }
[[ -f "$base" && ! -L "$base" && ! -b "$base" ]] || { echo 'Base must be an uncompressed regular .img file' >&2; exit 2; }
[[ ! -e "$output" && ! -L "$output" ]] || { echo 'Output already exists' >&2; exit 2; }
actual=$(sha256sum "$base" | cut -d' ' -f1)
[[ "$actual" == "${checksum,,}" ]] || { echo 'Base checksum mismatch' >&2; exit 2; }
if (( ! apply )); then
  printf 'DRY RUN: clone %s to %s; mount partition %s; install overlay; preserve boot sectors and kernel.\n' "$base" "$output" "$part"
  exit 0
fi
[[ $EUID -eq 0 && $attest -eq 1 ]] || { echo 'Requires root and --attest-clean-base. Never publish a used household disk clone.' >&2; exit 2; }
[[ -n "$pubkey" || -n "$trust" ]] || { echo 'Supply a public SSH key or signed recovery trust key; image passwords are disabled.' >&2; exit 2; }
if [[ -n "$pubkey" ]]; then ssh-keygen -lf "$pubkey" >/dev/null; fi
mkdir -p "$(dirname "$output")"
partial="${output}.partial"
[[ ! -e "$partial" ]] || { echo 'Partial output already exists; inspect it before retrying' >&2; exit 2; }
cp --reflink=auto --sparse=always -- "$base" "$partial"
work=$(mktemp -d)
loop= mounted=0
cleanup() {
  set +e
  # No forced unmounts: failure leaves the partial image for diagnosis.
  for p in run sys proc dev; do mountpoint -q "$work/root/$p" && umount -R "$work/root/$p"; done
  if (( mounted )); then umount "$work/root"; fi
  [[ -n "$loop" ]] && losetup -d "$loop"
  rmdir "$work/root" "$work" 2>/dev/null || true
}
trap cleanup EXIT
loop=$(losetup --find --show --partscan "$partial")
rootdev="${loop}p${part}"
[[ -b "$rootdev" ]] || { echo 'Selected root partition does not exist' >&2; exit 2; }
mkdir "$work/root"
mount "$rootdev" "$work/root"
mounted=1
[[ -f "$work/root/etc/os-release" ]] || { echo 'Selected partition is not a Linux rootfs' >&2; exit 2; }
args=(--target-root "$work/root" --apply)
(( kiosk )) && args+=(--enable-kiosk)
[[ -n "$trust" ]] && args+=(--trust-key "$trust")
python3 "$repo/image/overlay.py" "${args[@]}"
if (( deps )); then
  # Native arm64 is preferred. x86 builds require qemu-user-static/binfmt configured by the operator.
  for d in dev proc sys; do
    mkdir -p "$work/root/$d"
    mount --rbind "/$d" "$work/root/$d"
    mount --make-rslave "$work/root/$d"
  done
  mkdir -p "$work/root/run"
  mount -t tmpfs tmpfs "$work/root/run"
  # Temporary resolver, restored before sanitization; do not bind the host's /run.
  [[ ! -e "$work/root/etc/resolv.conf" && ! -L "$work/root/etc/resolv.conf" ]] || mv "$work/root/etc/resolv.conf" "$work/resolv.conf.old"
  cp -L /etc/resolv.conf "$work/root/etc/resolv.conf"
  policy="$work/root/usr/sbin/policy-rc.d"
  [[ ! -e "$policy" ]] || cp -a "$policy" "$work/policy-rc.d.old"
  printf '#!/bin/sh\nexit 101\n' > "$policy"; chmod 755 "$policy"
  chroot "$work/root" /bin/bash /opt/orangepi4pro-homeassistant/image/install-dependencies.sh --apply
  if [[ -f "$work/policy-rc.d.old" ]]; then mv "$work/policy-rc.d.old" "$policy"; else rm -f "$policy"; fi
  rm -f "$work/root/etc/resolv.conf"
  [[ ! -e "$work/resolv.conf.old" && ! -L "$work/resolv.conf.old" ]] || mv "$work/resolv.conf.old" "$work/root/etc/resolv.conf"
  for d in run sys proc dev; do umount -R "$work/root/$d"; done
fi
# Fail before publishing an image lacking the minimum runtime.
chroot "$work/root" /usr/bin/python3 --version
chroot "$work/root" /usr/bin/docker compose version
python3 "$repo/image/scrub.py" --root "$work/root" --apply
if [[ -n "$pubkey" ]]; then
  install -d -m 0700 "$work/root/root/.ssh"
  install -m 0600 "$pubkey" "$work/root/root/.ssh/authorized_keys"
fi
if [[ -n "$cache" ]]; then
  [[ -f "$cache/images.tar" && -f "$cache/manifest.json" ]] || { echo 'Invalid container cache' >&2; exit 2; }
  mkdir -p "$work/root/opt/opiha-cache"
  cp -- "$cache/images.tar" "$cache/manifest.json" "$work/root/opt/opiha-cache/"
fi
python3 "$repo/image/audit-rootfs.py" "$work/root"
chroot "$work/root" dpkg-query -W > "${output}.packages.txt"
sync
umount "$work/root"; mounted=0
losetup -d "$loop"; loop=
mv -- "$partial" "$output"
sha256sum "$output" > "${output}.sha256"
python3 - "$base" "$checksum" "$output" "$part" <<'PY'
import json, sys
from pathlib import Path
base, sha, out, part = sys.argv[1:]
Path(out + '.manifest.json').write_text(json.dumps({'base_sha256': sha, 'root_partition': int(part),
 'boot_assets_modified': False, 'rootfs_overlay': 'orangepi4pro-homeassistant',
 'reproducibility': 'Base hash and package inventory recorded; apt repositories/filesystem timestamps are not bit-reproducible'}, indent=2) + '\n')
PY
printf 'Created %s and its SHA256, package inventory and build manifest. Not hardware-validated.\n' "$output"
