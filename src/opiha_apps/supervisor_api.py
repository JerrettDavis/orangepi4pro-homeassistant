"""A small, honest subset of the Supervisor's API for add-ons (`http://supervisor/...`).

This is not the Supervisor. It answers what add-ons commonly ask (their own info and options, host and
core info, the MQTT/MySQL service registry, the Home Assistant REST proxy) and says so plainly for
everything else. Unimplemented paths are recorded so missing coverage is visible, never faked.

Authentication is the per-add-on SUPERVISOR_TOKEN written to the add-on's private.env. The listener is bound
only to the add-on bridge address and refuses peers outside the add-on subnet.
"""
from __future__ import annotations
import hmac
import ipaddress
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from . import addon_runtime, addons, catalog, supervisor_ws
from .common import AppError, atomic, read_json, write_json

SUBNET = ipaddress.ip_network("172.30.32.0/23")
MAX_BODY = 1024 * 1024
PROXY_LIMIT = 16 * 1024 * 1024
SERVICES = {"mqtt", "mysql"}
# The host's reverse proxy owns port 80 on every address, so the shim listens on its own port and the
# kernel redirects the Supervisor-style `http://supervisor/` (172.30.32.2:80) from the add-on bridge to it.
SHIM_PORT = 8180
REDIRECT_RULE = ["-i", "opihaadd0", "-d", addon_runtime.SUPERVISOR_IP, "-p", "tcp", "--dport", "80",
                 "-j", "REDIRECT", "--to-ports", str(SHIM_PORT)]
# Add-ons with host networking reach the same address from the host itself, which is locally generated traffic.
# (REDIRECT would aim at 127.0.0.1 for locally generated packets; the shim listens on the bridge address.)
OUTPUT_RULE = ["-d", addon_runtime.SUPERVISOR_IP, "-p", "tcp", "--dport", "80",
               "-j", "DNAT", "--to-destination", f"{addon_runtime.SUPERVISOR_IP}:{SHIM_PORT}"]
RULES = (("PREROUTING", REDIRECT_RULE), ("OUTPUT", OUTPUT_RULE))


def ensure_redirect(run=None) -> bool:
    """Idempotently install the nat redirect; returns True when the rule is present afterwards."""
    run = run or (lambda argv: subprocess.run(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20, check=False).returncode)
    tool = next((t for t in ("/usr/sbin/iptables", "/sbin/iptables", "/usr/bin/iptables") if Path(t).exists()), None)
    tool = tool or "/usr/sbin/iptables"
    try:
        for chain, rule in RULES:
            if run([tool, "-w", "-t", "nat", "-C", chain, *rule]) != 0 and run([tool, "-w", "-t", "nat", "-I", chain, *rule]) != 0:
                return False
        return True
    except (OSError, subprocess.SubprocessError):
        return False


