from __future__ import annotations
import argparse
import copy
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import urllib.error

from . import __version__, backup, compose, config, hardware, host, inventory, status
from .common import (ApplianceError, COMPONENTS, REPO, atomic_bytes, atomic_json,
                     exclusive_lock, private_mkdir, read_json, run, timestamp)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Orange Pi home-control appliance CLI. See docs/QUICKSTART.md.")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--config", type=Path, default=Path(os.environ.get("OPIHA_CONFIG", ".local/appliance.json")))
    sub = p.add_subparsers(dest="command", required=True)
    a = sub.add_parser("init", help="Initialize empty local state; never touches an existing installation")
    a.add_argument("--mode", choices=("lab", "appliance"), default="lab")
    a.add_argument("--data-dir")
    a = sub.add_parser("configure", help="Change explicit settings without restarting services")
    for name in ("ha-version", "timezone", "zwave-device", "camera-device", "dashboard-path", "ha-url"):
        a.add_argument("--" + name)
    a.add_argument("--lab-port", type=int)
    a.add_argument("--enable", choices=("zwave", "mqtt", "camera"), action="append", default=[])
    a.add_argument("--disable", choices=("zwave", "mqtt", "camera"), action="append", default=[])
    sub.add_parser("render", help="Print Compose JSON without starting containers")
    a = sub.add_parser("up", help="Start stack. Appliance restore requires activation first")
    a.add_argument("--onboarding", action="store_true", help="Allow only a new, unauthenticated appliance to start")
    sub.add_parser("down", help="Stop and remove project containers, preserving all state")
    a = sub.add_parser("activate", help="Arm production startup after the original HA/server are stopped")
    a.add_argument("--confirm-cutover", action="store_true", required=True)
    sub.add_parser("deactivate", help="Stop stack and remove production startup approval")
    sub.add_parser("doctor", help="Inspect prerequisites and hardware; no changes")
    sub.add_parser("status", help="HTTP responsiveness, camera status and free storage")
    hardware_parser = sub.add_parser("hardware", help="Read-only host hardware diagnostics")
    hardware_sub = hardware_parser.add_subparsers(dest="hardware_command", required=True)
    hardware_inventory = hardware_sub.add_parser("inventory", help="Collect sanitized host inventory")
    hardware_inventory.add_argument("--output", type=Path)
    hardware_inventory.add_argument("--private", action="store_true")
    for hardware_command in ("camera", "zwave", "storage"):
        hardware_sub.add_parser(hardware_command, help=f"Inspect {hardware_command} state")
    host_parser = sub.add_parser("host", help="Plan or apply the non-destructive live-host layout")
    host_sub = host_parser.add_subparsers(dest="host_command", required=True)
    for host_command in ("plan", "install"):
        host_action = host_sub.add_parser(host_command)
        host_action.add_argument("--root", type=Path, default=Path("/"))
        host_action.add_argument("--release", default=__version__)
        if host_command == "install":
            host_action.add_argument("--apply", action="store_true")
    a = sub.add_parser("serve", help="Run a read-only loopback diagnostic UI")
    a.add_argument("--port", type=int, default=8099)
    sub.add_parser("vision", help="Run low-rate OpenCV HOG person detection from go2rtc")
    a = sub.add_parser("lock-images", help="Pull release images and replace refs with verified registry digests")
    a.add_argument("--platform", choices=("linux/arm64", "linux/amd64"), required=True)
    a = sub.add_parser("inventory", help="Read HA registry identities without exposing credentials")
    a.add_argument("--ha-config", type=Path)
    a.add_argument("--output", type=Path)
    a = sub.add_parser("compare", help="Compare private inventory reports")
    a.add_argument("before", type=Path)
    a.add_argument("after", type=Path)
    a = sub.add_parser("live-check", help="Query HA version and unavailable entities with a private token file")
    a.add_argument("--token-file", type=Path, required=True)
    a.add_argument("--url")
    a.add_argument("--output", type=Path)
    a = sub.add_parser("sqlite-check", help="Run SQLite quick_check (prefer a stopped config)")
    a.add_argument("--database", type=Path)
    a = sub.add_parser("zwave-audit", help="Check stored key presence without printing values")
    a.add_argument("--store", type=Path)
    a = sub.add_parser("mqtt-init", help="Create a local-only broker account and password file")
    a.add_argument("--username", default="opiha")
    a = sub.add_parser("backup", help="Stop writers, snapshot, encrypt and restart previous containers")
    a.add_argument("--output", type=Path, required=True)
    a.add_argument("--recipient", help="Public age1... recipient, not a private identity")
    a.add_argument("--plaintext", action="store_true", help="Explicitly create an unencrypted lab bundle")
    a.add_argument("--signing-key", type=Path)
    add_offline(a)
    a = sub.add_parser("restore", help="Verify bundle; no state replacement without --apply")
    a.add_argument("--bundle", type=Path, required=True)
    a.add_argument("--identity", type=Path)
    a.add_argument("--signature", type=Path)
    a.add_argument("--trust-key", type=Path)
    a.add_argument("--apply", action="store_true")
    a.add_argument("--replace", action="store_true")
    a.add_argument("--apply-settings", action="store_true", help="Restore portable service settings (never lab isolation/host paths)")
    a.add_argument("--allow-version-change", action="store_true")
    add_offline(a)
    for name in ("import-config", "import-zwave"):
        a = sub.add_parser(name, help="Import a stopped raw configuration/store, preserving other components")
        a.add_argument("--source", type=Path, required=True)
        a.add_argument("--source-stopped", action="store_true", required=True)
        a.add_argument("--apply", action="store_true")
        a.add_argument("--replace", action="store_true")
        a.add_argument("--offline", action="store_true")
        a.add_argument("--allow-version-change", action="store_true")
    a = sub.add_parser("repair-restore", help="Recover interrupted atomic directory replacement")
    a.add_argument("--apply", action="store_true", required=True)
    a.add_argument("--source-stopped", action="store_true", required=True)
    a = sub.add_parser("signing-keygen", help="Create private Ed25519 recovery signing key and public trust key")
    a.add_argument("--private", type=Path, required=True)
    a.add_argument("--public", type=Path, required=True)
    a = sub.add_parser("vendor-hacs", help="Fetch a specific public HACS release and record its checksum")
    a.add_argument("--version", required=True)
    a = sub.add_parser("recover", help="Signed unattended recovery from explicitly mounted private media")
    a.add_argument("--media", type=Path, required=True)
    a.add_argument("--trust-key", type=Path, required=True)
    a.add_argument("--confirm-unattended", action="store_true", required=True)
    return p


