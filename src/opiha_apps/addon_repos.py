"""Add-on repositories: shallow git clones of repositories the administrator chose.

Cloning is the only network operation here. It is https-only, without submodules or
credential prompts, bounded in time and size, and writes into a private directory that
nothing executes from. Repository content is untrusted data until an install is approved.
"""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
from urllib.parse import urlparse
from . import addons
from .common import AppError, checked_path, read_json, stamp, write_json

# Offered in the panel, never cloned until the administrator asks.
SUGGESTED = [
    {"url": "https://github.com/home-assistant/addons", "name": "Official add-ons", "official": True},
    {"url": "https://github.com/hassio-addons/repository", "name": "Community Hass.io Add-ons", "official": False},
    {"url": "https://github.com/esphome/home-assistant-addon", "name": "ESPHome add-ons", "official": False},
    {"url": "https://github.com/zigbee2mqtt/hassio-zigbee2mqtt", "name": "Zigbee2MQTT", "official": False},
]
MAX_REPO_BYTES = 300 * 1024 * 1024
MAX_ADDONS = 400


def normalise_url(url: str) -> str:
    if not isinstance(url, str) or len(url) > 200 or any(c in url for c in " \t\r\n\x00'\"\\"):
        raise AppError("Repository URL is not acceptable")
    p = urlparse(url)
    if p.scheme != "https" or not p.hostname or p.username or p.password or p.query or p.fragment or p.port not in (None, 443):
        raise AppError("Only plain https:// repository URLs are accepted")
    if not re.fullmatch(r"[a-z0-9.-]+", p.hostname) or p.hostname in {"localhost"} or re.fullmatch(r"[\d.]+", p.hostname):
        raise AppError("Repository host must be a public DNS name")
    path = p.path.rstrip("/").removesuffix(".git")
    if not re.fullmatch(r"/[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+){1,3}", path) or ".." in path:
        raise AppError("Repository path must look like /owner/name")
    return f"https://{p.hostname}{path}"


def repo_id(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:8]


def _git(argv: list[str], cwd: Path | None, timeout: int) -> tuple[int, str]:
    env = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "HOME": "/var/lib/orangepi-apps", "LC_ALL": "C.UTF-8",
           "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"}
    try:
        p = subprocess.run(["/usr/bin/git", "-c", "protocol.allow=never", "-c", "protocol.https.allow=always",
                            "-c", "core.hooksPath=/dev/null", "-c", "submodule.recurse=false", *argv],
                           cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, check=False)
        return p.returncode, p.stdout[-4000:].decode("utf-8", errors="replace")
    except FileNotFoundError as exc:
        raise AppError("git is not installed at /usr/bin/git") from exc
    except subprocess.TimeoutExpired as exc:
        raise AppError("Repository download timed out") from exc


def _tree_size(path: Path) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            try:
                total += os.lstat(os.path.join(root, name)).st_size
            except OSError:
                pass
    return total


class Repositories:
    def __init__(self, root: Path, *, git=None):
        self.root = checked_path(root / "repos")
        self.root.mkdir(mode=0o700, exist_ok=True)
        self.git = git or _git

    def _dir(self, rid: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{8}", rid):
            raise AppError("Unknown repository")
        return checked_path(self.root / rid)

    def list(self) -> list[dict]:
        rows = []
        for d in sorted(self.root.iterdir()) if self.root.exists() else []:
            meta = d / "meta.json"
            if d.is_dir() and meta.is_file():
                rows.append(read_json(meta))
        return rows

    def add(self, url: str) -> dict:
        url = normalise_url(url)
        rid = repo_id(url)
        final = self._dir(rid)
        if final.exists():
            raise AppError("This repository is already added")
        work = checked_path(self.root / (".new-" + rid + "-" + stamp()))
        try:
            work.mkdir(mode=0o700)
            code, _ = self.git(["clone", "--depth", "1", "--no-tags", "--single-branch", "--no-recurse-submodules", url, str(work / "src")], None, 300)
            if code:
                raise AppError("Could not download the repository; check the URL and network")
            if _tree_size(work) > MAX_REPO_BYTES:
                raise AppError("Repository is larger than the 300 MiB limit")
            src = work / "src"
            if (src / "repo.yaml").is_file():
                info = addons.read_document(src / "repo.yaml")
            elif (src / "repository.yaml").is_file():
                info = addons.read_document(src / "repository.yaml")
            else:
                info = {}
            if not self._scan(src):
                raise AppError("No Home Assistant add-ons were found in this repository")
            name = info.get("name") if isinstance(info.get("name"), str) else url.rsplit("/", 1)[-1]
            meta = {"id": rid, "url": url, "name": name[:100], "maintainer": str(info.get("maintainer", ""))[:100],
                    "added": stamp()}
            write_json(work / "meta.json", meta)
            os.replace(work, final)
            return meta
        finally:
            if work.exists():
                shutil.rmtree(work, ignore_errors=True)

    def refresh(self, rid: str) -> dict:
        d = self._dir(rid)
        if not (d / "meta.json").is_file():
            raise AppError("Unknown repository")
        code, _ = self.git(["fetch", "--depth", "1", "--no-tags", "origin"], d / "src", 300)
        if code:
            raise AppError("Could not refresh the repository")
        code, _ = self.git(["reset", "--hard", "FETCH_HEAD"], d / "src", 120)
        if code:
            raise AppError("Could not apply the refreshed repository")
        return read_json(d / "meta.json")

    def remove(self, rid: str) -> None:
        d = self._dir(rid)
        if not (d / "meta.json").is_file():
            raise AppError("Unknown repository")
        shutil.rmtree(d)

    def _scan(self, src: Path) -> list[Path]:
        found = []
        for child in sorted(src.iterdir()):
            if child.name.startswith(".") or child.is_symlink() or not child.is_dir():
                continue
            if addons.find_manifest(child):
                found.append(child)
            if len(found) > MAX_ADDONS:
                raise AppError("Repository contains too many add-ons")
        return found

    def addons(self, rid: str) -> list[dict]:
        """Every add-on found, judged but not installed. A bad manifest is listed with its error."""
        d = self._dir(rid)
        meta = read_json(d / "meta.json")
        rows = []
        for folder in self._scan(d / "src"):
            try:
                manifest = addons.parse(addons.read_document(addons.find_manifest(folder)), repository=rid)
                rows.append({"repository": rid, "folder": folder.name, "manifest": manifest,
                             "report": addons.report(manifest), "has_dockerfile": (folder / "Dockerfile").is_file()})
            except AppError as exc:
                rows.append({"repository": rid, "folder": folder.name, "error": str(exc)})
        return rows

    def addon_dir(self, rid: str, folder: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", folder) or folder.startswith("."):
            raise AppError("Unknown add-on folder")
        path = checked_path(self._dir(rid) / "src" / folder)
        if not path.is_dir() or not addons.find_manifest(path):
            raise AppError("Unknown add-on")
        return path
