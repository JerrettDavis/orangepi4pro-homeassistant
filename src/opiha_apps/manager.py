"""Native app lifecycle, plan/approval jobs, ownership and state rollback.

The Home Assistant container is deliberately not managed by this class.
"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
import contextlib
import copy
import hashlib
import json
import os
import re
from pathlib import Path
import secrets
import shutil
import socket
import stat
import threading
import time
from . import __version__, addon_runtime, addons, catalog, resources
from .addon_repos import Repositories
from .common import AppError, atomic, checked_path, initialize, operation_lock, read_json, stamp, validate_config, write_json
from .engine import APP_LABEL, LABEL, Docker
from .filesystem import copy_tree, inventory, set_owner


class Manager:
    def __init__(self, config: dict, *, engine=None, sampler=resources.sample, check_port=True):
        self.config = validate_config(copy.deepcopy(config))
        self.root = checked_path(config["data_dir"], directory=True)
        self.owner = initialize(config)
        self.engine = engine or Docker(self.owner)
        self.sampler = sampler
        self.check_port = check_port
        self.guard = threading.RLock()
        self.plans: dict[str, dict] = {}
        self.jobs: dict[str, dict] = {}
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="opiha-apps")
        self.active = False
        self.repos = Repositories(self.root)
        self.shim_address = None
        self._ha_config = None
        self._load_addons()
        for p in sorted((self.root / "jobs").glob("*.json"))[-64:]:
            item = read_json(p)
            if item.get("status") in {"queued", "running"}:
                item.update(status="interrupted", stage="Inspect state before retrying", finished=time.time())
                write_json(p, item)
            self.jobs[p.stem] = item

    @property
    def ha_config(self):
        """Home Assistant's configuration directory, derived from the appliance file; None when unknown."""
        if self._ha_config is None:
            try:
                data = read_json(Path(self.config["appliance_config"]))["data_dir"]
                self._ha_config = str(Path(data) / "ha")
            except (AppError, KeyError, OSError):
                return None
        return self._ha_config

    @ha_config.setter
    def ha_config(self, value):
        self._ha_config = value

    def _load_addons(self):
        catalog.clear_dynamic()
        for p in sorted((self.root / "apps").glob("*/addon.json")):
            try:
                app = addon_runtime.load_addon(p)
                if app["slug"] == p.parent.name:
                    catalog.register(app["slug"], app)
            except AppError:
                continue

    def close(self):
        self.worker.shutdown(wait=True, cancel_futures=False)

    def app_dir(self, slug: str) -> Path:
        catalog.entry(slug)
        return checked_path(self.root / "apps" / slug)

    def record(self, slug: str) -> dict | None:
        p = self.app_dir(slug) / "record.json"
        return self.validate_record(slug, read_json(p)) if p.exists() else None

    @staticmethod
    def validate_record(slug: str, row: dict) -> dict:
        app = catalog.entry(slug)
        if set(row) != {"schema", "app", "options", "image", "image_id", "revision", "installed"} or row.get("schema") != 1 or row.get("app") != slug or type(row.get("installed")) is not bool:
            raise AppError("Invalid native-app state record")
        catalog.options(slug, row["options"])
        image = row.get("image")
        expected = app["repository"].removeprefix("docker.io/")
        if app.get("addon"):
            pattern = r"sha256:[0-9a-f]{64}" if app["build"] else re.escape(expected) + r"@sha256:[0-9a-f]{64}"
            if not isinstance(image, str) or not re.fullmatch(pattern, image):
                raise AppError("Restored add-on image must be its local build ID or a digest in its manifest's repository")
        elif not isinstance(image, str) or not re.fullmatch(re.escape(expected) + r"@sha256:[0-9a-f]{64}", image.removeprefix("docker.io/").removeprefix("library/")):
            raise AppError("Restored image must be a digest in the reviewed application repository")
        if not isinstance(row["image_id"], str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", row["image_id"]) or not isinstance(row["revision"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", row["revision"]):
            raise AppError("Invalid app image identity or revision")
        return row

    def records(self) -> dict[str, dict]:
        return {slug: item for slug in catalog.all_slugs() if (item := self.record(slug))}

    def _assert_no_journal(self, slug: str):
        if (self.app_dir(slug) / "transaction.json").exists():
            raise AppError("Interrupted app replacement: run opiha-apps repair locally before any lifecycle operation")

    def overview(self, include_stats=False) -> dict:
        host = self.sampler(self.root)
        records = self.records()
        try:
            all_containers = self.engine.containers()
            engine_error = None
        except (AppError, OSError, ValueError):
            all_containers = []
            engine_error = "Docker unavailable; this is not an empty/healthy host result"
        entries = []
        for app in catalog.public_catalog():
            slug = app["id"]
            record = records.get(slug)
            owned = [c for c in all_containers if (c.get("Config", {}).get("Labels") or {}).get(LABEL) == self.owner
                     and (c.get("Config", {}).get("Labels") or {}).get(APP_LABEL) == slug]
            external = self._external(slug, all_containers)
            state = "not_installed"
            if engine_error:
                state = "engine_unavailable"
            elif len(owned) > 1:
                state = "conflict"
            elif owned:
                state = owned[0].get("State", {}).get("Status", "unknown")
            elif external:
                state = "externally_managed"
            elif record:
                state = "data_retained"
            if (self.app_dir(slug) / "transaction.json").exists():
                state = "recovery_required"
            entries.append({**app, "state": state,
                            "installed": bool(owned), "options": record["options"] if record else app["defaults"],
                            "locked_image": record.get("image") if record else None,
                            "external_count": len(external), "data_retained": bool(record)})
        with self.guard:
            active_job = next((copy.deepcopy(j) for j in self.jobs.values() if j["status"] in {"queued", "running"}), None)
        result = {"version": __version__, "engine_error": engine_error, "apps": entries,
                  "resources": host, "reserve_mib": self.config["reserve_mib"],
                  "allocated_limit_mib": sum(r["options"]["memory_mib"] for r in records.values() if r.get("installed")),
                  "active_job": active_job,
                  "supervisor": False, "changes_homeassistant": False}
        if include_stats and not engine_error:
            ids = [c["Id"] for c in all_containers if (c.get("Config", {}).get("Labels") or {}).get(LABEL) == self.owner
                   and c.get("State", {}).get("Running")]
            result["container_stats"] = self.engine.stats(ids)
        return result

    @staticmethod
    def _canonical_image(value: str) -> str:
        return value.removeprefix("docker.io/").removeprefix("library/").split("@", 1)[0].split(":", 1)[0]

    def _external(self, slug: str, containers: list[dict]) -> list[dict]:
        if catalog.is_addon(slug):
            return []  # Add-ons share popular images; ownership is by name and label only.
        repo = self._canonical_image(catalog.entry(slug)["repository"])
        return [c for c in containers if self._canonical_image(c.get("Config", {}).get("Image", "")) == repo
                and (c.get("Config", {}).get("Labels") or {}).get(LABEL) != self.owner]

    def _budget(self, slug: str, opts: dict):
        host = self.sampler(self.root)
        total = host.get("memory_total")
        available = host.get("memory_available")
        if not isinstance(total, int) or not isinstance(available, int):
            raise AppError("Cannot measure host memory; refusing an unbudgeted app start")
        allocated = opts["memory_mib"] + sum(r["options"]["memory_mib"] for s, r in self.records().items()
                                              if s != slug and r.get("installed"))
        if allocated + self.config["reserve_mib"] > total // 1024**2:
            raise AppError("App memory ceilings would consume the reserved HA/kiosk/host headroom")
        if available < self.config["minimum_available_mib"] * 1024**2:
            raise AppError("Host memory is already under pressure; stop or resize another workload first")
        floor = 4 if catalog.entry(slug).get("build") else 2
        if host.get("disk_free") is None or host["disk_free"] < floor * 1024**3:
            raise AppError(f"At least {floor} GiB free storage is required before this app operation")

    def _architecture(self):
        info = self.engine.info()
        actual = {"aarch64": "arm64", "x86_64": "amd64"}.get(info.get("Architecture"), info.get("Architecture"))
        if actual != self.config["architecture"]:
            raise AppError("Docker architecture differs from the configured native architecture; emulation is not used")
        if info.get("OSType") != "linux" or info.get("MemoryLimit") is not True:
            raise AppError("Native Linux Docker with cgroup memory limits is required")

    def _hardware(self, slug: str, opts: dict, containers: list[dict]):
        if not catalog.entry(slug).get("radio"):
            return
        device = opts["device"]
        if not device or not opts["radio_reviewed"]:
            raise AppError("Radio starts need the original persistent USB path and explicit migration review")
        p = Path(device)
        if not p.exists() or not stat.S_ISCHR(p.stat().st_mode):
            raise AppError("The selected persistent USB character device is absent")
        for c in containers:
            if (c.get("Config", {}).get("Labels") or {}).get(LABEL) == self.owner:
                continue
            for dev in c.get("HostConfig", {}).get("Devices", []) or []:
                other = dev.get("PathOnHost")
                if other and Path(other).exists() and os.path.samefile(other, device):
                    raise AppError("Another container owns this radio; no automatic handover is allowed")
        if not (self.app_dir(slug) / "data/settings.json").is_file():
            raise AppError("Restore the stopped Z-Wave JS UI store including settings.json and original keys before starting")

    @staticmethod
    def _version_tuple(version: str):
        import re
        return tuple(int(x) for x in re.findall(r"\d+", version))

    def preflight(self, slug: str, action: str, opts: dict) -> dict:
        self._assert_no_journal(slug)
        all_containers = self.engine.containers()
        existing = self.engine.owned(slug)
        record = self.record(slug)
        if action not in {"install", "update", "start", "stop", "restart", "remove", "configure"}:
            raise AppError("Unsupported lifecycle operation")
        if action == "configure" and not catalog.is_addon(slug):
            raise AppError("Only add-ons have editable options")
        if catalog.is_addon(slug) and action in {"install", "update", "start", "restart", "configure"}:
            addon_runtime.check_grants(catalog.entry(slug), opts)
        if action in {"install", "update"}:
            if self._external(slug, all_containers):
                raise AppError("This application already has an external owner; preserve it or migrate it deliberately")
            name = "/opiha-apps-" + slug
            for c in all_containers:
                if c.get("Name") == name and (c.get("Config", {}).get("Labels") or {}).get(LABEL) != self.owner:
                    raise AppError("App container name is already owned by another deployment")
            if action == "install" and existing:
                raise AppError("App is already installed; use a reviewed update")
            if action == "update" and not record:
                raise AppError("Install the app before updating it")
            if record and self._version_tuple(opts["version"]) < self._version_tuple(record["options"]["version"]):
                raise AppError("App downgrade is unsafe without matching old state; use a tested recovery point")
        elif not existing or not record:
            raise AppError("This operation requires a uniquely owned installed app")
        if action in {"install", "update", "start", "restart"}:
            self._architecture()
            self._budget(slug, opts)
            if action in {"start", "restart"}:
                self._hardware(slug, opts, all_containers)
        if action in {"install", "update"}:
            wanted = catalog.wanted_ports(slug, opts)
            if self.config["port"] in wanted:
                raise AppError("App port conflicts with the manager API")
            for other, r in self.records().items():
                if other != slug and r.get("installed") and catalog.wanted_ports(other, r["options"]) & wanted:
                    raise AppError("App port conflicts with another managed app")
            if self.check_port:
                for port in wanted:
                    own_ports = (existing or {}).get("HostConfig", {}).get("PortBindings", {}) or {}
                    if existing and any(str(port) == row.get("HostPort") for rows in own_ports.values() for row in rows or []):
                        continue
                    # Docker's userland proxy can hold a just-removed app's port for a moment.
                    for attempt in range(10):
                        with socket.socket() as s:
                            try:
                                s.bind(("127.0.0.1", port))
                                break
                            except OSError as exc:
                                if attempt == 9:
                                    raise AppError("Selected loopback port is already in use") from exc
                        time.sleep(0.5)
        return {"container_id": existing["Id"] if existing else None,
                "running": bool(existing and existing.get("State", {}).get("Running")),
                "revision": record.get("revision") if record else None}

    def plan_addon(self, repository: str, folder: str, supplied: dict | None = None) -> dict:
        """Plan installing (or updating to) an add-on exactly as it exists in an added repository now."""
        raw = self.repos.raw(repository, folder)
        manifest = addons.parse(raw, repository=repository)
        app = addon_runtime.entry_from(manifest, repository, folder)
        slug = app["slug"]
        source = self.repos.addon_dir(repository, folder)
        info = {"raw": raw, "repo": repository, "folder": folder,
                "source_hash": addon_runtime.tree_hash(source)}
        with self.guard, catalog.override(slug, app):
            action = "update" if self.record(slug) else "install"
            options = {**(supplied or {}), "version": app["version"]}
            value = self.plan(slug, action, options, addon=info)
        return value

    def _addon_entry(self, info: dict) -> dict:
        return addon_runtime.entry_from(addons.parse(info["raw"], repository=info["repo"]), info["repo"], info["folder"])

    def plan(self, slug: str, action: str, supplied: dict | None = None, *, addon: dict | None = None) -> dict:
        with self.guard:
            old = self.record(slug)
            if catalog.is_addon(slug) and action in {"install", "update"} and addon is None:
                raise AppError("Install or update add-ons from their repository listing")
            opts = catalog.options(slug, supplied if supplied is not None else old["options"] if old else None)
            if action not in {"install", "update"} and old and (
                    {k: v for k, v in opts.items() if k != "config"} != {k: v for k, v in old["options"].items() if k != "config"}
                    or (action != "configure" and opts != old["options"])):
                raise AppError("Use update to change settings; lifecycle actions use the installed settings")
            baseline = self.preflight(slug, action, opts)
            for key in list(self.plans):
                if self.plans[key]["expires"] < time.time():
                    del self.plans[key]
            if len(self.plans) >= 32:
                raise AppError("Too many pending plans; wait for existing plans to expire")
            key = secrets.token_urlsafe(24)
            app = catalog.entry(slug)
            value = {"id": key, "app": slug, "action": action, "options": opts,
                     "image": catalog.image(slug, opts), "expires": time.time() + 300,
                     "baseline": baseline, "preserves_data": True, "changes_homeassistant": False,
                     "warnings": [app["notes"], "App code and its web UI must be trusted.",
                                  "This app can reach your LAN through Docker NAT; it is not a production-state quarantine."],
                     "starts_app": action in {"start", "restart"},
                     "requires_host_reboot": False}
            if addon is not None:
                report = addons.report(app["manifest"])
                value.update(addon=addon, report=report, privileges=report["privileges"],
                             builds_locally=bool(app["build"]), source_hash=addon["source_hash"])
                value["warnings"].append("Add-ons are third-party software from a repository you added. They are not reviewed by this project.")
                if app["build"]:
                    value["warnings"].append("This add-on is built on the device from its Dockerfile; that needs several GiB of free storage and can take many minutes.")
                if opts["lan"]:
                    value["warnings"].append("Published ports are reachable from your LAN, bypassing the host firewall's usual rules for Docker.")
            if action == "update":
                value["warnings"].append("Only this app stops. A private rollback copy is retained; reserve storage for it.")
            self.plans[key] = value
            return copy.deepcopy(value)

    def submit(self, plan_id: str, confirmed: bool) -> dict:
        if confirmed is not True:
            raise AppError("Explicit approval of the displayed plan is required")
        with self.guard:
            if self.active:
                raise AppError("Another app job is already running")
            plan = self.plans.pop(plan_id, None)
            if not plan or plan["expires"] < time.time():
                raise AppError("Plan expired or was already used; create a fresh plan")
            self.active = True
            job_id = stamp()
            job = {"id": job_id, "app": plan["app"], "action": plan["action"], "status": "queued",
                   "stage": "Awaiting worker", "created": time.time()}
            self.jobs[job_id] = job
            write_json(self.root / "jobs" / (job_id + ".json"), job)
            self.worker.submit(self._job, job_id, plan)
            return copy.deepcopy(job)

    def _job_stage(self, job_id: str, stage: str, **extra):
        with self.guard:
            self.jobs[job_id].update(stage=stage, **extra)
            write_json(self.root / "jobs" / (job_id + ".json"), self.jobs[job_id])

    def _job(self, job_id: str, plan: dict):
        try:
            entry = self._addon_entry(plan["addon"]) if plan.get("addon") else None
            with operation_lock(self.root), (catalog.override(plan["app"], entry) if entry else contextlib.nullcontext()):
                self._job_stage(job_id, "Revalidating approved plan", status="running")
                baseline = self.preflight(plan["app"], plan["action"], plan["options"])
                if baseline != plan["baseline"]:
                    raise AppError("Installed state changed after planning; review a new plan")
                self._execute(plan, lambda message: self._job_stage(job_id, message))
            if entry and (self.root / "apps" / plan["app"] / "addon.json").is_file():
                catalog.register(plan["app"], entry)
            self._job_stage(job_id, "Completed", status="succeeded", finished=time.time())
        except (AppError, OSError, ValueError) as exc:
            message = str(exc) if isinstance(exc, AppError) else "Host operation failed; review local permissions and storage"
            self._job_stage(job_id, message, status="failed", finished=time.time())
        except Exception:
            self._job_stage(job_id, "Unexpected failure; inspect transaction state locally before retrying", status="failed", finished=time.time())
        finally:
            with self.guard:
                self.active = False
                # Keep a bounded in-memory history. Private files remain for diagnostics.
                for key in list(self.jobs)[:-64]:
                    del self.jobs[key]

    def job(self, identifier: str) -> dict:
        with self.guard:
            if identifier not in self.jobs:
                raise AppError("Unknown or expired job")
            return copy.deepcopy(self.jobs[identifier])

    def _seed(self, slug: str, locked_image: str, opts: dict | None = None):
        if catalog.is_addon(slug):
            return addon_runtime.seed(self, slug, opts)
        app = catalog.entry(slug)
        root = self.app_dir(slug)
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        data = checked_path(root / "data")
        data.mkdir(mode=0o700, exist_ok=True)
        seeded = False
        if not any(data.iterdir()):
            seeded = True
            if slug == "nodered":
                settings = {"uiPort": 1880, "httpAdminRoot": catalog.PREFIX + slug,
                            "httpNodeRoot": catalog.PREFIX + slug + "/flows",
                            "credentialSecret": secrets.token_urlsafe(48), "functionExternalModules": False}
                atomic(data / "settings.js", ("module.exports = " + json.dumps(settings, indent=2) + ";\n").encode())
            elif slug == "go2rtc":
                write_json(data / "go2rtc.yaml", {"api": {"listen": ":1984", "base_path": catalog.PREFIX + slug},
                          "rtsp": {"listen": ":8554"}, "webrtc": {"listen": ""}, "streams": {}})
            elif slug == "mosquitto":
                (data / "config").mkdir(mode=0o700)
                (data / "data").mkdir(mode=0o700)
                credentials = {"username": "opiha", "password": secrets.token_urlsafe(36)}
                write_json(root / "credentials.json", credentials)
                password_file = data / "config/passwordfile"
                atomic(password_file, (credentials["username"] + ":" + credentials["password"] + "\n").encode())
                set_owner(data, app["uid"])
                self.engine.command(["run", "--rm", "--network", "none", "--user", "1883:1883",
                                     "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
                                     "--entrypoint", "mosquitto_passwd", "--mount",
                                     f"type=bind,src={data / 'config'},dst=/credentials",
                                     locked_image, "-U", "/credentials/passwordfile"], timeout=60)
                if credentials["password"] in password_file.read_text() or ":$" not in password_file.read_text():
                    raise AppError("MQTT password hashing failed; no broker was started")
                atomic(data / "config/mosquitto.conf", b"listener 1883\nallow_anonymous false\npassword_file /mosquitto/config/passwordfile\npersistence true\npersistence_location /mosquitto/data/\nlog_dest stdout\n")
        if slug == "mosquitto" and not (data / "config/mosquitto.conf").is_file():
            raise AppError("Incomplete MQTT seed; inspect and remove the failed unused app data before retrying")
        if slug == "zwave":
            if not (root / "private.env").exists():
                atomic(root / "private.env", ("SESSION_SECRET=" + secrets.token_hex(32) + "\nDEFAULT_USERNAME=admin\nDEFAULT_PASSWORD=" + secrets.token_urlsafe(36) + "\n").encode())
            write_json(root / "server.json", {"serverEnabled": True, "serverHost": "0.0.0.0",
                                              "serverPort": 3000, "serverServiceDiscoveryDisabled": True})
        set_owner(data, app["uid"])

    def spec(self, slug: str, record: dict) -> dict:
        self.validate_record(slug, record)
        if catalog.is_addon(slug):
            return addon_runtime.spec(self, slug, record)
        app = catalog.entry(slug)
        opts = catalog.options(slug, record["options"])
        root = self.app_dir(slug)
        spec = {**opts, "uid": app["uid"], "image": record["image"], "network": self.config["network"],
                "ports": [(opts["port"], app["container_port"])],
                "mounts": [(str(checked_path(root / "data")), app["mount"], False)],
                "environment": {}, "command": []}
        if slug == "esphome":
            spec["environment"] = {"ESPHOME_DASHBOARD_USE_PING": "true", "ESPHOME_DEFAULT_COMPILE_PROCESS_LIMIT": "1"}
            spec["command"] = ["dashboard", "/config", "--port", "6052"]
        elif slug == "go2rtc":
            spec["ports"].append((28554, 8554))
        elif slug == "zwave":
            spec["ports"].append((23000, 3000))
            spec["environment"] = {"ZWAVE_EXTERNAL_SETTINGS": "/opiha/server.json", "ZWAVE_PORT": "/dev/zwave"}
            spec["mounts"].append((str(root / "server.json"), "/opiha/server.json", True))
            spec["env_file"] = str(root / "private.env")
        return spec

    def _execute(self, plan: dict, progress):
        slug, action, opts = plan["app"], plan["action"], plan["options"]
        old = self.record(slug)
        existing = self.engine.owned(slug)
        if action == "configure":
            progress("Writing add-on options")
            addon_runtime.write_options(self, slug, opts)
            write_json(self.app_dir(slug) / "record.json", {**old, "options": opts, "revision": stamp()})
            if existing.get("State", {}).get("Running"):
                self.engine.action(existing["Id"], slug, "restart")
            return
        info = plan.get("addon")
        if info:
            source = self.repos.addon_dir(info["repo"], info["folder"])
            if addon_runtime.tree_hash(source) != info["source_hash"]:
                raise AppError("Repository content changed after planning; review a new plan")
        if action in {"start", "stop", "restart", "remove"}:
            progress("Applying " + action + " to this app only")
            if action == "remove" and existing.get("State", {}).get("Running"):
                self.engine.action(existing["Id"], slug, "stop")
            if action in {"start", "restart"}:
                self.engine.restart_policy(existing["Id"], slug, opts["autostart"])
            self.engine.action(existing["Id"], slug, action)
            if action == "remove":
                old["installed"] = False
                old["revision"] = stamp()
                write_json(self.app_dir(slug) / "record.json", old)
            return
        app = catalog.entry(slug)
        root = self.app_dir(slug)
        if app.get("build"):
            progress("Building the add-on image on this device (this can take many minutes)")
            context = checked_path(root / "build")
            root.mkdir(parents=True, exist_ok=True, mode=0o700)
            if context.exists():
                shutil.rmtree(context)
            addon_runtime.copy_source(source, context)
            try:
                tag = "opiha-addon-" + slug + ":" + app["version"].lower()
                image_id = self.engine.build(tag, str(context), addon_runtime.build_args(app["manifest"], context), self.config["architecture"])
            finally:
                shutil.rmtree(context, ignore_errors=True)
            locked = image_id
        else:
            progress("Pulling and verifying native image")
            reference = old["image"] if old and not existing and old["options"] == opts else catalog.image(slug, opts)
            locked, image_id = self.engine.pull(reference, app["repository"], self.config["architecture"])
        self.engine.ensure_network(self.config["network"])
        if not existing:
            self._seed(slug, locked, opts)
        old_addon = None
        if info:
            previous_addon = root / "addon.json"
            old_addon = read_json(previous_addon) if previous_addon.is_file() else None
        new = {"schema": 1, "app": slug, "options": opts, "image": locked,
               "image_id": image_id, "revision": stamp(), "installed": True}
        if not existing:
            progress("Creating stopped app; no automatic production activation")
            spec = self.spec(slug, new)
            spec["autostart"] = False  # An installed but unreviewed app must not start on a later host boot.
            first = {"schema": 1, "app": slug, "phase": "first-install", "new": new, "old": old}
            write_json(root / "transaction.json", first)
            if info:
                addon_runtime.save_addon(self, slug, info["raw"], info["repo"], info["folder"])
            try:
                self.engine.create(slug, spec)
                write_json(root / "record.json", new)
                (root / "transaction.json").unlink()
            except Exception:
                self.repair(slug)
                raise
            return
        was_running = bool(existing.get("State", {}).get("Running"))
        backup = self.root / "rollbacks" / (slug + "-" + stamp())
        transaction = {"schema": 1, "app": slug, "old": old, "new": new,
                       "backup": str(backup), "was_running": was_running, "phase": "stopping"}
        if old_addon:
            transaction["old_addon"] = old_addon
        write_json(root / "transaction.json", transaction)
        if info:
            addon_runtime.save_addon(self, slug, info["raw"], info["repo"], info["folder"])
        try:
            progress("Stopping app and making a private rollback copy")
            self.engine.restart_policy(existing["Id"], slug, False)
            if was_running:
                self.engine.action(existing["Id"], slug, "stop")
            copy_tree(root / "data", backup)
            if info:
                addon_runtime.write_options(self, slug, opts)
            transaction["phase"] = "copied"
            write_json(root / "transaction.json", transaction)
            self.engine.action(existing["Id"], slug, "remove")
            progress("Creating replacement container")
            spec = self.spec(slug, new)
            spec["autostart"] = opts["autostart"] if was_running else False
            identifier = self.engine.create(slug, spec)
            write_json(root / "record.json", new)
            if was_running:
                self._hardware(slug, opts, self.engine.containers())
                self.engine.action(identifier, slug, "start")
                self._wait_running(identifier, slug)
            (root / "transaction.json").unlink()
            progress("Replacement complete; rollback state retained")
        except Exception:
            # Repair can still fail if storage or Docker is unavailable. Keep the journal.
            progress("Replacement failed; attempting state-matched rollback")
            self.repair(slug)
            raise AppError("Replacement failed; prior app state restored. Review before retrying")

    def _wait_running(self, identifier: str, slug: str):
        for attempt in range(60):
            row = self.engine.assert_owned(identifier, slug)
            state = row.get("State", {})
            health = state.get("Health", {}).get("Status")
            if state.get("Running") and health in {None, "healthy"}:
                # Running without a Docker healthcheck is not claimed as functional acceptance.
                return
            if state.get("Status") in {"exited", "dead"} or health == "unhealthy":
                raise AppError("Replacement container did not become runnable")
            time.sleep(2)
        raise AppError("Replacement container startup check timed out")

    def repair(self, slug: str):
        root = self.app_dir(slug)
        transaction = read_json(root / "transaction.json")
        if transaction.get("app") != slug:
            raise AppError("Invalid interrupted transaction")
        if transaction.get("phase") == "first-install":
            existing = self.engine.owned(slug)
            if existing:
                self.engine.restart_policy(existing["Id"], slug, False)
                if existing.get("State", {}).get("Running"):
                    self.engine.action(existing["Id"], slug, "stop")
                self.engine.action(existing["Id"], slug, "remove")
            old = transaction.get("old")
            if old:
                self.validate_record(slug, old)
                write_json(root / "record.json", old)
            else:
                (root / "record.json").unlink(missing_ok=True)
                if catalog.is_addon(slug):
                    (root / "addon.json").unlink(missing_ok=True)
            (root / "transaction.json").unlink()
            return
        if transaction.get("old_addon"):
            write_json(root / "addon.json", transaction["old_addon"])
            catalog.register(slug, addon_runtime.load_addon(root / "addon.json"))
        backup = checked_path(transaction["backup"])
        if backup.parent != self.root / "rollbacks":
            raise AppError("Rollback directory is outside managed storage")
        old = self.validate_record(slug, transaction["old"])
        if transaction["phase"] == "stopping":
            existing = self.engine.owned(slug)
            if not existing:
                raise AppError("Old container missing before snapshot completion; recover manually")
            self.engine.restart_policy(existing["Id"], slug, old["options"]["autostart"])
            if transaction["was_running"]:
                self.engine.action(existing["Id"], slug, "start")
        else:
            if not backup.is_dir():
                raise AppError("Required rollback copy is missing")
            existing = self.engine.owned(slug)
            if existing:
                if existing.get("State", {}).get("Running"):
                    self.engine.action(existing["Id"], slug, "stop")
                self.engine.action(existing["Id"], slug, "remove")
            if (root / "data").exists():
                failed = self.root / "rollbacks" / (slug + "-failed-" + stamp())
                os.replace(root / "data", failed)
            copy_tree(backup, root / "data")
            set_owner(root / "data", catalog.entry(slug)["uid"])
            spec = self.spec(slug, old)
            spec["autostart"] = old["options"]["autostart"] if transaction["was_running"] else False
            identifier = self.engine.create(slug, spec)
            write_json(root / "record.json", old)
            if transaction["was_running"]:
                self.engine.action(identifier, slug, "start")
        (root / "transaction.json").unlink()

    def logs(self, slug: str) -> dict:
        catalog.entry(slug)
        row = self.engine.owned(slug)
        if not row:
            raise AppError("No managed container for this app")
        return {"app": slug, "logs": self.engine.logs(row["Id"], slug), "private": True}

    def ingress(self, slug: str) -> dict:
        if not catalog.entry(slug)["ingress"]:
            raise AppError("This adapter has no reviewed in-HA web route")
        row, record = self.engine.owned(slug), self.record(slug)
        if not row or not record or not row.get("State", {}).get("Running"):
            raise AppError("The requested app is not running")
        return {"app": slug, "port": record["options"]["port"], "prefix": catalog.PREFIX + slug + "/"}

    def credentials(self, slug: str) -> dict:
        if slug != "mosquitto":
            raise AppError("This app has no generated account to reveal")
        return read_json(self.app_dir(slug) / "credentials.json")
