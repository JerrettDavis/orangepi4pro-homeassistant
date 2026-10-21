"""Opt-in native manager installation; never changes boot, networking or existing units."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import tempfile
from . import __version__
from .common import AppError, atomic, checked_path, defaults, initialize, read_json, read_token, stamp, write_json

SOURCE = Path(__file__).resolve().parents[2]
SERVICE = """[Unit]
Description=Orange Pi native app manager (not Home Assistant Supervisor)
After=docker.service network.target
Wants=docker.service

[Service]
Type=simple
ExecStart=/usr/bin/python3 /opt/orangepi-apps/current/bin/opiha-apps --config /etc/orangepi-apps/config.json serve
User=root
Group=root
UMask=0077
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/srv/orangepi-apps /etc/orangepi-apps
ReadOnlyPaths=/etc/orangepi-homeassistant
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 AF_NETLINK
MemoryHigh=160M
MemoryMax=256M
TasksMax=128
CPUWeight=25

[Install]
WantedBy=multi-user.target
"""


def mapped(root: Path, absolute: str) -> Path:
    checked_path(absolute)
    return checked_path(root / Path(absolute).relative_to("/"))


def source_files() -> list[tuple[Path, Path]]:
    files = [(p, Path("src/opiha_apps") / p.relative_to(SOURCE / "src/opiha_apps"))
             for p in sorted((SOURCE / "src/opiha_apps").rglob("*")) if p.is_file() and p.suffix == ".py" and "__pycache__" not in p.parts]
    files += [(p, Path("homeassistant/custom_components/opiha_apps") / p.relative_to(SOURCE / "homeassistant/custom_components/opiha_apps"))
              for p in sorted((SOURCE / "homeassistant/custom_components/opiha_apps").rglob("*"))
              if p.is_file() and p.suffix in {".py", ".js", ".json"} and "__pycache__" not in p.parts]
    files.append((SOURCE / "bin/opiha-apps", Path("bin/opiha-apps")))
    return files


def preview(root: Path, appliance: str, adopt_restored=False) -> dict:
    root = checked_path(root)
    if not (root / "etc/os-release").is_file():
        raise AppError("Destination does not look like a Linux root")
    cfg = read_json(mapped(root, appliance))
    if cfg.get("mode") != "appliance":
        raise AppError("Native apps require an appliance configuration; a quarantine lab is never converted")
    ha = mapped(root, cfg["data_dir"]) / "ha"
    yaml = checked_path(ha / "configuration.yaml")
    if not yaml.is_file() or yaml.stat().st_size > 4 * 1024**2:
        raise AppError("An existing readable HA configuration.yaml is required")
    state = mapped(root, "/srv/orangepi-apps")
    if state.exists() and any(state.iterdir()) and not (state / ".opiha-apps.json").is_file():
        raise AppError("Native-app state path is occupied by unowned data")
    code = mapped(root, "/opt/orangepi-apps")
    settings = mapped(root, "/etc/orangepi-apps")
    unit = mapped(root, "/etc/systemd/system/orangepi-apps.service")
    component = checked_path(ha / "custom_components/opiha_apps")
    marker = settings / "deployment.json"
    old = read_json(marker) if marker.exists() else None
    restored_panel = False
    if adopt_restored and not old and component.is_dir():
        source = SOURCE / "homeassistant/custom_components/opiha_apps"
        expected = {p.relative_to(source).as_posix(): p.read_bytes() for p in source.rglob("*")
                    if p.is_file() and "__pycache__" not in p.parts and p.suffix in {".py", ".js", ".json"}}
        actual = {p.relative_to(component).as_posix(): checked_path(p).read_bytes() for p in component.rglob("*")
                  if p.is_file() and "__pycache__" not in p.parts and p.suffix not in {".pyc", ".pyo"}}
        if actual != expected:
            raise AppError("Restored panel bytes differ from this release; use the matching release or reconcile explicitly")
        restored_panel = True
    for p in (code, settings, unit, component, ha / "opiha-apps-connection.json"):
        checked_path(p)
        if p.exists() and not old and not (restored_panel and p in {component, ha / "opiha-apps-connection.json"}):
            raise AppError("Unowned native-app destination exists; inspect it rather than overwriting")
    if old and old.get("owner") != "opiha-native-installer-v1":
        raise AppError("Unrecognized native-app deployment ownership")
    if old:
        for relative, expected in old.get("managed_hashes", {}).items():
            path = mapped(root, relative)
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise AppError("Managed installation files were edited; reconcile them before upgrade")
    text = yaml.read_text()
    if re.search(r"(?m)^opiha_apps\s*:", text) and not old and not restored_panel:
        raise AppError("An existing opiha_apps stanza needs explicit reconciliation")
    if "\x00" in text:
        raise AppError("HA configuration is not valid text")
    return {"version": __version__, "appliance_config": appliance, "homeassistant_config": str(ha),
            "adds_yaml_stanza": not bool(re.search(r"(?m)^opiha_apps\s*:", text)),
            "changes_boot": False, "changes_network": False, "starts_services": False,
            "changes_existing_units": False, "requires_one_ha_restart": True,
            "next": "Review and apply, start only orangepi-apps.service, validate HA config and restart HA once."}


def install(*, root=Path("/"), appliance="/etc/orangepi-homeassistant/appliance.json", apply=False, architecture=None, adopt_restored=False) -> dict:
    root = Path(root).absolute()
    result = preview(root, appliance, adopt_restored)
    if not apply:
        return {**result, "applied": False}
    if root == Path("/") and os.geteuid() != 0:
        raise AppError("Host installation requires root")
    ha = Path(result["homeassistant_config"])
    settings = mapped(root, "/etc/orangepi-apps")
    code = mapped(root, "/opt/orangepi-apps")
    settings.mkdir(mode=0o700, parents=True, exist_ok=True)
    code.mkdir(mode=0o755, parents=True, exist_ok=True)
    release = code / "releases" / __version__
    checked_path(release)
    expected = {str(dst): hashlib.sha256(src.read_bytes()).hexdigest() for src, dst in source_files()}
    if release.exists():
        for name, sha in expected.items():
            if not (release / name).is_file() or hashlib.sha256((release / name).read_bytes()).hexdigest() != sha:
                raise AppError("Release directory exists with different source bytes")
    else:
        release.parent.mkdir(parents=True, mode=0o755, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix=".install-", dir=release.parent))
        try:
            for source, target in source_files():
                atomic(stage / target, source.read_bytes(), 0o755 if str(target).startswith("bin/") else 0o644)
            os.chmod(stage, 0o755)
            stage.rename(release)
        finally:
            if stage.exists():
                shutil.rmtree(stage)
    configuration = settings / "config.json"
    if not configuration.exists():
        cfg = defaults()
        detected = architecture or {"aarch64": "arm64", "x86_64": "amd64"}.get(platform.machine())
        if detected not in {"arm64", "amd64"}:
            raise AppError("Only native ARM64 or AMD64 hosts are supported")
        cfg.update(architecture=detected, appliance_config=appliance)
        write_json(configuration, cfg)
    else:
        cfg = read_json(configuration)
    # The fake-root path is only for tests / offline staging; it must never be published with tokens.
    runtime = dict(cfg)
    for k in ("data_dir", "token_file", "appliance_config"):
        runtime[k] = str(mapped(root, runtime[k]))
    initialize(runtime)
    component = checked_path(ha / "custom_components/opiha_apps")
    component.mkdir(mode=0o700, parents=True, exist_ok=True)
    cache = component / "__pycache__"
    if cache.exists():
        checked_path(cache)
        shutil.rmtree(cache)
    hashes = {}
    for p in sorted((SOURCE / "homeassistant/custom_components/opiha_apps").rglob("*")):
        if not p.is_file() or "__pycache__" in p.parts:
            continue
        if p.suffix not in {".py", ".js", ".json"}:
            continue
        target = checked_path(component / p.relative_to(SOURCE / "homeassistant/custom_components/opiha_apps"))
        atomic(target, p.read_bytes())
        hashes["/" + target.relative_to(root).as_posix()] = hashlib.sha256(target.read_bytes()).hexdigest()
    atomic(ha / "opiha-apps-connection.json", (json.dumps({"url": f"http://127.0.0.1:{cfg['port']}", "token": read_token(runtime)}) + "\n").encode())
    yaml = ha / "configuration.yaml"
    if result["adds_yaml_stanza"]:
        backup = settings / ("configuration-before-" + stamp() + ".yaml")
        atomic(backup, yaml.read_bytes())
        atomic(yaml, yaml.read_bytes() + b"\n\n# Managed opt-in: Orange Pi native application panel\nopiha_apps:\n")
    unit = mapped(root, "/etc/systemd/system/orangepi-apps.service")
    atomic(unit, SERVICE.encode(), 0o644)
    hashes["/etc/systemd/system/orangepi-apps.service"] = hashlib.sha256(unit.read_bytes()).hexdigest()
    # current is an explicitly installer-owned selector, not an arbitrary symlink ancestor.
    selected = code / "current"
    temp = code / (".current-" + stamp())
    temp.symlink_to(Path("releases") / __version__)
    os.replace(temp, selected)
    write_json(settings / "deployment.json", {"owner": "opiha-native-installer-v1", "version": __version__,
                                              "managed_hashes": hashes, "appliance_config": appliance})
    return {**result, "applied": True, "public_image_safe": False,
            "warning": "Runtime installation generated private tokens. Do not publish a clone of this filesystem."}
