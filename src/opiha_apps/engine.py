"""Small Docker CLI adapter. No Docker socket is exposed to Home Assistant.

Only the local Engine is addressed. No shell, user-controlled Docker flags,
DOCKER_HOST, user context, or browser-supplied Compose YAML is evaluated.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from .common import AppError

LABEL = "io.opiha.native-apps.owner"
APP_LABEL = "io.opiha.native-apps.app"


class Docker:
    def __init__(self, owner: str, *, runner=None, config_dir: str | None = None):
        self.owner = owner
        self.config_dir = config_dir  # writable client state (buildx) when the service filesystem is read-only
        self.runner = runner or self._run

    def _run(self, argv: list[str], timeout: int = 30) -> tuple[int, str]:
        env = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "HOME": "/var/lib/orangepi-apps", "LC_ALL": "C.UTF-8"}
        if self.config_dir:
            env["DOCKER_CONFIG"] = self.config_dir
        try:
            # Output cannot accumulate unbounded in the daemon's memory during pulls.
            with tempfile.TemporaryFile() as output:
                p = subprocess.run(["/usr/bin/docker", "--host", "unix:///var/run/docker.sock", *argv],
                                   stdout=output, stderr=subprocess.STDOUT, env=env, timeout=timeout, check=False)
                length = output.tell()
                if length > 8 * 1024 * 1024:
                    raise AppError("Docker output exceeded its limit")
                output.seek(0)
                return p.returncode, output.read().decode("utf-8", errors="replace")
        except FileNotFoundError as exc:
            raise AppError("Docker Engine CLI is not installed at /usr/bin/docker") from exc
        except subprocess.TimeoutExpired as exc:
            raise AppError("Docker operation timed out; inspect the app before retrying") from exc

    def command(self, args: list[str], timeout: int = 30) -> str:
        code, out = self.runner(args, timeout)
        if code:
            # Upstream output can contain credentials or private paths. Do not forward it.
            raise AppError("Docker operation failed; inspect the local Docker service and app logs")
        return out

    def info(self) -> dict:
        return json.loads(self.command(["info", "--format", "{{json .}}"] ))

    def containers(self) -> list[dict]:
        ids = self.command(["container", "ls", "-aq"]).split()
        if not ids:
            return []
        if len(ids) > 1024:
            raise AppError("Container enumeration exceeds the supported host size")
        return json.loads(self.command(["container", "inspect", *ids]))

    def owned(self, slug: str) -> dict | None:
        found = []
        for c in self.containers():
            labels = c.get("Config", {}).get("Labels", {}) or {}
            if labels.get(LABEL) == self.owner and labels.get(APP_LABEL) == slug:
                found.append(c)
        if len(found) > 1:
            raise AppError("Multiple owned containers claim this app; resolve locally before continuing")
        return found[0] if found else None

    def assert_owned(self, identifier: str, slug: str) -> dict:
        rows = json.loads(self.command(["container", "inspect", identifier]))
        if len(rows) != 1:
            raise AppError("Cannot uniquely identify the managed container")
        c = rows[0]
        labels = c.get("Config", {}).get("Labels", {}) or {}
        if labels.get(LABEL) != self.owner or labels.get(APP_LABEL) != slug:
            raise AppError("Refusing to control a container owned by another deployment")
        return c

    def pull(self, reference: str, repository: str, architecture: str) -> tuple[str, str]:
        self.command(["image", "pull", "--platform", "linux/" + architecture, reference], timeout=1200)
        row = json.loads(self.command(["image", "inspect", reference]))[0]
        if row.get("Architecture") != architecture or row.get("Os") != "linux":
            raise AppError("Pulled image is not native to this Linux host")
        # Preserve the registry spelling returned by Docker, but only for this repository.
        def canonical(value: str) -> str:
            value = value.removeprefix("docker.io/").removeprefix("library/")
            return value
        candidates = [x for x in row.get("RepoDigests", []) if "@sha256:" in x
                      and canonical(x.split("@", 1)[0]) == canonical(repository)]
        if not candidates:
            raise AppError("Image has no matching registry digest; refusing a tag-only launch")
        return candidates[0], row["Id"]

    def ensure_network(self, name: str, create_args: list[str] | None = None):
        raw = self.command(["network", "ls", "--format", "{{json .}}"])
        for line in raw.splitlines():
            row = json.loads(line)
            if row.get("Name") == name:
                net = json.loads(self.command(["network", "inspect", name]))[0]
                if (net.get("Labels") or {}).get(LABEL) != self.owner or net.get("Driver") != "bridge":
                    raise AppError("Existing app network is not owned by this deployment")
                return
        self.command(["network", "create", "--driver", "bridge", *(create_args or []), "--label", LABEL + "=" + self.owner, name])

    def create(self, slug: str, spec: dict) -> str:
        # Reviewed catalog apps run as an unprivileged UID with every capability dropped.
        # Add-on specs may name a user, a capability allow-list and further reviewed switches.
        user = spec.get("user", str(spec["uid"]) + ":" + str(spec["uid"]))
        args = ["container", "create", "--name", "opiha-apps-" + slug,
                "--label", LABEL + "=" + self.owner, "--label", APP_LABEL + "=" + slug,
                "--restart", "unless-stopped" if spec["autostart"] else "no",
                "--network", spec["network"], "--memory", str(spec["memory_mib"]) + "m",
                "--memory-swap", str(spec["memory_mib"]) + "m", "--cpu-shares", str(spec["cpu_shares"]),
                "--pids-limit", "512", "--cap-drop", "ALL",
                "--log-driver", "json-file", "--log-opt", "max-size=5m", "--log-opt", "max-file=2",
                "--user", user]
        if not spec.get("privileged_mode"):
            args += ["--security-opt", "no-new-privileges:true"]
        else:
            args += ["--privileged"]
        for cap in spec.get("cap_add", []):
            args += ["--cap-add", cap]
        if spec.get("init"):
            args += ["--init"]
        if spec.get("tmpfs"):
            args += ["--tmpfs", "/tmp:rw,size=64m"]
        for alias in spec.get("aliases", []):
            args += ["--network-alias", alias]
        for host, address in spec.get("extra_hosts", []):
            args += ["--add-host", f"{host}:{address}"]
        for src, dst, readonly in spec["mounts"]:
            args += ["--mount", f"type=bind,src={src},dst={dst}" + (",readonly" if readonly else "")]
        for host, container in spec["ports"]:
            args += ["--publish", f"{spec.get('bind', '127.0.0.1')}:{host}:{container}"]
        for host, container in spec.get("loopback_ports", []):
            args += ["--publish", f"127.0.0.1:{host}:{container}"]
        for host, container in spec.get("udp_ports", []):
            args += ["--publish", f"{spec.get('bind', '127.0.0.1')}:{host}:{container}/udp"]
        for key, value in sorted(spec["environment"].items()):
            args += ["--env", f"{key}={value}"]
        if spec.get("env_file"):
            args += ["--env-file", spec["env_file"]]
        if spec.get("device"):
            args += ["--device", spec["device"] + ":/dev/zwave:rwm",
                     "--group-add", str(os.stat(spec["device"]).st_gid)]
        for path in spec.get("devices", []):
            args += ["--device", f"{path}:{path}:rwm"]
        args += [spec["image"], *spec.get("command", [])]
        return self.command(args, timeout=90).strip()

    def build(self, tag: str, context: str, build_args: dict[str, str], architecture: str) -> str:
        """Build an add-on image from its reviewed-on-install source tree; returns the local image ID."""
        argv = ["image", "build", "--quiet", "--platform", "linux/" + architecture, "--tag", tag,
                "--label", LABEL + "=" + self.owner]
        for key, value in sorted(build_args.items()):
            argv += ["--build-arg", f"{key}={value}"]
        code, out = self.runner([*argv, context], 3600)
        if code:
            raise AppError("Image build failed: " + " ".join(out.strip().splitlines()[-4:])[-400:])
        row = json.loads(self.command(["image", "inspect", tag]))[0]
        if row.get("Architecture") != architecture or row.get("Os") != "linux":
            raise AppError("Built image is not native to this Linux host")
        return row["Id"]

    def action(self, identifier: str, slug: str, action: str):
        self.assert_owned(identifier, slug)
        if action not in {"start", "stop", "restart", "remove"}:
            raise AppError("Unknown container action")
        if action == "remove":
            return self.command(["container", "rm", identifier])
        args = ["container", action]
        if action != "start":
            args += ["--time", "60"]
        return self.command([*args, identifier], timeout=90)

    def restart_policy(self, identifier: str, slug: str, autostart: bool):
        self.assert_owned(identifier, slug)
        self.command(["container", "update", "--restart", "unless-stopped" if autostart else "no", identifier])

    def logs(self, identifier: str, slug: str) -> str:
        self.assert_owned(identifier, slug)
        # Logs are an explicit admin operation, not continuously collected.
        return self.command(["container", "logs", "--tail", "150", identifier])[-128 * 1024:]

    def stats(self, ids: list[str]) -> list[dict]:
        if not ids:
            return []
        return [json.loads(x) for x in self.command(["stats", "--no-stream", "--format", "{{json .}}", *ids]).splitlines()]
