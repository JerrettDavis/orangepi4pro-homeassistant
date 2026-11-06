#!/usr/bin/env python3
"""Build and deploy the household Lovelace dashboards.

  build   write homeassistant/dashboards/storage/<name>.json from the definitions
  deploy  back up the live dashboard, then save the built config over WebSocket

Environment: HOMEASSISTANT_URL (e.g. http://host:8123) and HOMEASSISTANT_TOKEN
(long-lived access token). The token is never written anywhere.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dashboard_defs import desktops, home_ops, lights, vehicles  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "homeassistant" / "dashboards" / "storage"
BACKUPS = ROOT / ".local" / "dashboard-backups"

DASHBOARDS = {
    "lights": {"module": lights, "url_path": "dashboard-lights", "title": "Lights",
               "icon": "mdi:lightbulb-group"},
    "desktops": {"module": desktops, "url_path": "dashboard-desktops", "title": "Desktops",
                 "icon": "mdi:desktop-tower-monitor"},
    "vehicles": {"module": vehicles, "url_path": "dashboard-vehicles", "title": "Vehicle leases",
                 "icon": "mdi:car-multiple"},
    "home-operations": {"module": home_ops, "url_path": "dashboard-home-operations", "title": "Home Operations",
                        "icon": "mdi:home-heart"},
}


def build_all(names: list[str] | None = None) -> dict[str, dict]:
    return {name: spec["module"].build() for name, spec in DASHBOARDS.items() if not names or name in names}


def write_built(built: dict[str, dict]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, config in built.items():
        (OUT / f"{name}.json").write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


class Session:
    def __init__(self, ws):
        self.ws = ws
        self.next_id = 0

    async def call(self, message: dict) -> dict:
        self.next_id += 1
        await self.ws.send(json.dumps({**message, "id": self.next_id}))
        while True:
            reply = json.loads(await self.ws.recv())
            if reply.get("id") == self.next_id:
                return reply


async def deploy(built: dict[str, dict]) -> None:
    import websockets

    url = os.environ["HOMEASSISTANT_URL"].rstrip("/").replace("http", "ws", 1) + "/api/websocket"
    token = os.environ["HOMEASSISTANT_TOKEN"]
    async with websockets.connect(url, max_size=64 * 1024 * 1024) as ws:
        await ws.recv()
        await ws.send(json.dumps({"type": "auth", "access_token": token}))
        if json.loads(await ws.recv())["type"] != "auth_ok":
            raise SystemExit("Home Assistant rejected the access token")
        session = Session(ws)
        existing = {d["url_path"] for d in (await session.call({"type": "lovelace/dashboards/list"}))["result"]}
        stamp = time.strftime("%Y%m%d-%H%M%S")
        for name, config in built.items():
            spec = DASHBOARDS[name]
            path = spec["url_path"]
            if path not in existing:
                created = await session.call({
                    "type": "lovelace/dashboards/create", "url_path": path, "title": spec["title"],
                    "icon": spec["icon"], "show_in_sidebar": True, "require_admin": False, "mode": "storage"})
                if not created.get("success"):
                    raise SystemExit(f"Cannot create {path}: {created.get('error')}")
            else:
                current = await session.call({"type": "lovelace/config", "url_path": path, "force": True})
                if current.get("success"):
                    BACKUPS.mkdir(parents=True, exist_ok=True)
                    (BACKUPS / f"{path}-{stamp}.json").write_text(json.dumps(current["result"], indent=1),
                                                                  encoding="utf-8")
            saved = await session.call({"type": "lovelace/config/save", "url_path": path, "config": config})
            if not saved.get("success"):
                raise SystemExit(f"Saving {path} failed: {saved.get('error')}")
            print(f"deployed {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("build", "deploy"))
    parser.add_argument("names", nargs="*", help=f"dashboards ({', '.join(DASHBOARDS)}); default all")
    args = parser.parse_args()
    unknown = [n for n in args.names if n not in DASHBOARDS]
    if unknown:
        parser.error(f"unknown dashboard(s): {', '.join(unknown)}")
    built = build_all(args.names)
    write_built(built)
    if args.command == "deploy":
        asyncio.run(deploy(built))
    print(f"{args.command}: {', '.join(built)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
