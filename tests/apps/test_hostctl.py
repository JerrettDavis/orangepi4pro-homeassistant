"""Host control: argument vectors, validation, parsing. A fake runner stands in for systemd, Docker and apt."""
from __future__ import annotations
import base64
import json
import subprocess
import sys
import time
import pytest
from opiha_apps import hostctl
from opiha_apps.common import AppError, defaults, validate_config
from opiha_apps.hostctl import Host, dispatch

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="Linux host control (pty, fcntl)")


class Runner:
    """Match the first scripted rule whose words all appear in the argv; record every call."""
    def __init__(self):
        self.calls, self.rules = [], []

    def when(self, *words, code=0, out=""):
        self.rules.append((words, code, out))

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        for words, code, out in self.rules:
            if all(w in argv for w in words):
                return subprocess.CompletedProcess(argv, code, out, "")
        return subprocess.CompletedProcess(argv, 0, "", "")

    def ran(self, *words):
        return [c for c in self.calls if all(w in c for w in words)]


@pytest.fixture
def runner():
    return Runner()


@pytest.fixture
def host(runner, tmp_path):
    cfg = {**defaults(), "host_terminal": False, "host_user": "orangepi"}
    return Host(cfg, runner=runner, proc=tmp_path / "proc", sysfs=tmp_path / "sys", home_of=lambda user: "/home/" + user)


def test_operations_have_handlers():
    for name in hostctl.OPERATIONS:
        assert callable(getattr(Host, name))


def test_unknown_operation_and_extra_fields_rejected(host):
    with pytest.raises(AppError):
        dispatch(host, "shell", {})
    with pytest.raises(AppError):
        dispatch(host, "docker", {"stats": True, "x": 1})
    with pytest.raises(AppError):
        dispatch(host, "service", {"unit": "ssh.service"})


@pytest.mark.parametrize("unit", ["../x.service", "a b.service", "x;rm.service", "-rf.service", "plain", "x.service\n", ""])
def test_service_unit_names_validated(host, unit):
    with pytest.raises(AppError):
        host.service({"unit": unit, "action": "restart", "confirm": True})


def test_lifeline_services_can_only_restart(host, runner):
    for unit in ("ssh.service", "orangepi-apps.service", "NetworkManager.service"):
        for action in ("stop", "disable"):
            with pytest.raises(AppError, match="reachable"):
                host.service({"unit": unit, "action": action, "confirm": True})
    host.service({"unit": "ssh.service", "action": "restart", "confirm": True})
    assert runner.ran("systemctl", "restart", "ssh.service")


def test_own_unit_restart_is_deferred_not_immediate(host, runner):
    result = host.service({"unit": "orangepi-apps.service", "action": "restart", "confirm": True})
    assert result["deferred"] is True
    call = runner.ran("orangepi-apps.service")[0]
    assert call[0] == "systemd-run" and any(a.startswith("--on-active=") for a in call)
    assert "--timer-property=AccuracySec=100ms" in call  # transient timers otherwise fire up to a minute late


def test_destructive_service_actions_need_confirmation(host, runner):
    with pytest.raises(AppError, match="Confirm"):
        host.service({"unit": "docker.service", "action": "stop"})
    assert not runner.calls
    host.service({"unit": "cups.service", "action": "start"})
    assert runner.ran("systemctl", "start", "cups.service")


def test_enable_runs_unsandboxed_with_exit_status(host, runner):
    host.service({"unit": "cups.service", "action": "enable"})
    call = runner.ran("enable", "cups.service")[0]
    assert call[:2] == ["systemd-run", "--wait"] and "--pipe" in call


def test_service_failure_reports_last_line(host, runner):
    runner.when("start", "bad.service", code=5, out="Failed to start bad.service: Unit bad.service not found.\n")
    with pytest.raises(AppError, match="not found"):
        host.service({"unit": "bad.service", "action": "start"})


