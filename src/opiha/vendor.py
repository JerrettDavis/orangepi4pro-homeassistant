from __future__ import annotations
import io
import json
from pathlib import Path
import shutil
import tempfile
import urllib.request
import zipfile
from .common import ApplianceError, REPO, atomic_json, read_json, safe_relative, sha256


def _seed_archive(config: Path, name: str, archive: Path, lock: Path) -> bool:
    target = config / "custom_components" / name
    if target.exists() or not archive.exists():
        return False
    if target.is_symlink() or target.parent.is_symlink():
        raise ApplianceError(f"Refusing symlinked {name} destination")
    metadata = read_json(lock)
    if sha256(archive) != metadata["sha256"]:
        raise ApplianceError(f"Vendored {name} checksum mismatch")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{name}-", dir=target.parent) as tmp:
        stage = Path(tmp) / name
        stage.mkdir()
        total = 0
        with zipfile.ZipFile(archive) as z:
            seen = set()
            for info in z.infolist():
                if info.is_dir():
                    continue
                p = safe_relative(info.filename)
                if p.as_posix() in seen or (info.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ApplianceError(f"Invalid {name} zip member")
                seen.add(p.as_posix())
                total += info.file_size
                if total > 150 * 1024 * 1024 or len(seen) > 10000:
                    raise ApplianceError(f"{name} zip exceeds size limits")
                dest = stage.joinpath(*p.parts)
                dest.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as source, dest.open("xb") as output:
                    shutil.copyfileobj(source, output)
        if not (stage / "manifest.json").is_file():
            raise ApplianceError(f"Expected {name} archive with manifest.json at the root")
        if name == "auth_oidc":
            manifest = read_json(stage / "manifest.json")
            if manifest.get("domain") != name or manifest.get("version") != metadata.get("version"):
                raise ApplianceError("OIDC archive manifest does not match its lock")
        stage.rename(target)
    return True


def seed_hacs(config: Path) -> bool:
    return _seed_archive(config, "hacs", REPO / "vendor/hacs.zip", REPO / "vendor/hacs.lock.json")


def seed_oidc(config: Path) -> bool:
    archive = REPO / "vendor/auth-oidc.zip"
    if not archive.is_file():
        raise ApplianceError("Vendored OIDC archive is missing")
    return _seed_archive(config, "auth_oidc", archive, REPO / "vendor/auth-oidc.lock.json")


def fetch_hacs(version: str) -> dict:
    import re
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ApplianceError("Pass an explicit HACS release version")
    url = f"https://api.github.com/repos/hacs/integration/releases/tags/{version}"
    req = urllib.request.Request(url, headers={"User-Agent": "opiha-image-builder"})
    with urllib.request.urlopen(req, timeout=30) as response:
        release = json.load(response)
    asset = next((a for a in release["assets"] if a["name"] == "hacs.zip"), None)
    if not asset:
        raise ApplianceError("Release has no hacs.zip asset")
    download = asset["browser_download_url"]
    if not download.startswith("https://github.com/hacs/integration/releases/download/"):
        raise ApplianceError("Unexpected HACS asset URL")
    destination = REPO / "vendor/hacs.zip"
    if destination.exists():
        raise ApplianceError("Remove the previous public vendor artifact before updating")
    req = urllib.request.Request(download, headers={"User-Agent": "opiha-image-builder"})
    with urllib.request.urlopen(req, timeout=60) as response, destination.open("xb") as output:
        count = 0
        while chunk := response.read(1024 * 1024):
            count += len(chunk)
            if count > 75 * 1024 * 1024:
                destination.unlink(missing_ok=True)
                raise ApplianceError("HACS asset is unexpectedly large")
            output.write(chunk)
    digest = sha256(destination)
    published = asset.get("digest")
    if published and published != "sha256:" + digest:
        destination.unlink()
        raise ApplianceError("GitHub asset digest mismatch")
    result = {"version": version, "sha256": digest, "url": download,
              "publisher_digest_verified": bool(published),
              "note": "Public software only. GitHub device authorization and household state are never bundled here."}
    atomic_json(REPO / "vendor/hacs.lock.json", result, 0o644)
    return result