def add_offline(p):
    p.add_argument("--offline", action="store_true", help="Do not contact Docker; caller must stop every state writer")
    p.add_argument("--source-stopped", action="store_true")


def emit(value: dict, output: Path | None = None) -> None:
    if output:
        atomic_json(output, value)
        print(f"Private report written to {output}")
    else:
        print(json.dumps(value, indent=2, sort_keys=True))


def check_version(version: str | None, cfg: dict, allow: bool = False) -> None:
    if not version:
        return
    import re
    if not re.fullmatch(r"[0-9]{4}\.[0-9]{1,2}\.[0-9]+", version):
        raise ApplianceError("Cannot automatically validate this source HA version; use official restore and review migration")
    source = tuple(map(int, version.split(".")))
    dest = tuple(map(int, cfg["ha_version"].split(".")))
    if source > dest:
        raise ApplianceError("Refusing HA downgrade. Configure the source HA version or a newer release first")
    if source != dest and not allow:
        raise ApplianceError(f"Source HA is {version}; configure that exact version or explicitly --allow-version-change")


def start(cfg: dict, onboarding: bool = False) -> None:
    data = config.ensure_state(cfg)
    work = Path(cfg["work_dir"])
    if (work / "restore-journal.json").exists():
        raise ApplianceError("Incomplete restore; repair before startup")
    if cfg["mode"] == "appliance" and not (work / "activated.json").exists():
        if not onboarding or (work / "restored.json").exists():
            raise ApplianceError("Production startup is disarmed. Stop the source HA/server, then activate --confirm-cutover")
    version = data / "ha/.HA_VERSION"
    check_version(version.read_text().strip() if version.exists() else None, cfg, allow=True)
    config.seed(cfg)
    compose.command(cfg, "up", "-d", "--remove-orphans", "homeassistant")
    if cfg["mode"] == "appliance":
        for feature, enabled in cfg["features"].items():
            if not enabled:
                continue
            isolated = copy.deepcopy(cfg)
            isolated["features"] = {k: k == feature for k in cfg["features"]}
            try:
                compose.verify_hardware(isolated)
                compose.command(cfg, "up", "-d", feature)
            except ApplianceError as exc:
                print(f"Optional service {feature} not started: {exc}", file=sys.stderr)


