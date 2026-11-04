import copy
import json
from pathlib import Path
import subprocess
import shutil

import pytest

from paseo_fleet import inventory, render
from paseo_fleet.cli import build_artifacts, main

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "config" / "paseo-fleet.example.json"


@pytest.fixture
def doc():
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


@pytest.fixture
def inv():
    return inventory.load(EXAMPLE)


def host(inv, hid):
    return next(h for h in inv.hosts if h.id == hid)


def test_example_inventory_is_valid(inv):
    assert inv.hub.id == "workstation"
    assert {h.platform for h in inv.hosts} == {"windows", "docker", "linux", "macos"}


@pytest.mark.parametrize("mutate,message", [
    (lambda d: d["hosts"][2].update(ssh="user@host; rm -rf /"), "ssh must look like"),
    (lambda d: d["hosts"][1].update(daemon_port=6767), "already used"),
    (lambda d: d["agents"].append("evil-pkg"), "must be pinned"),
    (lambda d: d.update(paseo_version="latest"), "exact version"),
    (lambda d: d["hosts"][0].pop("hub"), "exactly one host"),
    (lambda d: d["hosts"][2].update(workspace_root="/tmp/$(id)"), "unsafe"),
    (lambda d: d["hosts"][2].update(limits={"memory": "lots"}), "limits.memory"),
])
def test_invalid_inventories_are_rejected(doc, mutate, message):
    mutate(doc)
    with pytest.raises(inventory.InventoryError, match=message):
        inventory.parse(copy.deepcopy(doc))


def test_posix_linux_script_is_pinned_verified_and_limited(inv):
    script = render.render_posix(host(inv, "raspberrypi"), inv)
    assert "node-v$NODE_VER-$OS-$ARCH" in script and "NODE_VER=22.22.0" in script
    assert "checksum mismatch" in script
    assert "'@getpaseo/cli@0.15.0'" in script or "@getpaseo/cli@0.15.0" in script
    assert "@openai/codex@0.166.0" in script
    assert "Nice=10" in script and "MemoryMax=2G" in script
    assert "systemctl --user" in script and "127.0.0.1:$PORT" in script
    assert "@@" not in script


def test_macos_uses_launchd(inv):
    script = render.render_posix(host(inv, "macbook"), inv)
    assert "launchctl bootstrap" in script and "systemctl" not in script
    assert "darwin" in script


def test_windows_script_registers_scheduled_task(inv):
    script = render.render_windows(host(inv, "workstation"), inv)
    assert "Register-ScheduledTask" in script and "Get-FileHash" in script
    assert "@@" not in script


def test_env_content_is_embedded_only_encoded(inv):
    script = render.render_posix(host(inv, "raspberrypi"), inv, env_content="OPENAI_API_KEY=sk-secret\n")
    assert "sk-secret" not in script and "base64 -d" in script


def test_docker_files_bind_loopback_only(inv):
    files = render.render_docker_files(host(inv, "workstation-docker"), inv, has_agent_env=False)
    assert '"127.0.0.1:6768:6767"' in files["compose.yaml"]
    assert "mem_limit: 4g" in files["compose.yaml"]
    assert "FROM ghcr.io/getpaseo/paseo:0.15.0" in files["Dockerfile"]


def test_docker_workspace_mount_is_bind_mounted(doc):
    doc["hosts"][1]["workspace_mount"] = "G:\\agents"
    h = host(inventory.parse(doc), "workstation-docker")
    files = render.render_docker_files(h, inventory.parse(doc), has_agent_env=False)
    assert '- "G:/agents:/workspace"' in files["compose.yaml"]
    assert "\n  workspace:" not in files["compose.yaml"]
    assert render.workspace_root(h) == "/workspace"


def test_connection_strings(inv):
    assert render.connection(host(inv, "raspberrypi")) == "ssh://USER@raspberrypi.example?daemonPort=6767"
    assert render.connection(host(inv, "workstation")) == "127.0.0.1:6767"
    assert render.connection(host(inv, "workstation-docker"), "p@ss") == "tcp://127.0.0.1:6768?password=p%40ss"


def test_plan_redacts_secrets(inv, tmp_path, capsys):
    env = tmp_path / "agent.env"
    env.write_text("TOKEN=super-secret\n", encoding="utf-8")
    doc = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    doc["hosts"][2]["env_file"] = str(env)
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert main(["--inventory", str(path), "plan", "--host", "raspberrypi"]) == 0
    out = capsys.readouterr().out
    assert "super-secret" not in out and "daemon.env" in out


def test_build_artifacts_does_not_create_secrets_on_plan(inv, tmp_path):
    h = host(inv, "workstation-docker")
    art = build_artifacts(inv, h, create_secrets=False)
    assert "<generated-on-provision>" in art["files"][".env"]


@pytest.mark.skipif(shutil.which("sh") is None, reason="sh not available")
def test_generated_posix_scripts_parse(inv, tmp_path):
    for hid in ("raspberrypi", "macbook"):
        script = tmp_path / f"{hid}.sh"
        script.write_text(render.render_posix(host(inv, hid), inv), encoding="utf-8", newline="\n")
        assert subprocess.run(["sh", "-n", str(script)], capture_output=True).returncode == 0
