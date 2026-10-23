"""Host control behind the Orange Pi panel: stats, services, power, Docker, updates, kiosk/desktop mode, terminal.

Every operation takes a small validated JSON object and runs fixed argument vectors; nothing user-supplied
reaches a shell. Anything that writes outside the manager's sandbox (package installs, enabling units, power
actions, the kiosk user's files) is handed to PID 1 with ``systemd-run`` so it runs unsandboxed and survives a
manager restart. Callers are already authenticated HA administrators; destructive operations still require an
explicit ``confirm: true``.
"""
from __future__ import annotations
import base64
import binascii
import fcntl
import json
import os
from pathlib import Path
import pty
import re
import secrets
import select
import struct
import subprocess
import termios
import threading
import time
from .common import AppError

SERVICE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9:_.@-]{0,100}\.service")
CONTAINER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
IMAGE_RE = re.compile(r"(sha256:)?[a-f0-9]{12,64}|[A-Za-z0-9][A-Za-z0-9_.:/@-]{0,200}")
OWN_UNIT = "orangepi-apps.service"
# Units whose loss strands the operator: restart is allowed, stop/disable/mask are not.
LIFELINE = {OWN_UNIT, "ssh.service", "sshd.service", "dbus.service", "systemd-logind.service", "systemd-journald.service",
            "systemd-networkd.service", "NetworkManager.service", "systemd-resolved.service"}
SERVICE_ACTIONS = {"start", "stop", "restart", "enable", "disable"}
JOB_UNIT = "opiha-host-job"
JOB_KINDS = {
    "apt-update": (["apt-get", "update"], "Refresh package lists"),
    "apt-upgrade": (["apt-get", "-y", "-o", "Dpkg::Options::=--force-confdef", "-o", "Dpkg::Options::=--force-confold", "upgrade"], "Upgrade packages"),
    "snap-refresh": (["snap", "refresh"], "Refresh snaps"),
}
KIOSK_UNITS = {"kiosk": "orangepi-homeassistant-kiosk.service", "controls": "orangepi-homeassistant-kiosk-controls.service",
               "keyboard": "orangepi-homeassistant-keyboard.service"}
LOG_LIMIT = 256 * 1024


def need(data: dict, allowed: set[str], required: set[str] = frozenset()) -> None:
    if not isinstance(data, dict) or set(data) - allowed or required - set(data):
        raise AppError("Unexpected or missing request fields")


def confirmed(data: dict, what: str) -> None:
    if data.get("confirm") is not True:
        raise AppError(f"Confirm before you {what}")


def clip(text: str, limit: int = LOG_LIMIT) -> str:
    return text if len(text) <= limit else "… (earlier output trimmed)\n" + text[-limit:]


class Terminal:
    """One pty running ``systemd-run --pty`` as the kiosk user; output kept in a bounded ring for polling readers."""
    BUFFER = 256 * 1024

    def __init__(self, argv: list[str], rows: int, cols: int, popen=subprocess.Popen):
        self.master, slave = pty.openpty()
        self.resize(rows, cols)
        try:
            self.proc = popen(argv, stdin=slave, stdout=slave, stderr=slave, close_fds=True, start_new_session=True,
                              preexec_fn=lambda: fcntl.ioctl(0, termios.TIOCSCTTY, 0))
        finally:
            os.close(slave)
        self.cond = threading.Condition()
        self.data = bytearray()
        self.start = 0  # absolute offset of data[0]
        self.exited = False
        self.last_seen = time.monotonic()
        threading.Thread(target=self._pump, daemon=True, name="opiha-term").start()

    def _pump(self):
        while True:
            try:
                ready, _, _ = select.select([self.master], [], [], 0.5)
                if ready:
                    chunk = os.read(self.master, 8192)
                    if not chunk:
                        break
                    with self.cond:
                        self.data += chunk
                        if len(self.data) > self.BUFFER:
                            drop = len(self.data) - self.BUFFER
                            del self.data[:drop]
                            self.start += drop
                        self.cond.notify_all()
                elif self.proc.poll() is not None:
                    break
            except OSError:
                break
        with self.cond:
            self.exited = True
            self.cond.notify_all()

    def resize(self, rows: int, cols: int):
        fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    def write(self, payload: bytes):
        if not self.exited:
            os.write(self.master, payload)

    def read(self, cursor: int, wait: float) -> dict:
        self.last_seen = time.monotonic()
        with self.cond:
            if cursor >= self.start + len(self.data) and not self.exited and wait > 0:
                self.cond.wait(wait)
            cursor = max(cursor, self.start)
            chunk = bytes(self.data[cursor - self.start:])
            end = self.start + len(self.data)
            return {"data": base64.b64encode(chunk).decode(), "from": cursor, "cursor": end, "exited": self.exited and cursor >= end}

    def close(self):
        try:
            if self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(3)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
        finally:
            try:
                os.close(self.master)
            except OSError:
                pass