def test_services_listing_merges_unit_files(host, runner):
    runner.when("list-units", out=(
        "  ssh.service        loaded    active running OpenBSD Secure Shell server\n"
        "● dnsmasq.service    loaded    failed failed  dnsmasq - A lightweight DHCP and caching DNS server\n"
        "  ghost.service      not-found inactive dead  ghost.service\n"))
    runner.when("list-unit-files", out="ssh.service enabled enabled\ndnsmasq.service disabled enabled\n")
    rows = {r["unit"]: r for r in host.services({})["services"]}
    assert set(rows) == {"ssh.service", "dnsmasq.service"}
    assert rows["ssh.service"]["enabled"] == "enabled" and rows["ssh.service"]["lifeline"] is True
    assert rows["dnsmasq.service"]["active"] == "failed" and rows["dnsmasq.service"]["description"].startswith("dnsmasq")


def test_power_needs_confirm_and_is_deferred(host, runner):
    with pytest.raises(AppError):
        host.power({"action": "reboot"})
    with pytest.raises(AppError):
        host.power({"action": "halt", "confirm": True})
    assert not runner.calls
    assert host.power({"action": "reboot", "confirm": True})["scheduled"] == "reboot"
    call = runner.calls[0]
    assert call[0] == "systemd-run" and call[-2:] == ["systemctl", "reboot"] and any(a.startswith("--on-active=") for a in call)


@pytest.mark.parametrize("data", [{"lines": 5}, {"lines": 99999}, {"priority": "loud"}, {"unit": "x;y.service"}, {"unit": "../etc"}, {"lines": "10"}])
def test_journal_arguments_validated(host, data):
    with pytest.raises(AppError):
        host.logs(data)


def test_journal_builds_fixed_vector(host, runner):
    runner.when("journalctl", out="line\n")
    assert host.logs({"unit": "docker.service", "lines": 50, "priority": "err", "boot": True})["logs"] == "line\n"
    assert runner.calls[0][-7:] == ["-u", "docker.service", "-n", "50", "-p", "err", "-b"]


DOCKER_PS = "\n".join(json.dumps(r) for r in [
    {"ID": "a" * 64, "Names": "homeassistant", "Image": "ghcr.io/home-assistant/home-assistant:2026.9.3", "State": "running", "Status": "Up 2 hours",
     "Ports": "", "CreatedAt": "x", "Labels": "com.docker.compose.project=opiha,org.opiha.role=ha"},
    {"ID": "b" * 64, "Names": "scratch", "Image": "alpine", "State": "exited", "Status": "Exited (0)", "Ports": "", "CreatedAt": "y", "Labels": ""}])
DOCKER_STATS = json.dumps({"ID": "a" * 64, "CPUPerc": "1.5%", "MemUsage": "512MiB / 5GiB", "MemPerc": "9%", "NetIO": "1kB / 2kB", "BlockIO": "0B / 0B", "PIDs": "40"})


def test_docker_listing_merges_stats_and_flags_managed(host, runner):
    runner.when("docker", "info", out=json.dumps({"ServerVersion": "29.6.1", "Containers": 2, "ContainersRunning": 1, "Images": 3}))
    runner.when("docker", "ps", out=DOCKER_PS)
    runner.when("docker", "stats", out=DOCKER_STATS)
    result = host.docker({"stats": True})
    ha, scratch = result["containers"]
    assert ha["managed"] is True and ha["compose"] == "opiha" and ha["cpu"] == "1.5%" and ha["id"] == "a" * 12
    assert scratch["managed"] is False and scratch["cpu"] is None
    assert result["summary"]["version"] == "29.6.1"


@pytest.mark.parametrize("cid", ["-f", "--all", "a b", "x;y", "../x", "", "a" * 129])
def test_container_ids_validated(host, runner, cid):
    with pytest.raises(AppError):
        host.container({"id": cid, "action": "start"})
    assert not runner.calls


def test_container_remove_blocked_for_managed_apps(host, runner):
    runner.when("inspect", out='{"org.opiha.apps.owner":"x"}')
    with pytest.raises(AppError, match="Apps tab"):
        host.container({"id": "nodered", "action": "remove", "confirm": True})
    assert not runner.ran("rm")


