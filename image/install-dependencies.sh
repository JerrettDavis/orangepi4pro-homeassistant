#!/usr/bin/env bash
# Intended to run INSIDE the target root (native arm64 or registered qemu/binfmt).
set -euo pipefail
[[ ${1:-} == --apply ]] || { echo 'Dry run: install system packages and official Docker Engine/Compose. Pass --apply.'; exit 0; }
[[ $EUID -eq 0 ]] || { echo 'Root required' >&2; exit 1; }
# shellcheck disable=SC1091
source /etc/os-release
case "$ID" in ubuntu|debian) ;; *) echo 'Only Ubuntu/Debian are supported' >&2; exit 1;; esac
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends python3 python3-opencv ca-certificates curl gnupg age openssl \
  rsync ffmpeg v4l-utils openssh-server mosquitto-clients x11-xserver-utils lightdm openbox xserver-xorg
# Docker's official apt repository, not a curl | sh installer.
install -m 0755 -d /etc/apt/keyrings
curl --fail --silent --show-error --location "https://download.docker.com/linux/$ID/gpg" -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
arch=$(dpkg --print-architecture)
codename=${UBUNTU_CODENAME:-${VERSION_CODENAME:?}}
printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/%s %s stable\n' \
  "$arch" "$ID" "$codename" > /etc/apt/sources.list.d/opiha-docker.list
apt-get update
# Do not remove existing Docker automatically. Conflicts must be reviewed by the operator.
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
# Debian has a native Chromium package; Ubuntu's transitional Snap needs a running system.
if [[ "$ID" == debian ]]; then
  apt-get install -y --no-install-recommends chromium
fi
apt-get clean
# No kernel, bootloader, partition, or distro upgrade is requested.