def do_backup(args, cfg: dict) -> None:
    if args.plaintext == bool(args.recipient):
        raise ApplianceError("Choose exactly one: --recipient age1... or --plaintext (lab only)")
    if args.plaintext and cfg["mode"] == "appliance":
        raise ApplianceError("Production snapshots require age encryption")
    output = args.output.resolve()
    data = config.ensure_state(cfg)
    if data in output.parents:
        raise ApplianceError("Backup output must be outside managed state")
    if output.exists() or output.with_suffix(output.suffix + ".sig").exists():
        raise ApplianceError("Backup destination already exists")
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    active = []
    try:
        with backup.quiesced(cfg, offline=args.offline, source_stopped=args.source_stopped) as active:
            with tempfile.TemporaryDirectory(prefix="backup-", dir=cfg["work_dir"]) as temp:
                clear = Path(temp) / "state.tar.gz"
                manifest = backup.create_tar(data, clear, config.portable_settings(cfg))
                if args.plaintext:
                    shutil.copyfile(clear, output)
                    os.chmod(output, 0o600)
                else:
                    backup.encrypt(clear, output, args.recipient)
                if args.signing_key:
                    backup.sign(output, output.with_suffix(output.suffix + ".sig"), args.signing_key)
                emit({"output": str(output), "files": len(manifest["files"]), "encrypted": not args.plaintext,
                      "signed": bool(args.signing_key), "external_database_included": False})
    finally:
        if active and not args.offline:
            compose.command(cfg, "up", "-d", *active)


def do_restore(args, cfg: dict, config_path: Path) -> None:
    data = config.ensure_state(cfg)
    if bool(args.signature) != bool(args.trust_key):
        raise ApplianceError("Supply both --signature and --trust-key")
    if args.signature:
        backup.verify_signature(args.bundle, args.signature, args.trust_key)
    if args.apply and not args.replace:
        raise ApplianceError("Replacing managed state requires --apply --replace")
    staging = Path(tempfile.mkdtemp(prefix=data.name + ".restore-", dir=data.parent))
    clear = None
    try:
        source = args.bundle
        if args.identity:
            clear = Path(cfg["work_dir"]) / ("decrypted-" + timestamp() + ".tar.gz")
            backup.decrypt(source, clear, args.identity)
            source = clear
        manifest = backup.extract_verified(source, staging)
        candidate = copy.deepcopy(cfg)
        if args.apply_settings:
            allowed = config.portable_settings(cfg)
            incoming = manifest.get("settings", {})
            candidate.update({k: incoming[k] for k in allowed if k in incoming})
            config.validate(candidate)
        check_version(manifest.get("homeassistant_version"), candidate, args.allow_version_change)
        # Never allow appliance settings to re-enable host networking or devices in the lab.
        if candidate["mode"] == "lab":
            candidate["features"] = {k: False for k in candidate["features"]}
        if not args.apply:
            emit({"verified": True, "files": len(manifest["files"]), "ha_version": manifest.get("homeassistant_version"),
                  "state_changed": False, "next": "Repeat with --apply --replace after reviewing versions and source shutdown"})
            return
        with backup.quiesced(cfg, offline=args.offline, source_stopped=args.source_stopped):
            previous = backup.commit_state(cfg, staging)
            atomic_json(config_path, candidate)
            # Broker image uses uid 1883. The outer managed root stays private.
            fix_runtime_permissions(candidate)
        emit({"restored": True, "previous_state": str(previous), "started": False,
              "next": "Inspect reports, activate production cutover explicitly, then up"})
    finally:
        if clear:
            clear.unlink(missing_ok=True)
        # Preserve staging when a crash journal needs it; otherwise clean temporary private data.
        if staging.exists() and not (Path(cfg["work_dir"]) / "restore-journal.json").exists():
            shutil.rmtree(staging)