def test_container_remove_and_stop_need_confirm(host, runner):
    with pytest.raises(AppError, match="Confirm"):
        host.container({"id": "scratch", "action": "remove"})
    runner.when("inspect", out="{}")
    host.container({"id": "scratch", "action": "remove", "confirm": True})
    assert runner.ran("docker", "rm", "-f", "scratch")
    host.container({"id": "scratch", "action": "start"})
    assert runner.ran("docker", "start", "scratch")


def test_image_and_prune_need_confirm(host, runner):
    with pytest.raises(AppError):
        host.image({"id": "abcdef123456", "action": "remove"})
    with pytest.raises(AppError):
        host.image({"id": "-f", "action": "remove", "confirm": True})
    with pytest.raises(AppError):
        host.docker_prune({})
    host.image({"id": "abcdef123456", "action": "remove", "confirm": True})
    assert runner.ran("docker", "image", "rm", "abcdef123456")


APT = """Listing...
openssl/jammy-updates,jammy-security 3.0.2-0ubuntu1.20 arm64 [upgradable from: 3.0.2-0ubuntu1.18]
tzdata/jammy-updates 2026a-0ubuntu0.22.04 all [upgradable from: 2025b-0ubuntu0.22.04]
"""


def test_updates_parsing(host, runner):
    runner.when("apt", "list", out=APT)
    runner.when("apt-mark", out="wiringpi\n")
    runner.when("snap", "refresh", "--list", out="Name  Version  Rev  Size  Publisher  Notes\ngnome-46-2404  0+git  176  589MB  canonical**  -\n")
    info = host.updates({})
    assert [p["name"] for p in info["packages"]] == ["openssl", "tzdata"]
    assert info["packages"][0]["from"] == "3.0.2-0ubuntu1.18" and info["held"] == ["wiringpi"]
    assert info["snaps"] == [{"name": "gnome-46-2404", "version": "0+git", "revision": "176"}]


def test_update_job_lifecycle(host, runner):
    runner.when("systemctl", "show", out="LoadState=not-found\n")
    assert host.update_job({})["state"] == "none"
    with pytest.raises(AppError):
        host.update_start({"kind": "rm -rf /", "confirm": True})
    with pytest.raises(AppError, match="Confirm"):
        host.update_start({"kind": "apt-upgrade"})
    host.update_start({"kind": "apt-upgrade", "confirm": True})
    start = runner.ran("--unit=" + hostctl.JOB_UNIT)[0]
    assert start[0] == "systemd-run" and "DEBIAN_FRONTEND=noninteractive" in start and start[-1] == "upgrade"
    assert "--force-confold" in " ".join(start)
    assert runner.ran("reset-failed", hostctl.JOB_UNIT + ".service")


def test_update_job_refuses_when_running_and_reports_outcome(host, runner):
    runner.rules.clear()
    runner.when("systemctl", "show", out="LoadState=loaded\nActiveState=active\nSubState=running\nResult=success\nExecMainStatus=0\nDescription=Upgrade packages\n")
    runner.when("journalctl", out="Reading package lists\n")
    assert host.update_job({})["state"] == "running"
    with pytest.raises(AppError, match="still running"):
        host.update_start({"kind": "apt-update", "confirm": True})
    runner.rules.clear()
    runner.when("systemctl", "show", out="LoadState=loaded\nActiveState=active\nSubState=exited\nResult=exit-code\nExecMainStatus=100\nDescription=Upgrade packages\n")
    assert host.update_job({"log": False})["state"] == "failed"


KIOSK_SHOW = """Id=orangepi-homeassistant-kiosk.service
ActiveState=active
UnitFileState=enabled

Id=orangepi-homeassistant-kiosk-controls.service
ActiveState=active
UnitFileState=enabled

Id=orangepi-homeassistant-keyboard.service
ActiveState=inactive
UnitFileState=enabled
"""


