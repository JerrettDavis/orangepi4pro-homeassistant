"""paseo-fleet command line: provision, register, inspect and dispatch to Paseo daemons."""

from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import time

from . import render
from .inventory import Host, Inventory, InventoryError, load

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INVENTORY = ROOT / ".local" / "paseo-fleet" / "inventory.json"
SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "-o", "StrictHostKeyChecking=accept-new"]


class FleetError(RuntimeError):
    pass


def _state_dir(inv: Inventory) -> Path:
    return (inv.source.parent if inv.source else DEFAULT_INVENTORY.parent)


def _read_env_file(inv: Inventory, host: Host) -> str | None:
    if not host.env_file:
        return None
    path = Path(host.env_file)
    if not path.is_absolute():
        path = _state_dir(inv) / path
    if not path.is_file():
        raise FleetError(f"{host.id}: env_file not found: {path}")
    return path.read_text(encoding="utf-8")


def docker_password(inv: Inventory, host: Host, create: bool = False) -> str | None:
    path = _state_dir(inv) / "secrets" / f"{host.id}.password"
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    if not create:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    password = secrets.token_urlsafe(32)
    path.write_text(password + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return password


def paseo_binary() -> str:
    override = os.environ.get("PASEO_FLEET_PASEO")
    if override:
        return override
    if os.name == "nt":
        candidate = Path(os.environ.get("LOCALAPPDATA", "")) / "paseo-fleet" / "cli" / "node_modules" / ".bin" / "paseo.cmd"
    else:
        candidate = Path.home() / ".local" / "bin" / "paseo"
    if candidate.is_file():
        return str(candidate)
    found = shutil.which("paseo")
    if found:
        return found
    raise FleetError("paseo CLI not found; provision the hub first (provision --host <hub id>)")


def _ssh_base(host: Host) -> list[str]:
    cmd = ["ssh", *SSH_OPTS]
    if host.ssh_port:
        cmd += ["-p", str(host.ssh_port)]
    return cmd + [host.ssh]


def _host_os(host: Host) -> str:
    return "windows" if host.is_windows else "posix"


def build_artifacts(inv: Inventory, host: Host, create_secrets: bool = False) -> dict:
    """Everything needed to provision one host, as data (used by plan and provision)."""
    env_content = _read_env_file(inv, host)
    if host.is_docker:
        password = docker_password(inv, host, create=create_secrets) or "<generated-on-provision>"
        files = render.render_docker_files(host, inv, has_agent_env=env_content is not None)
        files[".env"] = f"PASEO_PASSWORD={password}\n"
        if env_content is not None:
            files["agent.env"] = env_content
        return {"kind": "docker", "files": files, "secrets": [password, env_content or ""]}
    if host.is_windows:
        script = render.render_windows(host, inv, env_content)
        return {"kind": "powershell", "script": script, "secrets": [env_content or ""]}
    script = render.render_posix(host, inv, env_content)
    return {"kind": "sh", "script": script, "secrets": [env_content or ""]}


def _run(cmd: list[str], stdin: str | None = None, timeout: int = 900) -> int:
    # Bytes, not text mode: Windows text mode would turn \n into \r\n and break sh.
    data = stdin.encode("utf-8") if stdin is not None else None
    return subprocess.run(cmd, input=data, timeout=timeout).returncode


def _provision_docker_local(inv: Inventory, host: Host, art: dict) -> None:
    directory = _state_dir(inv) / "docker" / host.id
    directory.mkdir(parents=True, exist_ok=True)
    for name, content in art["files"].items():
        (directory / name).write_text(content, encoding="utf-8", newline="\n")
    code = subprocess.run(
        ["docker", "compose", "-p", render.docker_project(host), "up", "-d", "--build"],
        cwd=directory).returncode
    if code != 0:
        raise FleetError(f"{host.id}: docker compose failed ({code})")
    _wait_health(host)


def _wait_health(host: Host, seconds: int = 90) -> None:
    from urllib.request import urlopen
    deadline = time.time() + seconds
    url = f"http://127.0.0.1:{host.daemon_port}/api/health"
    while time.time() < deadline:
        try:
            with urlopen(url, timeout=3) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(1)
    raise FleetError(f"{host.id}: daemon not healthy at {url}")


def provision_host(inv: Inventory, host: Host, dry_run: bool = False) -> None:
    art = build_artifacts(inv, host, create_secrets=not dry_run)
    if dry_run:
        print(f"--- {host.id} ({host.platform}, {host.transport}) [{art['kind']}] ---")
        if art["kind"] == "docker":
            for name, content in art["files"].items():
                shown = render.redact(content, art["secrets"]) if name in (".env", "agent.env") else content
                print(f"# {name}\n{shown}")
        else:
            print(render.redact(art["script"], art["secrets"]))
        return
    print(f"==> provisioning {host.id} ({host.platform}, {host.transport})", flush=True)
    if art["kind"] == "docker":
        if host.transport == "local":
            _provision_docker_local(inv, host, art)
            return
        script = render.render_docker_remote(host, art["files"])
        code = _run([*_ssh_base(host), "sh", "-s"], stdin=script)
    elif art["kind"] == "sh":
        if host.transport == "local":
            code = _run(["sh", "-s"], stdin=art["script"])
        else:
            code = _run([*_ssh_base(host), "sh", "-s"], stdin=art["script"])
    else:
        if host.transport == "local":
            rendered = _state_dir(inv) / "rendered"
            rendered.mkdir(parents=True, exist_ok=True)
            path = rendered / f"{host.id}.ps1"
            path.write_text(art["script"], encoding="utf-8-sig")
            env = {k: v for k, v in os.environ.items() if k.upper() != "PSMODULEPATH"}
            try:
                code = subprocess.run(
                    ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(path)],
                    env=env).returncode
            finally:
                path.unlink(missing_ok=True)
        else:
            encoded = base64.b64encode(art["script"].encode("utf-16-le")).decode()
            code = _run([*_ssh_base(host), "powershell", "-NoProfile", "-EncodedCommand", encoded])
    if code != 0:
        raise FleetError(f"{host.id}: provisioning failed (exit {code})")


