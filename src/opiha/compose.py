from __future__ import annotations
import json
import hashlib
import os
from pathlib import Path
import secrets
import stat
from .common import ApplianceError, atomic_bytes, atomic_json, read_json, run
from .config import ensure_state, validate


def bind(source: Path | str, target: str, readonly: bool = False) -> dict:
    return {"type": "bind", "source": str(source), "target": target, "read_only": readonly,
            "bind": {"create_host_path": False}}


def generate(cfg: dict) -> dict:
    """Return Compose as JSON, a YAML subset. No interpolation or .env evaluation."""
    validate(cfg)
    d = Path(cfg["data_dir"])
    w = Path(cfg["work_dir"])
    prod = cfg["mode"] == "appliance"
    restart = "unless-stopped" if prod else "no"
    log = {"driver": "json-file", "options": {"max-size": "10m", "max-file": "3"}}
    def service(image: str) -> dict:
        return {"image": cfg["images"][image], "restart": restart, "logging": log,
                "security_opt": ["no-new-privileges:true"],
                **({"pull_policy": "never"} if cfg["images"][image].startswith("opiha-cache/") else {})}
    ha = service("homeassistant")
    ha.update({"environment": {"TZ": cfg["timezone"]}, "stop_grace_period": "120s",
               "volumes": [bind(d / "ha", "/config"), bind(d / "ssl", "/ssl", True),
                           bind(d / "media", "/media"), bind(d / "share", "/share")],
               "healthcheck": {"test": ["CMD", "python3", "-c",
                   "import urllib.request; urllib.request.urlopen(" + repr(("http://127.0.0.1:8123" if cfg["mode"] == "lab" else cfg["ha_url"]) + "/") + ",timeout=5)"],
                   "interval": "30s", "timeout": "10s", "retries": 5, "start_period": "120s"}})
    services = {"homeassistant": ha}
    result = {"name": "opiha" if prod else "opiha-lab-" + hashlib.sha256(str(d).encode()).hexdigest()[:8], "services": services}
    if not prod:
        ha["networks"] = ["quarantine"]
        result["networks"] = {"quarantine": {"internal": True}}
        return result
    ha["network_mode"] = "host"
    # No blanket privileged:true, Docker socket or entire /dev mount.
    if cfg["features"]["zwave"]:
        z = service("zwave")
        z.update({"stop_signal": "SIGINT", "stop_grace_period": "60s",
                  "ports": ["127.0.0.1:8091:8091", "127.0.0.1:3000:3000"],
                  "devices": [f"{cfg['zwave_device']}:/dev/zwave"],
                  "environment": {"TZ": cfg["timezone"], "ZWAVE_PORT": "/dev/zwave",
                                  "ZWAVE_EXTERNAL_SETTINGS": "/opiha/zwave-external.json"},
                  "env_file": [{"path": str(d / "private/zwave.env"), "required": True}],
                  "volumes": [bind(d / "zwave", "/usr/src/app/store"),
                              bind(w / "zwave-external.json", "/opiha/zwave-external.json", True)],
                  "mem_limit": "768m", "cpus": 1.5})
        services["zwave"] = z
    if cfg["features"]["mqtt"]:
        mqtt = service("mqtt")
        mqtt.update({"ports": ["127.0.0.1:1883:1883"],
                     "volumes": [bind(d / "mqtt/config", "/mosquitto/config", True),
                                 bind(d / "mqtt/data", "/mosquitto/data")],
                     "mem_limit": "128m", "cpus": 0.5})
        services["mqtt"] = mqtt
    if cfg["features"]["camera"]:
        camera = service("camera")
        camera.update({"ports": ["127.0.0.1:1984:1984", "127.0.0.1:8554:8554"],
                       "devices": [f"{cfg['camera_device']}:/dev/video0"],
                       "volumes": [bind(d / "camera/go2rtc.yaml", "/config/go2rtc.yaml", True)],
                       "mem_limit": "384m", "cpus": 1.0})
        services["camera"] = camera
    return result


def prepare(cfg: dict) -> Path:
    d = ensure_state(cfg)
    w = Path(cfg["work_dir"])
    w.mkdir(parents=True, exist_ok=True, mode=0o700)
    if (w / "restore-journal.json").exists():
        raise ApplianceError("Unfinished restore transaction; run repair-restore before starting")
    if cfg["features"]["zwave"] and cfg["mode"] == "appliance":
        secret = d / "private/zwave.env"
        if not secret.exists():
            atomic_bytes(secret, f"SESSION_SECRET={secrets.token_hex(32)}\nDEFAULT_USERNAME=admin\nDEFAULT_PASSWORD={secrets.token_urlsafe(32)}\n".encode())
        atomic_json(w / "zwave-external.json", {"serverEnabled": True, "serverHost": "0.0.0.0", "serverPort": 3000,
                                                "serverServiceDiscoveryDisabled": True})
    if cfg["features"]["camera"] and cfg["mode"] == "appliance":
        target = d / "camera/go2rtc.yaml"
        if not target.exists():
            cam = cfg["camera"]
            source = (f"ffmpeg:device?video=/dev/video0&input_format={cam['input_format']}"
                      f"&video_size={cam['width']}x{cam['height']}&framerate={cam['fps']}#video=h264")
            atomic_json(target, {"api": {"listen": ":1984"}, "rtsp": {"listen": ":8554"},
                                 "webrtc": {"listen": ""}, "streams": {"local": source}})
    target = w / "compose.json"
    atomic_json(target, generate(cfg))
    return target


def command(cfg: dict, *args: str, capture: bool = False):
    path = prepare(cfg)
    # An explicit, empty env-file avoids loading a workstation's unrelated .env.
    empty = path.parent / "empty.env"
    atomic_bytes(empty, b"")
    return run(["docker", "compose", "--env-file", str(empty), "--project-directory", str(path.parent),
                "-p", generate(cfg)["name"],
                "-f", str(path), *args], capture=capture)


def verify_hardware(cfg: dict) -> None:
    if cfg["mode"] != "appliance":
        return
    for feature, key in (("zwave", "zwave_device"), ("camera", "camera_device")):
        if cfg["features"][feature]:
            p = Path(cfg[key])
            if not p.exists() or not stat.S_ISCHR(p.stat().st_mode):
                raise ApplianceError(f"{feature}: configured character device is unavailable")
    if cfg["features"]["mqtt"] and not (Path(cfg["data_dir"]) / "mqtt/config/passwordfile").is_file():
        raise ApplianceError("MQTT has no password file; run mqtt-init first")


def running(cfg: dict) -> list[str]:
    return command(cfg, "ps", "--status", "running", "--services", capture=True).stdout.split()


def lock_images(cfg: dict, platform: str) -> dict:
    if platform not in ("linux/amd64", "linux/arm64"):
        raise ApplianceError("Use linux/arm64 for the appliance or linux/amd64 for the lab")
    result = dict(cfg)
    result["images"] = {}
    for name, image in cfg["images"].items():
        run(["docker", "pull", "--platform", platform, image])
        info = json.loads(run(["docker", "image", "inspect", image], capture=True).stdout)[0]
        expected = platform.split("/")[-1]
        if info["Architecture"] != expected:
            raise ApplianceError(f"Wrong architecture pulled for {name}")
        digests = info.get("RepoDigests", [])
        if not digests:
            raise ApplianceError(f"No registry digest for {name}")
        result["images"][name] = digests[0]
    return validate(result)