def test_desktop_status_modes(host, runner):
    runner.when("--machine=orangepi@.host", "show", out=KIOSK_SHOW)
    runner.when("ls", out="kiosk.disabled\nkiosk-controls.position\n")
    info = host.desktop({})
    assert info["mode"] == "kiosk" and info["boot"] == "desktop" and info["units"]["keyboard"]["active"] == "inactive"
    runner.rules.clear()
    runner.when("--machine=orangepi@.host", "show", out=KIOSK_SHOW.replace("ActiveState=active", "ActiveState=inactive", 1))
    runner.when("pgrep", code=0, out="1234")
    assert host.desktop({})["mode"] == "desktop"
    runner.rules.clear()
    runner.when("--machine=orangepi@.host", "show", code=1, out="Failed to connect to bus")
    assert host.desktop({})["mode"] == "unavailable"


def test_switch_to_desktop_is_confirmed_and_deferred(host, runner):
    with pytest.raises(AppError):
        host.desktop_mode({"mode": "desktop"})
    host.desktop_mode({"mode": "desktop", "confirm": True})
    call = runner.calls[-1]
    assert call[0] == "systemd-run" and "stop" in call and "orangepi-homeassistant-kiosk.service" in call and any(a.startswith("--on-active") for a in call)


def test_kiosk_mode_clears_boot_markers_and_rejects_conflict(host, runner):
    with pytest.raises(AppError):
        host.desktop_mode({"mode": "kiosk", "boot": "desktop"})
    host.desktop_mode({"mode": "kiosk"})
    assert runner.ran("rm", "-f", "/home/orangepi/.config/opiha/kiosk.disabled")
    assert runner.ran("start", "orangepi-homeassistant-kiosk.service")
    with pytest.raises(AppError):
        host.desktop_mode({})


def test_boot_preference_desktop_touches_markers_as_kiosk_user(host, runner):
    host.desktop_mode({"boot": "desktop"})
    touch = runner.ran("touch", "/home/orangepi/.config/opiha/kiosk.disabled")[0]
    assert "User=orangepi" in touch and touch[0] == "systemd-run"
    assert not runner.ran("stop")


def test_display_action_validated_and_runs_as_kiosk_user(host, runner):
    with pytest.raises(AppError):
        host.display({"action": "explode"})
    host.display({"action": "off"})
    call = runner.ran("xset")[0]
    assert "User=orangepi" in call and "DISPLAY=:0" in call and call[-4:] == ["xset", "dpms", "force", "off"]


def test_stats_from_proc_and_sysfs(host, tmp_path):
    proc, sysfs = tmp_path / "proc", tmp_path / "sys"
    (proc / "net").mkdir(parents=True)
    (proc / "stat").write_text("cpu  100 0 100 800 0 0 0 0 0 0\n")
    (proc / "meminfo").write_text("MemTotal: 4194304 kB\nMemAvailable: 1048576 kB\nCached: 2048 kB\nSwapTotal: 1024 kB\nSwapFree: 512 kB\n")
    (proc / "loadavg").write_text("0.50 0.40 0.30 1/200 99\n")
    (proc / "uptime").write_text("3600.5 100.0\n")
    (proc / "net/dev").write_text("Inter-|\n face |\n  lo: 1 0 0 0 0 0 0 0 1 0 0 0 0 0 0 0\neth0: 1000 0 0 0 0 0 0 0 2000 0 0 0 0 0 0 0\nveth1: 5 0 0 0 0 0 0 0 5 0 0 0 0 0 0 0\n")
    zone = sysfs / "class/thermal/thermal_zone0"
    zone.mkdir(parents=True)
    (zone / "type").write_text("cpu_thermal\n")
    (zone / "temp").write_text("52500\n")
    host.cpu_prev = (700, 800)  # previous sample, so the delta is computed without sleeping
    stats = host.stats({})
    assert stats["cpu_percent"] == 50.0
    assert stats["memory"]["total"] == 4 * 1024**3 and stats["memory"]["available"] == 1024**3
    assert stats["temperatures"] == [{"name": "cpu_thermal", "celsius": 52.5}]
    assert [n["name"] for n in stats["network"]] == ["eth0"]
    assert stats["uptime"] == 3600.5 and stats["load"] == [0.5, 0.4, 0.3]


def test_terminal_is_off_by_default(host):
    with pytest.raises(AppError, match="terminal is off"):
        host.term_open({"rows": 24, "cols": 80})
    with pytest.raises(AppError, match="terminal is off"):
        host.term_io({"id": "x", "cursor": 0})