def import_component(args, cfg: dict, component: str) -> None:
    source = args.source.resolve()
    data = config.ensure_state(cfg)
    if source == data or data in source.parents or source in data.parents:
        raise ApplianceError("Import source must be outside appliance state")
    if component == "ha":
        version = source / ".HA_VERSION"
        check_version(version.read_text().strip() if version.exists() else None, cfg, args.allow_version_change)
        if not (source / "configuration.yaml").exists():
            raise ApplianceError("Source is not an HA config directory")
    elif not source.is_dir() or not any(source.iterdir()):
        raise ApplianceError("Z-Wave source store is empty or absent")
    if not args.apply:
        emit({"component": component, "state_changed": False, "next": "Use --apply --replace when source and target writers are stopped"})
        return
    if not args.replace:
        raise ApplianceError("Import requires --replace to acknowledge component replacement")
    staging = Path(tempfile.mkdtemp(prefix=data.name + ".import-", dir=data.parent))
    try:
        with backup.quiesced(cfg, offline=args.offline, source_stopped=True):
            config.create_state(staging)
            for file, name in backup.state_files(data):
                if name.split("/")[0] == component:
                    continue
                target = staging / name
                private_mkdir(target.parent)
                shutil.copyfile(file, target)
                os.chmod(target, 0o600)
            if component == "ha":
                backup.copy_config(source, staging / "ha")
            else:
                # Same safe copy mechanism, without assuming an HA configuration file.
                for directory, dirs, files in os.walk(source, followlinks=False):
                    root = Path(directory)
                    for name in dirs + files:
                        if (root / name).is_symlink():
                            raise ApplianceError("Z-Wave source contains a symlink")
                    target = staging / "zwave" / root.relative_to(source)
                    private_mkdir(target)
                    for name in files:
                        import stat
                        if not stat.S_ISREG((root / name).stat().st_mode):
                            raise ApplianceError("Z-Wave source contains a special file")
                        shutil.copyfile(root / name, target / name)
                        os.chmod(target / name, 0o600)
            previous = backup.commit_state(cfg, staging)
            fix_runtime_permissions(cfg)
        emit({"imported": component, "previous_state": str(previous), "started": False})
    finally:
        if staging.exists() and not (Path(cfg["work_dir"]) / "restore-journal.json").exists():
            shutil.rmtree(staging)


def fix_runtime_permissions(cfg: dict) -> None:
    if cfg["mode"] != "appliance" or os.name != "posix" or os.geteuid() != 0:
        return
    data = Path(cfg["data_dir"])
    if cfg["features"]["mqtt"]:
        for root, dirs, files in os.walk(data / "mqtt"):
            os.chown(root, 1883, 1883)
            for name in files:
                os.chown(Path(root) / name, 1883, 1883)
    # Kiosk needs access only to its own profile, never HA or Z-Wave secrets.
    try:
        import pwd
        user = pwd.getpwnam("opiha-kiosk")
    except KeyError:
        return
    for root, dirs, files in os.walk(data / "kiosk"):
        os.chown(root, user.pw_uid, user.pw_gid)
        for name in files:
            os.chown(Path(root) / name, user.pw_uid, user.pw_gid)
    # Grant traverse to the managed parent, not read access. Individual components stay 0700.
    os.chmod(data, 0o711)