class Host:
    def __init__(self, config: dict, *, runner=subprocess.run, proc: Path = Path("/proc"), sysfs: Path = Path("/sys"),
                 popen=subprocess.Popen, clock=time.monotonic, home_of=None):
        self.config = config
        self.run_ = runner
        self.proc = proc
        self.sysfs = sysfs
        self.popen = popen
        self.clock = clock
        self.user = config.get("host_user", "orangepi")
        self.terminal_enabled = bool(config.get("host_terminal", False))
        self.home_of = home_of or self._home_of
        self.terminals: dict[str, Terminal] = {}
        self.lock = threading.Lock()
        self.cpu_prev: tuple[int, int] | None = None
        self.net_prev: tuple[float, dict] | None = None

    # ----- plumbing -------------------------------------------------------------------------------------------
    def run(self, argv: list[str], *, timeout: int = 20, check: bool = False) -> tuple[int, str]:
        try:
            done = self.run_(argv, capture_output=True, text=True, timeout=timeout, errors="replace",
                             env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"})
        except FileNotFoundError as exc:
            raise AppError(f"{argv[0]} is not installed") from exc
        except subprocess.TimeoutExpired as exc:
            raise AppError(f"{argv[0]} timed out") from exc
        out = (done.stdout or "") + (done.stderr or "" if done.returncode else "")
        if check and done.returncode:
            raise AppError((out.strip().splitlines() or [f"{argv[0]} failed"])[-1][:300])
        return done.returncode, out

    def unsandboxed(self, argv: list[str], *, user: str | None = None, env: dict | None = None, timeout: int = 60) -> tuple[int, str]:
        """Run in PID 1's context (no manager sandbox) and return the command's real exit status and output."""
        prefix = ["systemd-run", "--wait", "--pipe", "--collect", "--quiet"]
        if user:
            prefix += ["-p", f"User={user}"]
        for key, value in (env or {}).items():
            prefix += ["-E", f"{key}={value}"]
        return self.run(prefix + argv, timeout=timeout)

    def later(self, argv: list[str], seconds: int = 2):
        """Run after the HTTP reply has left, so a restart or reboot cannot swallow its own answer."""
        self.run(["systemd-run", "--quiet", f"--on-active={seconds}s", "--collect"] + argv, check=True)

    def read(self, path: Path, limit: int = 1 << 20) -> str | None:
        try:
            with open(path, "r", errors="replace") as handle:
                return handle.read(limit)
        except OSError:
            return None

    @staticmethod
    def _home_of(user: str) -> str:
        import pwd
        try:
            return pwd.getpwnam(user).pw_dir
        except KeyError as exc:
            raise AppError("The configured host user does not exist") from exc

    # ----- statistics -----------------------------------------------------------------------------------------
    def cpu_percent(self) -> float | None:
        def sample():
            fields = (self.read(self.proc / "stat") or "").split("\n", 1)[0].split()[1:]
            values = [int(v) for v in fields[:8]] if len(fields) >= 4 else []
            return (values[3] + (values[4] if len(values) > 4 else 0), sum(values)) if values else None
        current = sample()
        if current is None:
            return None
        if self.cpu_prev is None or current[1] <= self.cpu_prev[1]:
            self.cpu_prev = current
            time.sleep(0.2)
            current = sample()
            if current is None or current[1] <= self.cpu_prev[1]:
                return None
        idle, total = current[0] - self.cpu_prev[0], current[1] - self.cpu_prev[1]
        self.cpu_prev = current
        return round(100 * (1 - idle / total), 1) if total > 0 else None

    def memory(self) -> dict:
        info = {}
        for line in (self.read(self.proc / "meminfo") or "").splitlines():
            key, _, rest = line.partition(":")
            if rest.split():
                info[key] = int(rest.split()[0]) * 1024
        return {"total": info.get("MemTotal"), "available": info.get("MemAvailable"), "cached": info.get("Cached"),
                "swap_total": info.get("SwapTotal"), "swap_free": info.get("SwapFree")}

    def disks(self) -> list[dict]:
        seen, rows = set(), []
        for mount in ("/", "/srv", "/var/lib/docker", "/boot/efi", "/boot"):
            try:
                st, vfs = os.stat(mount), os.statvfs(mount)
            except OSError:
                continue
            if st.st_dev in seen or not vfs.f_blocks:
                continue
            seen.add(st.st_dev)
            rows.append({"mount": mount, "total": vfs.f_blocks * vfs.f_frsize, "free": vfs.f_bavail * vfs.f_frsize})
        return rows

    def temperatures(self) -> list[dict]:
        rows = []
        root = self.sysfs / "class/thermal"
        try:
            zones = sorted(root.glob("thermal_zone*"), key=lambda p: int(re.sub(r"\D", "", p.name) or 0))
        except OSError:
            return rows
        for zone in zones:
            kind, raw = self.read(zone / "type", 128), self.read(zone / "temp", 32)
            try:
                rows.append({"name": (kind or zone.name).strip(), "celsius": round(int(raw) / 1000, 1)})
            except (TypeError, ValueError):
                continue
        return rows

    def frequencies(self) -> list[dict]:
        rows = []
        for policy in sorted((self.sysfs / "devices/system/cpu/cpufreq").glob("policy*")):
            cur, top = self.read(policy / "scaling_cur_freq", 32), self.read(policy / "cpuinfo_max_freq", 32)
            try:
                rows.append({"policy": policy.name, "mhz": int(cur) // 1000, "max_mhz": int(top) // 1000 if top else None})
            except (TypeError, ValueError):
                continue
        return rows

    def network(self) -> list[dict]:
        now, counters = self.clock(), {}
        for line in (self.read(self.proc / "net/dev") or "").splitlines()[2:]:
            name, _, rest = line.partition(":")
            name, fields = name.strip(), rest.split()
            if len(fields) >= 9 and name != "lo" and not re.match(r"(veth|br-|docker)", name):
                counters[name] = (int(fields[0]), int(fields[8]))
        previous = self.net_prev
        self.net_prev = (now, counters)
        addresses: dict[str, list[str]] = {}
        try:
            _, out = self.run(["ip", "-o", "-4", "addr", "show"], timeout=5)
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 4 and parts[2] == "inet":
                    addresses.setdefault(parts[1], []).append(parts[3])
        except AppError:
            pass
        rows = []
        for name, (rx, tx) in sorted(counters.items()):
            row = {"name": name, "rx": rx, "tx": tx, "addresses": addresses.get(name, []), "rx_rate": None, "tx_rate": None}
            if previous and name in previous[1] and now > previous[0]:
                span = now - previous[0]
                row["rx_rate"] = max(0, round((rx - previous[1][name][0]) / span))
                row["tx_rate"] = max(0, round((tx - previous[1][name][1]) / span))
            rows.append(row)
        return rows

    def identity(self) -> dict:
        pretty = next((line.split("=", 1)[1].strip().strip('"') for line in (self.read(Path("/etc/os-release")) or "").splitlines()
                       if line.startswith("PRETTY_NAME=")), None)
        uptime = (self.read(self.proc / "uptime", 64) or "").split()
        load = (self.read(self.proc / "loadavg", 64) or "").split()
        model = (self.read(self.sysfs / "firmware/devicetree/base/model", 128) or "").strip("\x00\n ")
        return {"hostname": os.uname().nodename, "os": pretty, "kernel": os.uname().release, "arch": os.uname().machine,
                "model": model or None, "uptime": float(uptime[0]) if uptime else None,
                "load": [float(v) for v in load[:3]], "cpus": os.cpu_count()}

    def stats(self, data: dict) -> dict:
        need(data, set())
        return {**self.identity(), "cpu_percent": self.cpu_percent(), "memory": self.memory(), "disks": self.disks(),
                "temperatures": self.temperatures(), "frequencies": self.frequencies(), "network": self.network()}

    def reboot_required(self) -> dict:
        flag = Path("/var/run/reboot-required")
        packages = (self.read(Path("/var/run/reboot-required.pkgs"), 8192) or "").split()
        return {"required": flag.exists(), "packages": packages[:20]}

    def overview(self, data: dict) -> dict:
        need(data, set())
        value = self.stats({})
        value["reboot"] = self.reboot_required()
        value["failed_services"] = [row["unit"] for row in self._units(failed=True)]
        try:
            value["docker"] = self._docker_summary()
        except AppError as exc:
            value["docker"] = {"error": str(exc)}
        value["job"] = self.update_job({"log": False})
        value["terminal_enabled"] = self.terminal_enabled
        value["desktop"] = {"mode": self._desktop_state()[0]}
        return value

    def hardware(self, data: dict) -> dict:
        need(data, set())
        _, blocks = self.run(["lsblk", "-J", "-o", "NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT,MODEL,TRAN"], timeout=10)
        try:
            devices = json.loads(blocks).get("blockdevices", [])
        except ValueError:
            devices = []
        usb = []
        try:
            usb = [line for line in self.run(["lsusb"], timeout=10)[1].splitlines() if line.strip()][:60]
        except AppError:
            pass
        return {"block_devices": devices, "usb": usb}

    # ----- systemd services -----------------------------------------------------------------------------------
    def _units(self, failed: bool = False) -> list[dict]:
        argv = ["systemctl", "list-units", "--type=service", "--no-legend", "--plain", "--no-pager"]
        argv += ["--failed"] if failed else ["--all"]
        _, out = self.run(argv, timeout=15)
        rows = []
        for line in out.splitlines():
            parts = line.replace("●", " ").split(None, 4)
            if len(parts) >= 4 and SERVICE_RE.fullmatch(parts[0]) and parts[1] != "not-found":
                rows.append({"unit": parts[0], "load": parts[1], "active": parts[2], "sub": parts[3],
                             "description": parts[4] if len(parts) > 4 else ""})
        return rows

    def services(self, data: dict) -> dict:
        need(data, set())
        rows = self._units()
        _, out = self.run(["systemctl", "list-unit-files", "--type=service", "--no-legend", "--plain", "--no-pager"], timeout=15)
        state = {p[0]: p[1] for p in (line.split() for line in out.splitlines()) if len(p) >= 2}
        for row in rows:
            row["enabled"] = state.get(row["unit"], "")
            row["lifeline"] = row["unit"] in LIFELINE
        return {"services": rows[:500]}

    def service(self, data: dict) -> dict:
        need(data, {"unit", "action", "confirm"}, {"unit", "action"})
        unit, action = data["unit"], data["action"]
        if not isinstance(unit, str) or not SERVICE_RE.fullmatch(unit) or action not in SERVICE_ACTIONS:
            raise AppError("Invalid service request")
        if unit in LIFELINE and action != "restart":
            raise AppError("This service keeps the host reachable; it can only be restarted")
        if action in {"stop", "restart", "disable"}:
            confirmed(data, f"{action} {unit}")
        if unit == OWN_UNIT:
            self.later(["systemctl", "restart", unit], 3)
            return {"unit": unit, "action": action, "deferred": True}
        if action in {"enable", "disable"}:
            code, out = self.unsandboxed(["systemctl", action, unit])
        else:
            code, out = self.run(["systemctl", action, unit], timeout=60)
        if code:
            raise AppError((out.strip().splitlines() or ["systemctl failed"])[-1][:300])
        return {"unit": unit, "action": action}

    def logs(self, data: dict) -> dict:
        need(data, {"unit", "lines", "priority", "boot"})
        argv = ["journalctl", "--no-pager", "-o", "short-iso"]
        unit = data.get("unit")
        if unit is not None:
            if not isinstance(unit, str) or not (SERVICE_RE.fullmatch(unit) or re.fullmatch(r"[A-Za-z0-9:_.@-]{1,100}\.(timer|socket|mount|target|scope)", unit)):
                raise AppError("Invalid unit")
            argv += ["-u", unit]
        lines = data.get("lines", 300)
        if type(lines) is not int or not 10 <= lines <= 2000:
            raise AppError("Choose 10 to 2000 lines")
        argv += ["-n", str(lines)]
        priority = data.get("priority")
        if priority is not None:
            if priority not in {"emerg", "alert", "crit", "err", "warning", "notice", "info", "debug"}:
                raise AppError("Invalid priority")
            argv += ["-p", priority]
        if data.get("boot") is True:
            argv.append("-b")
        _, out = self.run(argv, timeout=30)
        return {"logs": clip(out)}

    def power(self, data: dict) -> dict:
        need(data, {"action", "confirm"}, {"action"})
        if data["action"] not in {"reboot", "poweroff"}:
            raise AppError("Unknown power action")
        confirmed(data, data["action"] + " this host")
        self.later(["systemctl", data["action"]], 3)
        return {"scheduled": data["action"], "seconds": 3}

    # ----- Docker ---------------------------------------------------------------------------------------------
    def _docker(self, argv: list[str], timeout: int = 30) -> str:
        code, out = self.run(["docker"] + argv, timeout=timeout)
        if code:
            raise AppError((out.strip().splitlines() or ["docker failed"])[-1][:300])
        return out

    @staticmethod
    def _json_lines(text: str) -> list[dict]:
        rows = []
        for line in text.splitlines():
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, dict):
                rows.append(value)
        return rows

    def _docker_summary(self) -> dict:
        info = json.loads(self._docker(["info", "--format", "{{json .}}"], 15))
        return {"version": info.get("ServerVersion"), "containers": info.get("Containers"), "running": info.get("ContainersRunning"),
                "paused": info.get("ContainersPaused"), "stopped": info.get("ContainersStopped"), "images": info.get("Images"),
                "driver": info.get("Driver"), "root": info.get("DockerRootDir")}

    def docker(self, data: dict) -> dict:
        need(data, {"stats"})
        rows = self._json_lines(self._docker(["ps", "-a", "--no-trunc", "--format", "{{json .}}"]))
        stats = {}
        if data.get("stats") is True:
            for row in self._json_lines(self._docker(["stats", "--no-stream", "--no-trunc", "--format", "{{json .}}"], 45)):
                stats[row.get("ID", "")] = row
        containers = []
        for row in rows:
            labels = row.get("Labels") or ""
            cid = row.get("ID", "")
            live = stats.get(cid, {})
            containers.append({
                "id": cid[:12], "name": row.get("Names", ""), "image": row.get("Image", ""), "state": row.get("State", ""),
                "status": row.get("Status", ""), "ports": row.get("Ports", ""), "created": row.get("CreatedAt", ""),
                "managed": "opiha" in labels, "compose": next((p.split("=", 1)[1] for p in labels.split(",") if p.startswith("com.docker.compose.project=")), ""),
                "cpu": live.get("CPUPerc"), "memory": live.get("MemUsage"), "memory_percent": live.get("MemPerc"),
                "net": live.get("NetIO"), "block": live.get("BlockIO"), "pids": live.get("PIDs")})
        return {"summary": self._docker_summary(), "containers": containers}

    def container(self, data: dict) -> dict:
        need(data, {"id", "action", "confirm"}, {"id", "action"})
        cid, action = data["id"], data["action"]
        if not isinstance(cid, str) or not CONTAINER_RE.fullmatch(cid) or action not in {"start", "stop", "restart", "pause", "unpause", "kill", "remove"}:
            raise AppError("Invalid container request")
        if action in {"stop", "restart", "kill", "remove"}:
            confirmed(data, f"{action} a container")
        if action == "remove":
            labels = self._docker(["inspect", "--format", "{{json .Config.Labels}}", cid], 15)
            if "opiha" in labels:
                raise AppError("Remove managed applications from the Apps tab, which also handles their state")
            self._docker(["rm", "-f", cid], 60)
        else:
            self._docker([action, cid], 90)
        return {"id": cid, "action": action}

    def container_logs(self, data: dict) -> dict:
        need(data, {"id", "lines"}, {"id"})
        lines = data.get("lines", 300)
        if not isinstance(data["id"], str) or not CONTAINER_RE.fullmatch(data["id"]) or type(lines) is not int or not 10 <= lines <= 2000:
            raise AppError("Invalid log request")
        code, out = self.run(["docker", "logs", "--timestamps", "--tail", str(lines), data["id"]], timeout=30)
        if code:
            raise AppError((out.strip().splitlines() or ["docker logs failed"])[-1][:300])
        return {"logs": clip(out)}

    def images(self, data: dict) -> dict:
        need(data, set())
        rows = self._json_lines(self._docker(["images", "--format", "{{json .}}"]))
        used = {r.get("Image", "") for r in self._json_lines(self._docker(["ps", "-a", "--format", "{{json .}}"]))}
        out = [{"id": r.get("ID", ""), "repository": r.get("Repository", ""), "tag": r.get("Tag", ""), "size": r.get("Size", ""),
                "created": r.get("CreatedSince", ""),
                "in_use": f"{r.get('Repository')}:{r.get('Tag')}" in used or r.get("ID", "") in used} for r in rows]
        return {"images": out, "volumes": [r.get("Name", "") for r in self._json_lines(self._docker(["volume", "ls", "--format", "{{json .}}"]))],
                "networks": [r.get("Name", "") for r in self._json_lines(self._docker(["network", "ls", "--format", "{{json .}}"]))]}

    def image(self, data: dict) -> dict:
        need(data, {"id", "action", "confirm"}, {"id", "action"})
        if not isinstance(data["id"], str) or not IMAGE_RE.fullmatch(data["id"]) or data["action"] != "remove":
            raise AppError("Invalid image request")
        confirmed(data, "remove an image")
        self._docker(["image", "rm", data["id"]], 60)
        return {"id": data["id"], "removed": True}

    def docker_prune(self, data: dict) -> dict:
        need(data, {"confirm"})
        confirmed(data, "remove dangling images and stopped build leftovers")
        return {"output": clip(self._docker(["image", "prune", "-f"], 120))}

    # ----- updates --------------------------------------------------------------------------------------------
    def updates(self, data: dict) -> dict:
        need(data, set())
        _, out = self.unsandboxed(["apt", "list", "--upgradable"], timeout=60)
        packages = []
        for line in out.splitlines():
            match = re.match(r"([^/\s]+)/(\S+) (\S+) (\S+)(?: \[upgradable from: (\S+)\])?", line)
            if match:
                packages.append({"name": match[1], "suite": match[2], "version": match[3], "arch": match[4], "from": match[5]})
        _, held = self.run(["apt-mark", "showhold"], timeout=10)
        snaps = []
        code, listing = self.unsandboxed(["snap", "refresh", "--list"], timeout=60)
        if code == 0:
            for line in listing.splitlines()[1:]:
                parts = line.split()
                if len(parts) >= 3:
                    snaps.append({"name": parts[0], "version": parts[1], "revision": parts[2]})
        stamp = None
        for candidate in ("/var/lib/apt/periodic/update-success-stamp", "/var/cache/apt/pkgcache.bin"):
            try:
                stamp = int(os.stat(candidate).st_mtime)
                break
            except OSError:
                continue
        return {"packages": packages[:500], "held": held.split(), "snaps": snaps, "reboot": self.reboot_required(), "refreshed": stamp}

    def update_job(self, data: dict) -> dict:
        need(data, {"log"})
        code, out = self.run(["systemctl", "show", JOB_UNIT + ".service", "-p", "LoadState,ActiveState,SubState,Result,ExecMainStatus,ExecMainStartTimestampMonotonic,Description"], timeout=10)
        props = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
        if props.get("LoadState") != "loaded":
            return {"state": "none"}
        running = props.get("SubState") in {"running", "start", "start-pre"}
        ok = props.get("Result") == "success" and props.get("ExecMainStatus") == "0"
        log = self.run(["journalctl", "-u", JOB_UNIT + ".service", "--no-pager", "-o", "cat", "-n", "400"], timeout=15)[1] if data.get("log", True) else ""
        return {"state": "running" if running else "succeeded" if ok else "failed", "description": props.get("Description"),
                "exit": props.get("ExecMainStatus"), "log": clip(log, 64 * 1024)}

    def update_start(self, data: dict) -> dict:
        need(data, {"kind", "confirm"}, {"kind"})
        if data["kind"] not in JOB_KINDS:
            raise AppError("Unknown update operation")
        confirmed(data, "start this update")
        if self.update_job({}).get("state") == "running":
            raise AppError("Another host update is still running")
        self.run(["systemctl", "stop", JOB_UNIT + ".service"], timeout=30)
        argv, description = JOB_KINDS[data["kind"]]
        self.run(["systemd-run", "--quiet", f"--unit={JOB_UNIT}", f"--description={description}", "-p", "RemainAfterExit=yes",
                  "-E", "DEBIAN_FRONTEND=noninteractive", "-E", "LC_ALL=C"] + argv, check=True, timeout=30)
        return {"started": data["kind"]}

    # ----- kiosk / desktop ------------------------------------------------------------------------------------
    def _user_systemctl(self, *args: str, timeout: int = 30) -> tuple[int, str]:
        return self.run(["systemctl", "--user", f"--machine={self.user}@.host", *args], timeout=timeout)

    def _markers(self) -> set[str]:
        home = self.home_of(self.user)
        code, out = self.unsandboxed(["ls", "-1", f"{home}/.config/opiha"], user=self.user, timeout=15)
        return set(out.split()) if code == 0 else set()

    def _desktop_state(self) -> tuple[str, dict, str]:
        """Mode (kiosk, desktop, no-session or unavailable), per-unit state, and a failure detail."""
        code, out = self._user_systemctl("show", *KIOSK_UNITS.values(), "-p", "Id,ActiveState,UnitFileState", timeout=15)
        if code:
            return "unavailable", {}, (out.strip().splitlines() or [""])[-1][:200]
        units = {}
        for block in out.strip().split("\n\n"):
            props = dict(line.split("=", 1) for line in block.splitlines() if "=" in line)
            for key, unit in KIOSK_UNITS.items():
                if props.get("Id") == unit:
                    units[key] = {"active": props.get("ActiveState"), "enabled": props.get("UnitFileState")}
        if units.get("kiosk", {}).get("active") in {"active", "activating"}:
            return "kiosk", units, ""
        session, _ = self.run(["pgrep", "-u", self.user, "-x", "xfce4-session"], timeout=5)
        return ("desktop" if session == 0 else "no-session"), units, ""

    def desktop(self, data: dict) -> dict:
        need(data, set())
        mode, units, detail = self._desktop_state()
        try:
            markers = self._markers()
        except AppError:
            markers = set()
        return {"mode": mode, "units": units, "detail": detail, "boot": "desktop" if "kiosk.disabled" in markers else "kiosk"}

    def desktop_mode(self, data: dict) -> dict:
        need(data, {"mode", "boot", "confirm"})
        mode, boot = data.get("mode"), data.get("boot")
        if mode not in {None, "kiosk", "desktop"} or boot not in {None, "kiosk", "desktop"} or (mode is None and boot is None):
            raise AppError("Choose a mode and/or a boot preference")
        if mode == "kiosk":
            if boot == "desktop":
                raise AppError("Starting the kiosk now makes it the boot default; leave the boot preference out")
            boot = "kiosk"  # kiosk.disabled would otherwise stop the unit from starting
        home = self.home_of(self.user)
        config = f"{home}/.config/opiha"
        if boot:
            self.unsandboxed(["install", "-d", "-o", self.user, "-m", "0755", config], timeout=15)
            for marker in ("kiosk.disabled", "kiosk-controls.disabled"):
                argv = ["touch", f"{config}/{marker}"] if boot == "desktop" else ["rm", "-f", f"{config}/{marker}"]
                code, out = self.unsandboxed(argv, user=self.user, timeout=15)
                if code:
                    raise AppError("Could not update the boot preference")
        if mode == "desktop":
            confirmed(data, "leave the kiosk")
            self.later(["systemctl", "--user", f"--machine={self.user}@.host", "stop", KIOSK_UNITS["controls"], KIOSK_UNITS["kiosk"]], 2)
        elif mode == "kiosk":
            self.later(["systemctl", "--user", f"--machine={self.user}@.host", "start", KIOSK_UNITS["kiosk"], KIOSK_UNITS["controls"]], 1)
        return {"mode": mode, "boot": boot}

    def display(self, data: dict) -> dict:
        need(data, {"action"}, {"action"})
        if data["action"] not in {"off", "on"}:
            raise AppError("Unknown display action")
        env = {"DISPLAY": ":0", "XAUTHORITY": f"{self.home_of(self.user)}/.Xauthority"}
        argv = ["xset", "dpms", "force", data["action"]]
        code, out = self.unsandboxed(argv, user=self.user, env=env, timeout=15)
        if code:
            raise AppError("The display server did not accept the request")
        return {"display": data["action"]}

    # ----- terminal -------------------------------------------------------------------------------------------
    def _terminal(self, ident) -> Terminal:
        if not self.terminal_enabled:
            raise AppError("The host terminal is off. Enable it on the host: sudo python3 /opt/orangepi-apps/current/bin/opiha-apps host-terminal on")
        with self.lock:
            term = self.terminals.get(ident) if isinstance(ident, str) else None
        if term is None:
            raise AppError("That terminal session has ended")
        return term

    def reap(self):
        cutoff = self.clock() - 60
        with self.lock:
            stale = [i for i, t in self.terminals.items() if t.last_seen < cutoff]
            dead = [self.terminals.pop(i) for i in stale]
        for term in dead:
            term.close()

    def term_open(self, data: dict) -> dict:
        need(data, {"rows", "cols"})
        if not self.terminal_enabled:
            raise AppError("The host terminal is off. Enable it on the host: sudo python3 /opt/orangepi-apps/current/bin/opiha-apps host-terminal on")
        rows, cols = data.get("rows", 24), data.get("cols", 80)
        if type(rows) is not int or type(cols) is not int or not 2 <= rows <= 200 or not 10 <= cols <= 500:
            raise AppError("Invalid terminal size")
        self.reap()
        with self.lock:
            if len(self.terminals) >= 3:
                raise AppError("Close an existing terminal first (3 at once)")
        home = self.home_of(self.user)
        argv = ["systemd-run", "--pty", "--wait", "--collect", "--quiet", "-p", f"User={self.user}", "-p", "PAMName=login",
                "-p", f"WorkingDirectory={home}", "-E", "TERM=xterm-256color", "-E", "COLORTERM=truecolor", "/bin/bash", "-l"]
        term = Terminal(argv, rows, cols, self.popen)
        ident = secrets.token_urlsafe(12)
        with self.lock:
            self.terminals[ident] = term
        return {"id": ident, "user": self.user}

    def term_io(self, data: dict) -> dict:
        need(data, {"id", "input", "rows", "cols", "cursor", "wait"}, {"id", "cursor"})
        self.reap()
        term = self._terminal(data["id"])
        cursor, wait = data["cursor"], data.get("wait", 1.0)
        if type(cursor) is not int or cursor < 0 or not isinstance(wait, (int, float)) or isinstance(wait, bool) or not 0 <= wait <= 5:
            raise AppError("Invalid terminal read")
        if "rows" in data or "cols" in data:
            rows, cols = data.get("rows"), data.get("cols")
            if type(rows) is not int or type(cols) is not int or not 2 <= rows <= 200 or not 10 <= cols <= 500:
                raise AppError("Invalid terminal size")
            term.resize(rows, cols)
        if data.get("input"):
            try:
                payload = base64.b64decode(data["input"], validate=True)
            except (binascii.Error, TypeError, ValueError) as exc:
                raise AppError("Invalid terminal input") from exc
            if len(payload) > 16384:
                raise AppError("Terminal input is too large")
            term.write(payload)
        return term.read(cursor, wait)

    def term_close(self, data: dict) -> dict:
        need(data, {"id"}, {"id"})
        with self.lock:
            term = self.terminals.pop(data["id"], None) if isinstance(data["id"], str) else None
        if term:
            term.close()
        return {"closed": term is not None}

    def close(self):
        with self.lock:
            terms, self.terminals = list(self.terminals.values()), {}
        for term in terms:
            term.close()


OPERATIONS = ("overview", "stats", "hardware", "services", "service", "logs", "power", "docker", "container", "container_logs",
              "images", "image", "docker_prune", "updates", "update_start", "update_job", "desktop", "desktop_mode", "display",
              "term_open", "term_io", "term_close")


def dispatch(host: Host, operation: str, data: dict) -> dict:
    if operation not in OPERATIONS:
        raise AppError("Unknown host operation")
    return getattr(host, operation)(data)
