"""Server-side manager client. Its bearer credential never reaches panel JavaScript."""
from __future__ import annotations
import json
from pathlib import Path
import re
import stat
from urllib.parse import urlsplit
import aiohttp


class NativeError(Exception):
    pass


def read_connection(path: Path) -> dict:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_size > 4096:
        raise NativeError("The private connection file must be a small regular file with mode 0600")
    value = json.loads(path.read_text())
    if set(value) != {"url", "token"}:
        raise NativeError("Invalid native-app connection file")
    url = urlsplit(value["url"])
    if url.scheme != "http" or url.hostname != "127.0.0.1" or url.username or url.password or url.path not in {"", "/"} or url.query or url.fragment:
        raise NativeError("The native-app manager must be on IPv4 loopback")
    if not url.port or not 1024 <= url.port <= 65535:
        raise NativeError("Invalid native-app manager port")
    if not isinstance(value["token"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{48,128}", value["token"]):
        raise NativeError("Invalid native-app manager credential")
    return {"url": value["url"].rstrip("/"), "token": value["token"]}


class Client:
    def __init__(self, connection: dict):
        self.url = connection["url"]
        self.token = connection["token"]
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=12),
                                             cookie_jar=aiohttp.DummyCookieJar())

    async def close(self):
        await self.session.close()

    async def request(self, method: str, path: str, body: dict | None = None) -> dict:
        if method not in {"GET", "POST"} or not re.fullmatch(r"/v1/[a-zA-Z0-9_/-]+", path):
            raise NativeError("Invalid manager request")
        try:
            async with self.session.request(method, self.url + path, json=body,
                      headers={"Authorization": "Bearer " + self.token}, allow_redirects=False) as response:
                raw = await response.content.read(2 * 1024 * 1024 + 1)
                if len(raw) > 2 * 1024 * 1024:
                    raise NativeError("Manager response exceeded its limit")
                result = json.loads(raw)
                if not isinstance(result, dict):
                    raise NativeError("Unexpected manager response")
                if response.status != 200:
                    raise NativeError(result.get("error", "Manager request failed"))
                return result
        except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
            raise NativeError("Cannot reach the native-app manager") from exc
