from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import platform
import sys
import time
from . import __version__
from .common import AppError, defaults, initialize, operation_lock, read_json, read_token, validate_config, write_json


def parser():
    p = argparse.ArgumentParser(description="Native Orange Pi app manager, not Home Assistant Supervisor")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--config", type=Path, default=Path("/etc/orangepi-apps/config.json"))
    sub = p.add_subparsers(dest="command", required=True)
    a = sub.add_parser("install-host", help="Preview native host/panel installation; nothing starts automatically")
    a.add_argument("--root", type=Path, default=Path("/"))
    a.add_argument("--appliance-config", default="/etc/orangepi-homeassistant/appliance.json")
    a.add_argument("--architecture", choices=("arm64", "amd64"))
    a.add_argument("--adopt-restored-panel", action="store_true", help="Accept byte-identical panel files restored by a HA backup; never take over unrelated state")
    a.add_argument("--apply", action="store_true")
    a = sub.add_parser("init", help="Create private manager configuration for a dedicated test workspace")
    a.add_argument("--data-dir", required=True)
    a.add_argument("--architecture", choices=("arm64", "amd64"), required=True)
    a.add_argument("--port", type=int, default=8098)
    for name in ("catalog", "doctor", "overview", "metrics", "serve"):
        sub.add_parser(name)
    a = sub.add_parser("host-terminal", help="Allow or forbid the admin-only host terminal in the Orange Pi panel (needs a manager restart)")
    a.add_argument("state", choices=("on", "off"))
    a.add_argument("--user", help="Host account the terminal runs as (default: orangepi)")
    a = sub.add_parser("app", help="Plan one app operation; --apply executes the reviewed plan")
    a.add_argument("action", choices=("install", "update", "start", "stop", "restart", "remove", "configure", "backup", "restore"))
    a.add_argument("app")
    a.add_argument("--options-file", type=Path)
    a.add_argument("--backup-id", help="Backup to restore (see opiha-apps app ... via the Add-ons tab or the API)")
    a.add_argument("--apply", action="store_true")
    a.add_argument("--confirm-network-access", action="store_true")
    a = sub.add_parser("repo", help="Manage Home Assistant add-on repositories (git, https only)")
    a.add_argument("verb", choices=("list", "add", "refresh", "remove", "addons"))
    a.add_argument("value", nargs="?", help="URL for add, repository id otherwise")
    a = sub.add_parser("addon", help="Plan installing an add-on from an added repository; --apply executes the plan")
    a.add_argument("repository")
    a.add_argument("folder")
    a.add_argument("--options-file", type=Path)
    a.add_argument("--apply", action="store_true")
    a.add_argument("--confirm-network-access", action="store_true")
    a = sub.add_parser("repair", help="Repair an interrupted app update; stops/recreates only this managed app")
    a.add_argument("app")
    a.add_argument("--apply", action="store_true", required=True)
    a = sub.add_parser("logs"); a.add_argument("app")
    a = sub.add_parser("backup")
    a.add_argument("--output", type=Path, required=True)
    a.add_argument("--recipient")
    a.add_argument("--signing-key", type=Path)
    a.add_argument("--plaintext", action="store_true")
    a = sub.add_parser("restore", help="Verify or stage native-app backup into a NEW directory, never overwrite live state")
    a.add_argument("--bundle", type=Path, required=True)
    a.add_argument("--destination", type=Path, required=True)
    a.add_argument("--identity", type=Path)
    a.add_argument("--signature", type=Path)
    a.add_argument("--trust-key", type=Path)
    a.add_argument("--apply", action="store_true")
    return p


def emit(value):
    print(json.dumps(value, indent=2, sort_keys=True))


