#!/bin/sh
# Run the real Home Assistant Supervisor on the Orange Pi inside an isolated trial: its own network namespace, its own
# containerd and Docker daemon, storage on a separate disk. Prod Docker, ports and Home Assistant are not touched.
# Needs root. Usage: up.sh <storage-dir> [machine]   (machine defaults to qemuarm-64)
set -e
T=${1:?storage directory, e.g. /mnt/opisd-check/supervisor-trial}
MACHINE=${2:-qemuarm-64}
SOCK=/run/docker-trial.sock
IMAGE=ghcr.io/home-assistant/aarch64-hassio-supervisor:${SUPERVISOR_VERSION:-2026.10.3}
mkdir -p "$T/docker" "$T/data" "$T/containerd/root" /run/containerd-trial /run/supervisor /etc/netns/svtrial
echo "nameserver 1.1.1.1" > /etc/netns/svtrial/resolv.conf
if ! ip netns list | grep -q '^svtrial'; then
  ip netns add svtrial
  ip link add svh0 type veth peer name svc0
  ip link set svc0 netns svtrial
  ip addr add 10.99.0.1/30 dev svh0; ip link set svh0 up
  ip netns exec svtrial ip addr add 10.99.0.2/30 dev svc0
  ip netns exec svtrial ip link set svc0 up; ip netns exec svtrial ip link set lo up
  ip netns exec svtrial ip route add default via 10.99.0.1
  iptables -t nat -A POSTROUTING -s 10.99.0.0/30 ! -o svh0 -j MASQUERADE -m comment --comment svtrial
  iptables -I FORWARD -i svh0 -j ACCEPT -m comment --comment svtrial
  iptables -I FORWARD -o svh0 -j ACCEPT -m comment --comment svtrial
fi
if ! docker -H unix://$SOCK info >/dev/null 2>&1; then
  # nsenter (not `ip netns exec`) so /sys/fs/cgroup stays mounted for dockerd.
  nohup nsenter --net=/run/netns/svtrial containerd --root "$T/containerd/root" --state /run/containerd-trial/state \
    --address /run/containerd-trial/containerd.sock > "$T/containerd.log" 2>&1 &
  sleep 4
  nohup nsenter --net=/run/netns/svtrial dockerd --data-root "$T/docker" --exec-root /run/docker-trial \
    --host unix://$SOCK --pidfile /run/docker-trial.pid --containerd /run/containerd-trial/containerd.sock \
    --storage-driver overlay2 --feature containerd-snapshotter=false > "$T/dockerd.log" 2>&1 &
  sleep 12
fi
D="docker -H unix://$SOCK"
$D image inspect "$IMAGE" >/dev/null 2>&1 || $D pull "$IMAGE"
$D rm -f hassio_supervisor >/dev/null 2>&1 || true
$D run -d --name hassio_supervisor --privileged --security-opt seccomp=unconfined --restart=no \
  -v $SOCK:/run/docker.sock:rw -v /run/dbus:/run/dbus:ro -v /run/udev:/run/udev:ro -v /etc/machine-id:/etc/machine-id:ro \
  -v "$T/data":/data:rw -e SUPERVISOR_SHARE="$T/data" -e SUPERVISOR_NAME=hassio_supervisor -e SUPERVISOR_MACHINE="$MACHINE" "$IMAGE"
echo "Supervisor starting. API inside the namespace: http://172.30.32.2; Home Assistant: http://10.99.0.2:8123"