def _paseo(host: Host, inv: Inventory, *args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    password = docker_password(inv, host) if host.is_docker else None
    if password:
        env["PASEO_PASSWORD"] = password
    return subprocess.run(
        [paseo_binary(), "--host", render.connection(host), *args],
        capture_output=True, text=True, timeout=timeout, env=env)


def _json(proc: subprocess.CompletedProcess):
    try:
        return json.loads(proc.stdout)
    except (json.JSONDecodeError, TypeError):
        return None


def host_status(inv: Inventory, host: Host) -> dict:
    row = {"id": host.id, "platform": host.platform, "transport": host.transport,
           "labels": list(host.labels), "reachable": False, "detail": ""}
    try:
        proc = _paseo(host, inv, "ls", "--json")
    except (subprocess.TimeoutExpired, FleetError) as exc:
        row["detail"] = str(exc)
        return row
    listing = _json(proc)
    if proc.returncode != 0 or not isinstance(listing, list):
        text = (proc.stderr or proc.stdout).strip()
        try:
            text = json.loads(text)["error"]["message"]
        except (ValueError, KeyError, TypeError):
            text = text.splitlines()[-1] if text else f"exit {proc.returncode}"
        row["detail"] = text
        return row
    row["reachable"] = True
    row["agents"] = len(listing)
    row["running"] = sum(1 for a in listing if str(a.get("status", "")).lower() == "running")
    return row


def _local_repo_dirs(host: Host) -> list[str]:
    """Git repos directly under a workspace root whose filesystem this machine can see."""
    if host.transport != "local":
        return []
    base = Path(host.workspace_mount) if host.is_docker and host.workspace_mount else (
        None if host.is_docker else Path(render.workspace_root(host)))
    if base is None or not base.is_dir():
        return []
    sep = "/" if host.is_docker else os.sep
    root = render.workspace_root(host).rstrip("/\\")
    return [f"{root}{sep}{child.name}" for child in sorted(base.iterdir()) if (child / ".git").exists()]


def cmd_workspaces(inv: Inventory, args) -> int:
    failed = 0
    for host in inv.select(args.host, args.label):
        listing = _json(_paseo(host, inv, "project", "ls", "--json"))
        if listing is None:
            print(f"!! {host.id}: daemon not reachable", file=sys.stderr)
            failed += 1
            continue
        known = {str(p.get("path", "")).rstrip("/\\").lower() for p in listing}
        wanted = [render.workspace_root(host), *(_local_repo_dirs(host) if args.repos else [])]
        for path in wanted:
            tail = path[1:].rstrip("/\\").lower() if path.startswith("~/") else None
            if path.rstrip("/\\").lower() in known or (tail and any(k.endswith(tail) for k in known)):
                print(f"= {host.id}: {path}")
                continue
            try:
                proc = _paseo(host, inv, "project", "create", path, "--json", timeout=240)
            except subprocess.TimeoutExpired:
                failed += path == wanted[0]
                print(f"!! {host.id}: {path}: timed out", file=sys.stderr)
                continue
            if proc.returncode == 0:
                print(f"+ {host.id}: {path}")
            else:
                # A broken individual repo must not fail the fleet; only the root is mandatory.
                failed += path == wanted[0]
                print(f"!! {host.id}: {path}: {' '.join((proc.stderr or proc.stdout).split())[:300]}", file=sys.stderr)
    return 1 if failed else 0


def cmd_validate(inv: Inventory, args) -> int:
    print(f"inventory OK: {len(inv.hosts)} host(s), paseo {inv.paseo_version}, node {inv.node_version}")
    for h in inv.hosts:
        flags = "hub " if h.hub else ""
        print(f"  {h.id:<20} {h.platform:<8} {h.transport:<6} port {h.daemon_port} {flags}{','.join(h.labels)}")
    return 0


def cmd_plan(inv: Inventory, args) -> int:
    for host in inv.select(args.host, args.label):
        provision_host(inv, host, dry_run=True)
    return 0


def cmd_provision(inv: Inventory, args) -> int:
    hosts = inv.select(args.host, args.label)
    if not hosts:
        raise FleetError("no hosts selected")
    failures = []
    for host in hosts:
        try:
            provision_host(inv, host)
        except (FleetError, subprocess.TimeoutExpired) as exc:
            print(f"!! {exc}", file=sys.stderr)
            failures.append(host.id)
    if failures:
        print(f"failed: {', '.join(failures)}", file=sys.stderr)
        return 1
    return 0


def _hub_args(inv: Inventory) -> list[str]:
    return [paseo_binary(), "--host", render.connection(inv.hub)]


def cmd_register(inv: Inventory, args) -> int:
    hub = inv.hub
    existing = subprocess.run([*_hub_args(inv), "host", "ls", "--json"], capture_output=True, text=True, timeout=60)
    if existing.returncode != 0:
        raise FleetError("hub daemon not reachable: " + (existing.stderr or existing.stdout).strip())
    saved = _json(existing)
    known = json.dumps(saved) if saved is not None else existing.stdout
    failed = 0
    for host in inv.select(args.host, args.label):
        if host.id == hub.id:
            continue
        password = docker_password(inv, host) if host.is_docker else None
        conn = render.connection(host, password)
        if f'"{host.id}"' in known or host.id in known:
            print(f"= {host.id} already registered")
            continue
        proc = subprocess.run([*_hub_args(inv), "host", "add", conn, "--label", host.id,
                               "--meta", f"platform={host.platform}", "--meta", f"labels={','.join(host.labels)}"],
                              capture_output=True, text=True, timeout=60)
        if proc.returncode == 0:
            print(f"+ {host.id} registered")
        else:
            failed += 1
            print(f"!! {host.id}: {render.redact((proc.stderr or proc.stdout).strip(), [password or ''])}", file=sys.stderr)
    return 1 if failed else 0


def cmd_status(inv: Inventory, args) -> int:
    rows = [host_status(inv, h) for h in inv.select(args.host, args.label)]
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        print(f"{'HOST':<20} {'PLATFORM':<8} {'UP':<4} {'AGENTS':<7} DETAIL")
        for r in rows:
            print(f"{r['id']:<20} {r['platform']:<8} {'yes' if r['reachable'] else 'NO':<4} "
                  f"{str(r.get('running', '-')) + '/' + str(r.get('agents', '-')):<7} {r['detail']}")
    return 0 if all(r["reachable"] for r in rows) else 1


def cmd_dispatch(inv: Inventory, args) -> int:
    candidates = [h for h in inv.select(args.host, args.label) if h.id != inv.hub.id or args.include_hub]
    scored = []
    for host in candidates:
        row = host_status(inv, host)
        if row["reachable"]:
            scored.append((row.get("running", 0), host))
    if not scored:
        raise FleetError("no reachable host matches the selection")
    scored.sort(key=lambda item: (item[0], item[1].id))
    host = scored[0][1]
    cwd = args.cwd or render.workspace_root(host)
    cmd = ["run", "--no-wait", "--cwd", cwd, "--label", f"fleet-host={host.id}"]
    if args.provider:
        cmd += ["--provider", args.provider]
    if args.title:
        cmd += ["--title", args.title]
    cmd.append(args.prompt)
    print(f"dispatching to {host.id} ({scored[0][0]} running)", flush=True)
    proc = _paseo(host, inv, *cmd, timeout=120)
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    return proc.returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="paseo-fleet", description=__doc__)
    parser.add_argument("--inventory", type=Path,
                        default=Path(os.environ.get("PASEO_FLEET_INVENTORY", DEFAULT_INVENTORY)))
    sub = parser.add_subparsers(dest="command", required=True)

    def selector(p):
        p.add_argument("--host", action="append", help="host id (repeatable); default all enabled")
        p.add_argument("--label", action="append", help="require label (repeatable)")

    sub.add_parser("validate", help="validate the inventory").set_defaults(func=cmd_validate)
    p = sub.add_parser("plan", help="print what provisioning would run (secrets redacted)")
    selector(p)
    p.set_defaults(func=cmd_plan)
    p = sub.add_parser("provision", help="install/upgrade the daemon service on hosts")
    selector(p)
    p.set_defaults(func=cmd_provision)
    p = sub.add_parser("register", help="save the fleet's hosts in the hub daemon")
    selector(p)
    p.set_defaults(func=cmd_register)
    p = sub.add_parser("workspaces", help="register each host's workspace root (and local repos) as Paseo projects")
    selector(p)
    p.add_argument("--repos", action="store_true", help="also register git repos directly under local roots")
    p.set_defaults(func=cmd_workspaces)
    p = sub.add_parser("status", help="probe every host")
    selector(p)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_status)
    p = sub.add_parser("dispatch", help="start an agent on the least-busy matching host")
    selector(p)
    p.add_argument("prompt")
    p.add_argument("--provider")
    p.add_argument("--title")
    p.add_argument("--cwd", help="working directory on the chosen host (default: its workspace root)")
    p.add_argument("--include-hub", action="store_true", help="allow the hub itself as a target")
    p.set_defaults(func=cmd_dispatch)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        inv = load(args.inventory)
        return args.func(inv, args)
    except (InventoryError, FleetError) as exc:
        print(f"paseo-fleet: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