def mqtt_init(cfg: dict, username: str) -> None:
    import re, secrets
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", username):
        raise ApplianceError("Invalid MQTT username")
    d = config.ensure_state(cfg)
    path = d / "mqtt/config/passwordfile"
    if path.exists():
        raise ApplianceError("MQTT credentials already exist; refusing to rotate automatically")
    private_mkdir(path.parent)
    private_mkdir(d / "mqtt/data")
    password = secrets.token_urlsafe(32)
    # Convert a brand-new private staging file. Never pass passwords in process arguments.
    # Use the broker image's own utility when it is not installed natively.
    with tempfile.TemporaryDirectory(prefix=".mqtt-", dir=d / "private") as temporary:
        stage = Path(temporary) / "passwordfile"
        atomic_bytes(stage, f"{username}:{password}\n".encode())
        if shutil.which("mosquitto_passwd"):
            run(["mosquitto_passwd", "-U", str(stage)], capture=True)
        else:
            run(["docker", "run", "--rm", "--network", "none", "--user", "0:0",
                 "--entrypoint", "mosquitto_passwd", "--mount",
                 f"type=bind,source={temporary},target=/credentials",
                 cfg["images"]["mqtt"], "-U", "/credentials/passwordfile"], capture=True)
        if stage.read_text().strip() == f"{username}:{password}":
            raise ApplianceError("MQTT password hashing did not produce a hashed record")
        atomic_bytes(path, stage.read_bytes())
    atomic_json(d / "private/mqtt-account.json", {"username": username, "password": password})
    atomic_bytes(d / "mqtt/config/mosquitto.conf", b"listener 1883\nallow_anonymous false\npassword_file /mosquitto/config/passwordfile\npersistence true\npersistence_location /mosquitto/data/\nlog_dest stdout\n")
    fix_runtime_permissions(cfg)
    print("MQTT credentials stored privately; the broker only publishes a loopback port.")


def recover(args, cfg: dict, path: Path) -> None:
    if cfg["mode"] != "appliance":
        raise ApplianceError("Unattended recovery is only for appliance mode")
    if not args.trust_key.is_file():
        raise ApplianceError("A public recovery trust key must be baked into the image")
    # Only bootstrap a clean appliance. Never silently replace an active household.
    d = config.ensure_state(cfg)
    if any((d / "ha").iterdir()) or (Path(cfg["work_dir"]) / "restored.json").exists():
        raise ApplianceError("Unattended recovery only operates on empty fresh state")
    bundle = args.media / "state.tar.age"
    signature = args.media / "state.tar.age.sig"
    identity = args.media / "identity.txt"
    if not all(p.is_file() for p in (bundle, signature, identity)):
        raise ApplianceError("Recovery media must contain state.tar.age, its .sig, and identity.txt")
    # Signature verification happens before decryption. Keys are never copied to the public image.
    restore = argparse.Namespace(bundle=bundle, signature=signature, trust_key=args.trust_key, identity=identity,
        apply=True, replace=True, apply_settings=True, allow_version_change=False, offline=True, source_stopped=True)
    do_restore(restore, cfg, path)
    atomic_json(Path(cfg["work_dir"]) / "activated.json", {"at": timestamp(), "method": "signed-recovery"})
    print("Signed recovery completed. Source servers must remain stopped; appliance is armed.")