def terminal_host(runner, tmp_path, clock=time.monotonic):
    cfg = {**defaults(), "host_terminal": True, "host_user": "orangepi"}

    def popen(argv, **kwargs):
        assert argv[0] == "systemd-run" and "--pty" in argv and "User=orangepi" in argv and argv[-2:] == ["/bin/bash", "-l"]
        return subprocess.Popen(["/bin/sh", "-c", "echo ready; exec cat"], **kwargs)
    return Host(cfg, runner=runner, proc=tmp_path, sysfs=tmp_path, popen=popen, clock=clock, home_of=lambda u: "/home/" + u)


def read_until(host, sid, needle, cursor=0):
    seen, deadline = b"", time.monotonic() + 5
    while needle not in seen and time.monotonic() < deadline:
        r = host.term_io({"id": sid, "cursor": cursor, "wait": 0.3})
        seen += base64.b64decode(r["data"])
        cursor = r["cursor"]
    return seen, cursor


def test_terminal_round_trip_resize_and_close(runner, tmp_path):
    host = terminal_host(runner, tmp_path)
    sid = host.term_open({"rows": 30, "cols": 100})["id"]
    out, cursor = read_until(host, sid, b"ready")
    assert b"ready" in out
    host.term_io({"id": sid, "cursor": cursor, "wait": 0, "input": base64.b64encode(b"hello\n").decode(), "rows": 40, "cols": 120})
    out, cursor = read_until(host, sid, b"hello", cursor)
    assert b"hello" in out
    assert host.terminals[sid].proc.poll() is None
    assert host.term_close({"id": sid}) == {"closed": True}
    assert host.term_close({"id": sid}) == {"closed": False}
    with pytest.raises(AppError, match="ended"):
        host.term_io({"id": sid, "cursor": 0})
    host.close()


def test_terminal_input_validation_and_session_cap(runner, tmp_path):
    host = terminal_host(runner, tmp_path)
    ids = [host.term_open({"rows": 24, "cols": 80})["id"] for _ in range(3)]
    with pytest.raises(AppError, match="3 at once"):
        host.term_open({"rows": 24, "cols": 80})
    with pytest.raises(AppError):
        host.term_io({"id": ids[0], "cursor": 0, "input": "not base64!!"})
    with pytest.raises(AppError):
        host.term_io({"id": ids[0], "cursor": 0, "input": base64.b64encode(b"x" * 20000).decode()})
    with pytest.raises(AppError):
        host.term_open({"rows": 0, "cols": 80})
    host.close()
    assert not host.terminals


def test_abandoned_terminals_are_reaped(runner, tmp_path):
    now = [1000.0]
    host = terminal_host(runner, tmp_path, clock=lambda: now[0])
    sid = host.term_open({"rows": 24, "cols": 80})["id"]
    host.terminals[sid].last_seen = 1000.0
    now[0] = 1030.0
    host.reap()
    assert sid in host.terminals
    now[0] = 1100.0
    host.reap()
    assert sid not in host.terminals


def test_terminal_buffer_is_bounded_and_reports_gap(runner, tmp_path):
    host = terminal_host(runner, tmp_path)
    sid = host.term_open({"rows": 24, "cols": 80})["id"]
    term = host.terminals[sid]
    term.BUFFER = 1024
    with term.cond:
        term.data += b"x" * 5000
        drop = len(term.data) - 1024
        del term.data[:drop]
        term.start += drop
    result = term.read(0, 0)
    assert result["from"] == term.start > 0 and len(base64.b64decode(result["data"])) == 1024
    host.close()


def test_config_new_keys_optional_and_validated():
    legacy = defaults()
    assert validate_config(dict(legacy))["host_terminal"] is False
    assert validate_config({**legacy, "host_terminal": True, "host_user": "kiosk"})["host_user"] == "kiosk"
    for bad in ({"host_terminal": "yes"}, {"host_user": "Bad User"}, {"host_user": "root; id"}):
        with pytest.raises(AppError):
            validate_config({**legacy, **bad})
