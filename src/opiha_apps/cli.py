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
    a = sub.add_parser("app", help="Plan one app operation; --apply executes the reviewed plan")
    a.add_argument("action", choices=("install", "update", "start", "stop", "restart", "remove"))
    a.add_argument("app")
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
        cfg = validate_config(read_json(args.config.absolute()))
        from .manager import Manager
        manager = Manager(cfg)
        try:
            if args.command == "serve":
                from .server import make_server
                server = make_server(manager, port=cfg["port"])
                try:
                    server.serve_forever()
                finally:
                    server.server_close()
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
                plan = manager.plan(args.app, args.action, opts)
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