def main(argv=None):
    os.umask(0o077)
    args = parser().parse_args(argv)
    try:
        if args.command == "install-host":
            from .install import install
            emit(install(root=args.root, appliance=args.appliance_config, apply=args.apply, architecture=args.architecture, adopt_restored=args.adopt_restored_panel))
            return 0
        if args.command == "catalog":
            from .catalog import public_catalog
            emit(public_catalog()); return 0
        if args.command == "init":
            if args.config.exists():
                raise AppError("Manager configuration already exists")
            cfg = defaults()
            cfg.update(data_dir=str(Path(args.data_dir).absolute()), token_file=str(args.config.absolute().with_name("token")),
                       architecture=args.architecture, port=args.port)
            initialize(cfg)
            write_json(args.config.absolute(), cfg)
            emit({"initialized": str(args.config.absolute()), "started": False}); return 0
        if args.command == "restore":
            from .backup import restore
            emit(restore(args.bundle, args.destination, identity=args.identity, signature=args.signature,
                         trust_key=args.trust_key, apply=args.apply)); return 0
        if args.command == "host-terminal":
            current = validate_config(read_json(args.config.absolute()))
            current["host_terminal"] = args.state == "on"
            if args.user:
                current["host_user"] = args.user
            write_json(args.config.absolute(), validate_config(current))
            emit({"host_terminal": current["host_terminal"], "host_user": current["host_user"],
                  "next": "sudo systemctl restart orangepi-apps.service"}); return 0
        cfg = validate_config(read_json(args.config.absolute()))
        from .manager import Manager
        manager = Manager(cfg)
        try:
            if args.command == "serve":
                import threading
                from .server import make_server
                from .supervisor_api import Shim, run_forever
                server = make_server(manager, port=cfg["port"])
                stop = threading.Event()
                from . import addon_runtime
                if addon_runtime.real_supervisor():
                    manager.shim_state.update(error="The Home Assistant Supervisor manages add-ons on this host")
                else:
                    threading.Thread(target=run_forever, args=(Shim(manager), stop), daemon=True, name="opiha-supervisor-shim").start()
                try:
                    server.serve_forever()
                finally:
                    stop.set()
                    server.server_close()
            elif args.command == "repo":
                if args.verb == "list":
                    emit(manager.repos.list())
                elif not args.value:
                    raise AppError("A URL or repository id is required")
                elif args.verb == "add":
                    emit(manager.repos.add(args.value))
                elif args.verb == "refresh":
                    emit(manager.repos.refresh(args.value))
                elif args.verb == "remove":
                    manager.repos.remove(args.value); emit({"removed": args.value})
                else:
                    emit([{"folder": r["folder"], "name": r.get("manifest", {}).get("name"), "version": r.get("manifest", {}).get("version"),
                           "status": r.get("report", {}).get("status", "invalid"), "error": r.get("error")}
                          for r in manager.repos.addons(args.value)])
            elif args.command == "addon":
                opts = read_json(args.options_file.absolute()) if args.options_file else None
                plan = manager.plan_addon(args.repository, args.folder, opts)
                emit(plan)
                if args.apply:
                    if not args.confirm_network_access:
                        raise AppError("Execution requires --confirm-network-access; add-ons are third-party code that can reach your LAN")
                    job = manager.submit(plan["id"], True)
                    while manager.job(job["id"])["status"] in {"queued", "running"}:
                        time.sleep(.5)
                    result = manager.job(job["id"]); emit(result)
                    return 0 if result["status"] == "succeeded" else 1
            elif args.command in {"overview", "metrics", "doctor"}:
                value = manager.overview(include_stats=args.command == "metrics")
                if args.command == "doctor":
                    try:
                        manager._architecture(); value["native_engine_ready"] = True
                    except AppError as exc:
                        value["native_engine_ready"] = False; value["reason"] = str(exc)
                emit(value)
                if value.get("engine_error") or value.get("native_engine_ready") is False:
                    return 1
            elif args.command == "app":
                opts = read_json(args.options_file.absolute()) if args.options_file else None
                plan = manager.plan(args.app, args.action, opts, backup=args.backup_id)
                emit(plan)
                if args.apply:
                    if args.action in {"install", "update", "start", "restart"} and not args.confirm_network_access:
                        raise AppError("Execution requires --confirm-network-access; these apps can reach your LAN")
                    job = manager.submit(plan["id"], True)
                    while manager.job(job["id"])["status"] in {"queued", "running"}:
                        time.sleep(.2)
                    result = manager.job(job["id"]); emit(result)
                    return 0 if result["status"] == "succeeded" else 1
            elif args.command == "repair":
                with operation_lock(manager.root):
                    manager.repair(args.app)
                emit({"repaired": args.app})
            elif args.command == "logs":
                emit(manager.logs(args.app))
            elif args.command == "backup":
                from .backup import create
                emit(create(manager, args.output, recipient=args.recipient, signing_key=args.signing_key, plaintext=args.plaintext))
            return 0
        finally:
            manager.close()
    except KeyboardInterrupt:
        return 130
    except (AppError, OSError, ValueError, KeyError, TypeError) as exc:
        message = str(exc) if isinstance(exc, AppError) else "Operation failed; inspect local prerequisites and private configuration"
        print("opiha-apps: " + message, file=sys.stderr)
        return 2