class Shim:
    def __init__(self, manager):
        self.m = manager
        self.lock = threading.Lock()
        self.unimplemented: dict[str, int] = {}

    # --- identity -------------------------------------------------------------------

    def slug_for_token(self, token: str) -> str | None:
        if not token or not re.fullmatch(r"[0-9a-f]{64}", token):
            return None
        found = None
        for p in (self.m.root / "apps").glob("*/private.env"):
            path = p.parent / "addon.json"
            if not path.is_file():
                continue  # reviewed apps have no add-on token
            known = self._token_of(p)
            if known and hmac.compare_digest(known, token):
                found = p.parent.name
        if found and not catalog.is_addon(found):
            # Installed by another process (CLI, repair) since this one started: learn it from disk.
            try:
                catalog.register(found, addon_runtime.load_addon(self.m.root / "apps" / found / "addon.json"))
            except AppError:
                return None
        return found

    @staticmethod
    def _token_of(path: Path) -> str | None:
        match = re.search(r"(?m)^SUPERVISOR_TOKEN=([0-9a-f]{64})$", path.read_text())
        return match[1] if match else None

    # --- helpers --------------------------------------------------------------------

    def appliance(self) -> dict:
        try:
            return read_json(Path(self.m.config["appliance_config"]))
        except AppError:
            return {}

    def record_unimplemented(self, method: str, path: str):
        key = method + " " + re.sub(r"[0-9a-f]{16,}", "<id>", path)[:120]
        with self.lock:
            if key not in self.unimplemented and len(self.unimplemented) >= 200:
                return
            self.unimplemented[key] = self.unimplemented.get(key, 0) + 1
            snapshot = dict(self.unimplemented)
        try:
            write_json(self.m.root / "shim-unimplemented.json", snapshot)
        except (AppError, OSError):
            pass

    @staticmethod
    def ok(data=None):
        return 200, {"result": "ok", "data": {} if data is None else data}

    @staticmethod
    def error(status: int, message: str):
        return status, {"result": "error", "message": message}

    def info_for(self, slug: str) -> dict:
        app = catalog.entry(slug)
        m, record = app["manifest"], self.m.record(slug)
        row = self.m.engine.owned(slug)
        networks = (row or {}).get("NetworkSettings", {}).get("Networks", {}) or {}
        address = (networks.get(addon_runtime.NETWORK) or {}).get("IPAddress")
        opts = record["options"] if record else app and addon_runtime.defaults(app)
        if "host_network" in opts["grants"]:
            address = addon_runtime.SUPERVISOR_IP  # as the Supervisor reports the network gateway for host-networked add-ons
        entry = m["ingress_entry"] if isinstance(m["ingress_entry"], str) else ""
        port = opts["port"] if app["dynamic_ingress"] else app["container_port"]
        return {
            "name": m["name"], "slug": addon_runtime.supervisor_slug(app), "hostname": app["hostname"],
            "description": m["description"], "version": m["version"], "version_latest": m["version"],
            "update_available": False, "state": "started" if row and row.get("State", {}).get("Running") else "stopped",
            "boot": "auto" if opts["autostart"] else "manual", "build": app["build"], "arch": ["aarch64"],
            "options": opts["config"], "schema": m["schema"] or None, "protected": True, "rating": 5,
            "host_network": "host_network" in opts["grants"], "privileged": m["privileged"],
            "devices": opts["devices"], "ingress": app["ingress"], "ingress_port": port if app["ingress"] else None,
            "ingress_entry": "/" + entry.strip("/") if entry else "/", "ingress_url": catalog.PREFIX + slug + "/" + entry.strip("/"),
            "ip_address": address, "network": {k: v for k, v in opts["host_ports"].items()},
            "homeassistant_api": m["homeassistant_api"], "hassio_api": m["hassio_api"], "hassio_role": m["hassio_role"],
            "auth_api": False, "audio": "audio" in opts["grants"], "video": False, "gpio": False, "usb": False, "uart": False,
            "services_role": m["services"], "auto_update": False, "repository": app["repo"], "url": m["url"],
            "slug_local": slug,
        }

    # --- routing --------------------------------------------------------------------

    def handle(self, method: str, path: str, token: str, body: bytes = b"", content_type: str = "") -> tuple[int, object, str]:
        """Returns (status, payload, kind) where kind is 'json' (envelope) or 'raw' (bytes with content_type)."""
        slug = self.slug_for_token(token)
        if not slug:
            return (*self.error(401, "Unauthorized"), "json")
        raw_path = path
        path = "/" + path.split("?", 1)[0].strip("/")
        app = catalog.entry(slug)
        m = app["manifest"]
        try:
            if path.startswith(("/core/api", "/homeassistant/api")):
                if not m["homeassistant_api"]:
                    return (*self.error(403, "This add-on has not declared homeassistant_api"), "json")
                return self.proxy_core(method, raw_path, body, content_type)
            if path in {"/core/websocket", "/homeassistant/websocket"}:
                return (*self.error(426, "Open this endpoint with a WebSocket upgrade"), "json")
            payload = self.route(method, path, slug, app, body)
            return (*payload, "json")
        except AppError as exc:
            return (*self.error(400, str(exc)), "json")

    def route(self, method: str, path: str, slug: str, app: dict, body: bytes):
        m = app["manifest"]
        if re.fullmatch(r"/addons/(self|" + re.escape(addon_runtime.supervisor_slug(app)) + r")/info", path) and method == "GET":
            return self.ok(self.info_for(slug))
        if re.fullmatch(r"/addons/self/options/config", path) and method == "GET":
            return self.ok(self.m.record(slug)["options"]["config"])
        if path == "/addons/self/options" and method == "POST":
            return self.set_options(slug, app, body)
        if path == "/addons/self/options/validate" and method == "POST":
            try:
                value = json.loads(body or b"{}")
                addons.validate_options(m["schema"], value.get("options") if isinstance(value, dict) and "options" in value else value)
                return self.ok({"valid": True, "message": ""})
            except (AppError, ValueError) as exc:
                return self.ok({"valid": False, "message": str(exc)})
        if path == "/addons/self/stats" and method == "GET":
            return self.stats(slug)
        if path == "/supervisor/ping" and method == "GET":
            return self.ok()
        if path == "/info" and method == "GET":
            return self.ok(self.system_info())
        if path in {"/core/info", "/homeassistant/info"} and method == "GET":
            a = self.appliance()
            return self.ok({"version": a.get("ha_version"), "version_latest": a.get("ha_version"), "update_available": False,
                            "machine": "orangepi4pro", "ip_address": addon_runtime.SUPERVISOR_IP, "arch": "aarch64",
                            "port": 8123, "ssl": False, "watchdog": True, "boot": True, "image": a.get("images", {}).get("homeassistant")})
        if path == "/host/info" and method == "GET":
            return self.ok({"hostname": socket.gethostname(), "operating_system": "Orange Pi Linux", "chassis": "embedded",
                            "features": [], "kernel": "", "deployment": "production", "disk_total": None, "disk_free": None})
        if path == "/supervisor/info" and method == "GET":
            return self.ok({"version": "orangepi-shim", "channel": "stable", "arch": "aarch64", "supported": True,
                            "healthy": True, "timezone": "UTC", "logging": "info", "ip_address": addon_runtime.SUPERVISOR_IP,
                            "addons": [], "addons_repositories": []})
        if path == "/network/info" and method == "GET":
            return self.ok({"interfaces": host_interfaces(), "host_internet": True, "supervisor_internet": True})
        if (m_ := re.fullmatch(r"/network/interface/([A-Za-z0-9_.:-]{1,15})/info", path)) and method == "GET":
            found = next((i for i in host_interfaces() if i["interface"] == m_[1]), None)
            return self.ok(found) if found else self.error(404, "Unknown network interface")
        if m_ := re.fullmatch(r"/services/(mqtt|mysql)", path):
            return self.service(method, m_[1], slug, app, body)
        if path == "/discovery" and method == "POST":
            return self.discovery(slug, app, body)
        if path == "/discovery" or path.startswith("/discovery/"):
            return self.ok({"discovery": []}) if method == "GET" else self.ok()
        self.record_unimplemented(method, path)
        return self.error(404, "Not implemented by the Orange Pi Supervisor shim")

    # --- handlers -------------------------------------------------------------------

    def system_info(self) -> dict:
        a = self.appliance()
        return {"supervisor": "orangepi-shim", "homeassistant": a.get("ha_version"), "hassos": None,
                "docker": None, "hostname": socket.gethostname(), "operating_system": "Orange Pi Linux",
                "machine": "orangepi4pro", "arch": "aarch64", "channel": "stable", "supported": True,
                "supervisor_api": "shim", "state": "running", "features": [], "timezone": "UTC"}

    def set_options(self, slug: str, app: dict, body: bytes):
        try:
            doc = json.loads(body or b"{}")
        except ValueError as exc:
            raise AppError("Request body is not valid JSON") from exc
        if not isinstance(doc, dict) or "options" not in doc:
            raise AppError("Send {\"options\": {...}}")
        record = self.m.record(slug)
        opts = {**record["options"], "config": doc["options"]}
        opts = catalog.options(slug, opts)
        with self.m.guard:
            if self.m.active:
                raise AppError("A lifecycle job is running; try again shortly")
            addon_runtime.write_options(self.m, slug, opts)
            write_json(self.m.app_dir(slug) / "record.json", {**record, "options": opts})
        return self.ok()

    def stats(self, slug: str):
        row = self.m.engine.owned(slug)
        if not row or not row.get("State", {}).get("Running"):
            return self.error(400, "The add-on is not running")
        rows = self.m.engine.stats([row["Id"]])
        return self.ok(rows[0] if rows else {})

    def service(self, method: str, name: str, slug: str, app: dict, body: bytes):
        wanted = {s.split(":")[0]: (s.split(":") + ["want"])[1] for s in app["manifest"]["services"]}
        role = wanted.get(name)
        path = self.m.root / "services" / (name + ".json")
        if method == "GET":
            if role not in {"want", "need"} and role != "provide":
                return self.error(403, "This add-on has not declared the " + name + " service")
            if not path.is_file():
                return self.error(400, "No " + name + " service is registered")
            data = read_json(path)
            return self.ok({k: v for k, v in data.items() if k != "provider"})
        if role != "provide":
            return self.error(403, "Only an add-on that declares " + name + ":provide can publish it")
        if method == "POST":
            try:
                doc = json.loads(body or b"{}")
            except ValueError as exc:
                raise AppError("Request body is not valid JSON") from exc
            if not isinstance(doc, dict) or len(doc) > 16 or not all(isinstance(k, str) and isinstance(v, (str, int, bool)) for k, v in doc.items()):
                raise AppError("Service data must be a flat object")
            (self.m.root / "services").mkdir(mode=0o700, exist_ok=True)
            write_json(path, {**doc, "provider": slug})
            return self.ok()
        if method == "DELETE":
            if path.is_file() and read_json(path).get("provider") == slug:
                path.unlink()
            return self.ok()
        return self.error(405, "Unsupported method")

    def ha_access(self) -> tuple[str, str] | None:
        token_file = self.m.root / "ha-token"
        if not token_file.is_file():
            return None
        return self.appliance().get("ha_url", "http://127.0.0.1:8123").rstrip("/"), token_file.read_text().strip()

    def discovery(self, slug: str, app: dict, body: bytes):
        """Supervisor discovery needs HA's hassio integration; MQTT is instead registered through the config-flow API."""
        try:
            doc = json.loads(body or b"{}")
        except ValueError as exc:
            raise AppError("Request body is not valid JSON") from exc
        service, config = doc.get("service"), doc.get("config")
        if not isinstance(doc, dict) or service not in app["manifest"]["discovery"] or not isinstance(config, dict):
            return self.error(403, "This add-on has not declared that discovery service")
        if service not in {"mqtt", "wyoming", *supervisor_ws.URL_SERVICES}:
            self.record_unimplemented("POST", "/discovery:" + str(service))
            return self.error(501, "Only MQTT, Wyoming, Z-Wave JS, Matter and OpenThread discovery are implemented; add the " + str(service) + " integration in Home Assistant by hand")
        access = self.ha_access()
        if access is None:
            return self.error(503, "No Home Assistant access token is configured (Add-ons tab), so the service cannot be registered automatically")
        if service in {"wyoming", *supervisor_ws.URL_SERVICES}:
            # Home Assistant runs on the host network, so it reaches the add-on's own address on the add-on bridge.
            row = self.m.engine.owned(slug)
            networks = (row or {}).get("NetworkSettings", {}).get("Networks", {}) or {}
            address = (networks.get(addon_runtime.NETWORK) or {}).get("IPAddress")
            if not address or not row.get("State", {}).get("Running"):
                return self.error(400, "The add-on has no address on the add-on network")
            # Wyoming add-ons announce `uri: tcp://<their hostname>:<port>`; only the port is used (the host is this add-on).
            match = re.fullmatch(r"tcp://[A-Za-z0-9.-]{1,100}:(\d{1,5})", str(config.get("uri", "")))
            port = int(match[1]) if match else config.get("port")
            if service == "wyoming":
                outcome = supervisor_ws.discover_wyoming(access[0], access[1], address, port)
            else:
                outcome = supervisor_ws.discover_url_service(access[0], access[1], service, address, config.get("port"))
            return self.ok({"uuid": slug, "outcome": outcome})
        port = config.get("port", 1883)
        host_port = self.m.record(slug)["options"]["host_ports"].get(f"{port}/tcp")
        if type(port) is not int or host_port is None:
            return self.error(400, "The add-on's broker port is not published to the host")
        outcome = supervisor_ws.discover_mqtt(access[0], access[1], "127.0.0.1", host_port,
                                              config.get("username"), config.get("password"), config.get("protocol"))
        return self.ok({"uuid": slug, "outcome": outcome})

    def websocket(self, sock) -> None:
        access = self.ha_access()
        if access is None:
            supervisor_ws.send_json(sock, {"type": "auth_invalid", "message": "No Home Assistant access token is configured"}, False)
            supervisor_ws.close_politely(sock, 1008)
            return
        def valid(token: str) -> bool:
            slug = self.slug_for_token(token)
            return bool(slug and catalog.entry(slug)["manifest"]["homeassistant_api"])
        supervisor_ws.relay(sock, access[1], access[0], valid)

    def proxy_core(self, method: str, path: str, body: bytes, content_type: str):
        token_file = self.m.root / "ha-token"
        if not token_file.is_file():
            return (*self.error(503, "No Home Assistant access token is configured for add-ons (see docs/native-apps/ADDONS.md)"), "json")
        token = token_file.read_text().strip()
        base = self.appliance().get("ha_url", "http://127.0.0.1:8123").rstrip("/")
        tail = re.sub(r"^/(core|homeassistant)/api", "", "/" + path.lstrip("/")) or "/"
        if method not in {"GET", "POST", "PUT", "DELETE", "PATCH"} or ".." in tail or "\r" in tail or "\n" in tail or " " in tail:
            return (*self.error(400, "Unsupported request"), "json")
        request = urllib.request.Request(base + "/api" + tail, data=body or None, method=method,
                                         headers={"Authorization": "Bearer " + token, "Content-Type": content_type or "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                data = response.read(PROXY_LIMIT + 1)
                if len(data) > PROXY_LIMIT:
                    return (*self.error(502, "Home Assistant response is too large"), "json")
                return response.status, data, response.headers.get("Content-Type", "application/json")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read(PROXY_LIMIT), exc.headers.get("Content-Type", "application/json")
        except (urllib.error.URLError, OSError):
            return (*self.error(502, "Home Assistant is not reachable"), "json")


def _ip_json(args: list[str], run=None):
    run = run or (lambda argv: subprocess.run(argv, capture_output=True, text=True, timeout=10, check=False).stdout)
    tool = next((t for t in ("/usr/sbin/ip", "/sbin/ip", "/usr/bin/ip", "/bin/ip") if Path(t).exists()), "/usr/sbin/ip")
    try:
        value = json.loads(run([tool, "-j", *args]) or "[]")
    except (OSError, ValueError, subprocess.SubprocessError):
        return []
    return value if isinstance(value, list) else []


def host_interfaces(run=None) -> list[dict]:
    """The host's real network interfaces in the Supervisor's `network/info` shape (Samba and others bind to these)."""
    routes = _ip_json(["-4", "route", "show", "default"], run)
    primary = routes[0].get("dev") if routes else None
    gateway = routes[0].get("gateway") if routes else None
    result = []
    for link in _ip_json(["-4", "addr", "show"], run):
        name = link.get("ifname", "")
        if not name or name == "lo" or name.startswith(("docker", "br-", "veth", "opihaadd", "virbr")):
            continue
        addresses = [f"{a['local']}/{a['prefixlen']}" for a in link.get("addr_info", []) if a.get("family") == "inet" and "local" in a]
        if not addresses:
            continue
        kind = "wireless" if name.startswith(("wl", "wlan")) else "ethernet"
        result.append({"interface": name, "type": kind, "enabled": True, "connected": True, "primary": name == primary,
                       "ipv4": {"method": "auto", "address": addresses, "gateway": gateway if name == primary else None,
                                "nameservers": [], "ready": True},
                       "ipv6": {"method": "disabled", "address": [], "gateway": None, "nameservers": [], "ready": False},
                       "mac": link.get("address"), "vlan": None, "wifi": None})
    return result


def peer_allowed(address: str) -> bool:
    """Add-on bridge clients, plus this host itself: add-ons with host networking arrive from the Pi's own address.
    Binding succeeds only for addresses that belong to this machine, so a remote host cannot pass as local."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    if ip in SUBNET or ip.is_loopback:
        return True
    try:
        with socket.socket(socket.AF_INET6 if ip.version == 6 else socket.AF_INET) as probe:
            probe.bind((address, 0))
        return True
    except OSError:
        return False


def make_server(shim: Shim, host: str = addon_runtime.SUPERVISOR_IP, port: int = SHIM_PORT, *, allow_any_peer: bool = False):
    class Handler(BaseHTTPRequestHandler):
        server_version = "OPIHA-Supervisor-Shim/1"

        def setup(self):
            super().setup()
            self.connection.settimeout(35)

        def log_message(self, *_):
            return

        def token(self) -> str:
            header = self.headers.get("Authorization", "")
            if header.startswith("Bearer "):
                return header[7:].strip()
            return (self.headers.get("X-Supervisor-Token") or self.headers.get("X-Hassio-Key") or "").strip()

        def upgrade(self):
            key = self.headers.get("Sec-WebSocket-Key", "")
            if not re.fullmatch(r"[A-Za-z0-9+/]{22}==", key):
                self.send_error(400)
                return
            self.connection.sendall(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                                     f"Sec-WebSocket-Accept: {supervisor_ws.accept_key(key)}\r\n\r\n").encode())
            self.connection.settimeout(None)
            shim.websocket(self.connection)
            self.close_connection = True

        def serve(self):
            try:
                if not allow_any_peer and not peer_allowed(self.client_address[0]):
                    self.send_error(403)
                    return
                if (self.headers.get("Upgrade", "").lower() == "websocket"
                        and self.path.split("?")[0].rstrip("/") in {"/core/websocket", "/homeassistant/websocket"}):
                    return self.upgrade()
                length = int(self.headers.get("Content-Length", "0") or 0)
                if length < 0 or length > MAX_BODY or self.headers.get("Transfer-Encoding"):
                    self.send_error(413)
                    return
                body = self.rfile.read(length) if length else b""
                status, payload, kind = shim.handle(self.command, self.path, self.token(), body, self.headers.get("Content-Type", ""))
                if kind == "json":
                    data, ctype = json.dumps(payload).encode(), "application/json"
                else:
                    data, ctype = payload, kind
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError, socket.timeout, ValueError):
                return
            except Exception:
                try:
                    self.send_error(500)
                except OSError:
                    pass
            self.close_connection = True

        do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = serve

    class Server(ThreadingHTTPServer):
        daemon_threads = True
        request_queue_size = 32

    return Server((host, port), Handler)


def listener_alive(host: str, port: int) -> bool:
    """True when something accepts connections at host:port (a socket bound to a removed address does not)."""
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


def run_forever(shim: Shim, stop: threading.Event, host: str = addon_runtime.SUPERVISOR_IP, port: int = SHIM_PORT):
    """Serve once the add-on bridge address exists; retry while Docker has not created it yet, and keep the
    redirect in place (it is re-checked because a firewall reload can drop it)."""
    server = None
    state = shim.m.shim_state
    while not stop.is_set():
        error = None
        if server is None:
            try:
                server = make_server(shim, host, port)
                threading.Thread(target=server.serve_forever, daemon=True).start()
            except OSError as exc:
                server, error = None, f"cannot listen on {host}:{port} ({exc.strerror or exc}); the add-on network is created by the first add-on install"
        if server is not None and not listener_alive(host, server.server_address[1]):
            # The add-on network was removed or recreated underneath the socket (or another process took the
            # address): drop the dead listener and bind again on the next pass.
            server.shutdown()
            server.server_close()
            server = None
            stop.wait(1)
            continue
        redirect = ensure_redirect() if server is not None else False
        if server is not None and not redirect:
            error = "could not install the supervisor:80 redirect (iptables); add-ons will not reach the API"
        changed = (state.get("listening"), state.get("redirect"), state.get("error")) != (server is not None, redirect, error)
        state.update(listening=server is not None, redirect=redirect, error=error)
        if changed and error:
            print("opiha-apps: supervisor shim: " + error, file=sys.stderr, flush=True)
        stop.wait(30 if server is not None else 10)
    if server is not None:
        server.shutdown()
        server.server_close()