def dispatch(args) -> int:
    path = args.config.resolve()
    command = args.command
    if command == "hardware":
        if args.hardware_command == "inventory":
            if args.private and not args.output:
                raise ApplianceError("Private hardware inventory requires --output outside the repository")
            result = hardware.collect_inventory(private=args.private)
            if args.output:
                hardware.write_inventory(result, args.output, private=args.private)
                print(f"Hardware inventory written to {args.output}")
            else:
                emit(result)
        else:
            emit(hardware.collect_section(args.hardware_command))
        return 0
    if command == "host":
        root = args.root.absolute()
        if args.host_command == "install" and args.apply:
            if root == Path("/") and os.geteuid() != 0:
                raise ApplianceError("Applying the live host install requires root")
            emit(host.install(root=root, release=args.release))
        else:
            emit(host.plan(root=root, release=args.release))
        return 0
    if command == "init":
        cfg = config.initialize(path, args.mode, args.data_dir)
        emit({"initialized": str(path), "mode": cfg["mode"], "data": cfg["data_dir"], "started": False})
        return 0
    if command == "compare":
        result = inventory.compare(read_json(args.before), read_json(args.after))
        emit(result)
        return 0 if result["matches"] else 1
    if command == "signing-keygen":
        if args.private.exists() or args.public.exists():
            raise ApplianceError("Key destination already exists")
        private_mkdir(args.private.resolve().parent)
        args.public.resolve().parent.mkdir(parents=True, exist_ok=True)
        run(["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(args.private)])
        os.chmod(args.private, 0o600)
        run(["openssl", "pkey", "-in", str(args.private), "-pubout", "-out", str(args.public)])
        print("Public trust key may be committed. Private signing key must remain outside the repository.")
        return 0
    if command == "vendor-hacs":
        from .vendor import fetch_hacs
        emit(fetch_hacs(args.version))
        return 0
    if command == "inventory" and args.ha_config:
        emit(inventory.inventory(args.ha_config), args.output)
        return 0
    cfg = config.load(path)
    if command in ("serve", "vision"):
        if command == "serve":
            from .server import make_server
            server = make_server(cfg, port=args.port)
            try:
                server.serve_forever()
            finally:
                server.server_close()
        else:
            if not cfg["features"]["camera"]:
                raise ApplianceError("Camera feature is disabled")
            from .vision import run_vision
            run_vision(cfg)
        return 0
    if command in ("render", "status", "doctor", "inventory", "live-check", "sqlite-check", "zwave-audit"):
        if command == "render":
            emit(compose.generate(cfg))
        elif command == "status":
            emit(status.snapshot(cfg))
        elif command == "doctor":
            emit(status.doctor(cfg))
        elif command == "inventory":
            emit(inventory.inventory(Path(cfg["data_dir"]) / "ha"), args.output)
        elif command == "live-check":
            emit(status.live_check(args.url or cfg["ha_url"], args.token_file), args.output)
        elif command == "sqlite-check":
            result = inventory.sqlite_check(args.database or Path(cfg["data_dir"]) / "ha/home-assistant_v2.db")
            emit({"sqlite_quick_check": result})
            return 0 if result in ("ok", "absent") else 1
        elif command == "zwave-audit":
            emit(inventory.zwave_audit(args.store or Path(cfg["data_dir"]) / "zwave"))
        return 0
    with exclusive_lock(Path(cfg["work_dir"])):
        if command == "configure":
            for key in ("timezone", "zwave_device", "camera_device", "dashboard_path", "ha_url", "lab_port"):
                value = getattr(args, key)
                if value is not None:
                    cfg[key] = value
            if args.lab_port and cfg["mode"] == "lab" and not args.ha_url:
                cfg["ha_url"] = f"http://127.0.0.1:{args.lab_port}"
            if args.ha_version:
                cfg["ha_version"] = args.ha_version
                cfg["images"]["homeassistant"] = "ghcr.io/home-assistant/home-assistant:" + args.ha_version
            for feature in args.enable:
                cfg["features"][feature] = True
            for feature in args.disable:
                cfg["features"][feature] = False
            config.validate(cfg)
            atomic_json(path, cfg)
            print("Configuration saved. Running services were not restarted.")
        elif command == "up":
            start(cfg, args.onboarding)
        elif command == "down":
            compose.command(cfg, "down", "--timeout", "120")
        elif command == "activate":
            if cfg["mode"] != "appliance":
                raise ApplianceError("Lab startup does not require production activation")
            atomic_json(Path(cfg["work_dir"]) / "activated.json", {"at": timestamp(), "method": "explicit-cutover"})
            print("Production startup armed. Do not run the old HA or Z-Wave server concurrently.")
        elif command == "deactivate":
            compose.command(cfg, "down", "--timeout", "120")
            (Path(cfg["work_dir"]) / "activated.json").unlink(missing_ok=True)
        elif command == "lock-images":
            atomic_json(path, compose.lock_images(cfg, args.platform))
            print("Images digest-locked in the private runtime configuration.")
        elif command == "backup":
            do_backup(args, cfg)
        elif command == "restore":
            do_restore(args, cfg, path)
        elif command in ("import-config", "import-zwave"):
            import_component(args, cfg, "ha" if command == "import-config" else "zwave")
        elif command == "repair-restore":
            backup.repair_restore(cfg)
            print("Prior state restored. Production startup remains disarmed.")
        elif command == "mqtt-init":
            mqtt_init(cfg, args.username)
        elif command == "recover":
            recover(args, cfg, path)
        else:
            raise ApplianceError("Unknown operation")
    return 0


def main(argv: list[str] | None = None) -> int:
    os.umask(0o077)
    try:
        return dispatch(parser().parse_args(argv))
    except KeyboardInterrupt:
        return 130
    except (ApplianceError, OSError, KeyError, TypeError, ValueError) as exc:
        # Avoid dumping private settings/token payloads in tracebacks.
        print(f"opiha: {exc}", file=sys.stderr)
        return 2
