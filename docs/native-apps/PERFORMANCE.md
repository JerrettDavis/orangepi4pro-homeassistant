# Performance plan

The native design avoids a guest OS and guest RAM reservation. It does not promise zero overhead or benchmarked equivalence to bare-metal HAOS. Docker, the application itself, the host manager and an in-HA HTTP/WebSocket proxy still consume resources. No Orange Pi performance measurements were made in this environment.

The upstream hardware report at the reviewed commit recorded roughly 5.7 GiB RAM on the 6 GiB A733 board. That is a prior local observation, not a new measurement. Preserve the existing kernel, display stack, Firefox touch changes, NVMe boot and working governor. Do not upgrade a kernel merely to install an app panel.

## Default controls

The manager leaves 2048 MiB outside the total of admitted app memory ceilings. This is conservative accounting, including installed-but-stopped apps, not actual allocated RAM and not a cgroup reservation for HA. It refuses starts/installations when available memory is under 384 MiB or free storage under 2 GiB. Snapshots also check their own storage requirement.

Each app receives a Docker memory ceiling and equal memory-plus-swap ceiling. An app that exceeds it can be OOM-killed; it is not allowed to consume unlimited host swap. Change its budget only after measuring and retaining host/HA headroom. Default CPU shares are 512, relative to the typical default-weight Docker workload, with no blanket `--cpus` cap. Shares matter under contention and are not a latency guarantee. HA's own container is not reconfigured.

The manager service has its own 160 MiB soft and 256 MiB hard memory limits. It does not run a continuous Docker-stats loop. Catalog refreshes occur every 15 seconds while the panel is visible, and detailed stats are requested explicitly. Hidden app panels do not poll the catalog. Embedded UI session renewal is active only while viewing the app.

## Measure the actual appliance

Run the same private, read-only sample before installation, after an idle manager/panel installation, while opening app UIs, and during representative work:

```bash
python3 scripts/native-apps/benchmark.py --seconds 60 \
  --label before-native-apps --output /private/bench-before.json

python3 scripts/native-apps/benchmark.py --seconds 60 \
  --label idle-native-apps --output /private/bench-idle.json

python3 scripts/native-apps/benchmark.py --seconds 60 \
  --label esphome-build --output /private/bench-build.json
```

The default probe is the existing unauthenticated local HA HTTP page. `--ha-url` accepts a credential-free HTTP(S) endpoint; do not embed a token. The result records response samples, median/p95, failures, available RAM, swap, load, thermals and Linux pressure metrics where exposed. This is not an authenticated entity or automation-latency benchmark.

Also check the actual touchscreen while scrolling and switching dashboards, selected device/automation response times, dropped camera frames, swap pressure, thermals, and Docker OOM/restart events. Keep conditions comparable; a simultaneous recorder purge or firmware build can dominate a sample. Establish acceptable thresholds for your workload rather than treating a generic percentage as certification.

## ESPHome and camera workloads

The adapter requests `ESPHOME_DEFAULT_COMPILE_PROCESS_LIMIT=1`. A requested compile limit is not proof that every future builder/backend honors it or that concurrent queued builds cannot create contention. Confirm it in real build logs and set builder concurrency conservatively. A 1536 MiB ceiling may be insufficient for a particular ESP-IDF project. Raising the ceiling consumes the same finite board memory; increasing zram is not a substitute for measuring the working set.

Current Device Builder supports sending builds to another dashboard. A workstation can do compilation while the Orange Pi retains the dashboard and device configuration. Pair this deliberately and use manual addressing where the bridge cannot discover mDNS peers. The pinned 2026.9.0 image and its Device Builder routing were checked in upstream source, but remote compilation was not exercised here.

go2rtc begins with no streams and no hardware passthrough. Prefer restreaming an existing encoded stream over transcoding. Do not assume CSI, hardware encode/decode or the A733 NPU is usable: the reviewed hardware baseline had no camera/NPU device nodes. That remains a board-support task.
