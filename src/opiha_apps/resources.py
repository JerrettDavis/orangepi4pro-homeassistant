"""Read-only host resource samples; no governor, scheduler, or HA limits are changed."""
from __future__ import annotations
import os
from pathlib import Path
import shutil
import time


def sample(path: Path) -> dict:
    memory = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, value = line.split(":", 1)
            memory[key] = int(value.strip().split()[0]) * 1024
    except (OSError, ValueError):
        pass
    thermals = []
    for zone in sorted(Path("/sys/class/thermal").glob("thermal_zone*")):
        try:
            temperature = int((zone / "temp").read_text()) / 1000
            thermals.append({"name": (zone / "type").read_text().strip(), "celsius": temperature})
        except (OSError, ValueError):
            continue
    pressures = {}
    for name in ("cpu", "memory", "io"):
        try:
            pressures[name] = Path("/proc/pressure", name).read_text().strip()
        except OSError:
            pressures[name] = "unavailable"
    try:
        disk = shutil.disk_usage(path)
        disk_free = disk.free
    except OSError:
        disk_free = None
    return {"at": time.time(), "memory_total": memory.get("MemTotal"),
            "memory_available": memory.get("MemAvailable"), "swap_total": memory.get("SwapTotal"),
            "swap_free": memory.get("SwapFree"), "disk_free": disk_free,
            "load_average": list(os.getloadavg()), "cpu_count": os.cpu_count(),
            "thermals": thermals, "pressure": pressures}
