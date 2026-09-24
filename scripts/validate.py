#!/usr/bin/env python3
"""Run the source validation matrix without changing host configuration."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def manifest_platforms(raw: str) -> set[str]:
    platforms = set(re.findall(r"^\s*Platform:\s*([^\s]+)\s*$", raw, re.MULTILINE))
    return {platform for platform in platforms if platform != "unknown/unknown"}


def registry_index_platforms(document: dict) -> set[str]:
    platforms = set()
    for manifest in document.get("manifests", []):
        platform = manifest.get("platform", {})
        os_name = platform.get("os")
        architecture = platform.get("architecture")
        if not os_name or not architecture or (os_name, architecture) == ("unknown", "unknown"):
            continue
        value = f"{os_name}/{architecture}"
        if platform.get("variant"):
            value += f"/{platform['variant']}"
        platforms.add(value)
    return platforms


def _image_parts(image: str) -> tuple[str, str, str]:
    if image.startswith("ghcr.io/"):
        registry = "ghcr.io"
        remainder = image.removeprefix("ghcr.io/")
    else:
        registry = "registry-1.docker.io"
        remainder = image.removeprefix("docker.io/")
    if ":" not in remainder.rsplit("/", 1)[-1]:
        raise ValueError("Image reference must use an explicit tag")
    repository, tag = remainder.rsplit(":", 1)
    if registry == "registry-1.docker.io" and "/" not in repository:
        repository = "library/" + repository
    return registry, repository, tag


def registry_inspect(image: str) -> str:
    registry, repository, tag = _image_parts(image)
    if registry == "registry-1.docker.io":
        token_url = "https://auth.docker.io/token?" + urlencode(
            {"service": "registry.docker.io", "scope": f"repository:{repository}:pull"}
        )
    else:
        token_url = "https://ghcr.io/token?" + urlencode(
            {"service": "ghcr.io", "scope": f"repository:{repository}:pull"}
        )
    with urlopen(Request(token_url, headers={"User-Agent": "opiha-validation/1"}), timeout=30) as response:
        token_document = json.load(response)
    token = token_document.get("token") or token_document.get("access_token")
    if not token:
        raise OSError("Registry did not issue an anonymous pull token")
    manifest_url = f"https://{registry}/v2/{repository}/manifests/{tag}"
    request = Request(
        manifest_url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": ", ".join(
                (
                    "application/vnd.oci.image.index.v1+json",
                    "application/vnd.docker.distribution.manifest.list.v2+json",
                )
            ),
            "User-Agent": "opiha-validation/1",
        },
    )
    with urlopen(request, timeout=30) as response:
        document = json.load(response)
    return "".join(f"Platform: {value}\n" for value in sorted(registry_index_platforms(document)))


def inspect_image(image: str) -> str:
    try:
        completed = subprocess.run(
            ["docker", "buildx", "imagetools", "inspect", image],
            check=True,
            text=True,
            capture_output=True,
            shell=False,
        )
        return completed.stdout
    except (FileNotFoundError, subprocess.SubprocessError):
        return registry_inspect(image)


def validate_images(
    images: dict[str, str], inspector: Callable[[str], str] = inspect_image
) -> list[dict]:
    results = []
    for name, image in images.items():
        try:
            platforms = manifest_platforms(inspector(image))
            arm64 = any(platform in {"linux/arm64", "linux/arm64/v8"} for platform in platforms)
            results.append({"name": name, "image": image, "arm64": arm64})
        except (OSError, subprocess.SubprocessError):
            results.append(
                {"name": name, "image": image, "arm64": False, "error": "inspection failed"}
            )
    return results


def run_checks(commands: list[list[str]], runner=subprocess.run) -> list[dict]:
    results = []
    for argv in commands:
        name = Path(argv[-1]).name if len(argv) == 2 and argv[0] == "bash" else " ".join(argv)
        try:
            completed = runner(
                argv,
                check=False,
                text=True,
                capture_output=True,
                cwd=ROOT,
                shell=False,
            )
        except FileNotFoundError:
            results.append({"name": name, "status": "fail", "reason": f"missing executable: {argv[0]}"})
            continue
        if completed.returncode == 0:
            results.append({"name": name, "status": "pass"})
        else:
            detail = (completed.stderr or completed.stdout).strip().splitlines()
            reason = detail[-1] if detail else "no diagnostic output"
            results.append({"name": name, "status": "fail", "reason": f"exit {completed.returncode}: {reason}"})
    return results


def summarize(checks: list[dict]) -> dict:
    return {
        "passed": sum(check.get("status") == "pass" for check in checks),
        "failed": sum(check.get("status") == "fail" for check in checks),
        "skipped": sum(check.get("status") == "skip" for check in checks),
        "checks": checks,
    }


def _compile_sources() -> dict:
    try:
        count = 0
        for root_name in ("src", "scripts", "image"):
            for path in (ROOT / root_name).rglob("*.py"):
                compile(path.read_text(encoding="utf-8"), str(path), "exec")
                count += 1
        return {"name": "python-compilation", "status": "pass", "files": count}
    except (OSError, SyntaxError) as exc:
        return {"name": "python-compilation", "status": "fail", "reason": str(exc)}


def _package_check() -> dict:
    with tempfile.TemporaryDirectory(prefix="opiha-package-validation-") as tmp:
        root = Path(tmp)
        commands = [
            [sys.executable, str(ROOT / "scripts/package.py"), "--output", str(root / "one")],
            [sys.executable, str(ROOT / "scripts/package.py"), "--output", str(root / "two")],
        ]
        results = run_checks(commands)
        failure = next((item for item in results if item["status"] == "fail"), None)
        if failure:
            return {"name": "source-package", "status": "fail", "reason": failure["reason"]}
        first = next((root / "one").glob("*.zip"), None)
        second = next((root / "two").glob("*.zip"), None)
        if not first or not second:
            return {"name": "source-package", "status": "fail", "reason": "package artifact missing"}
        one = hashlib.sha256(first.read_bytes()).hexdigest()
        two = hashlib.sha256(second.read_bytes()).hexdigest()
        if one != two:
            return {"name": "source-package", "status": "fail", "reason": "packages are not deterministic"}
        return {"name": "source-package", "status": "pass", "sha256": one}


def _render_check() -> dict:
    with tempfile.TemporaryDirectory(prefix="opiha-render-validation-") as tmp:
        root = Path(tmp)
        config_path = root / "appliance.json"
        commands = [
            [sys.executable, str(ROOT / "bin/opiha"), "--config", str(config_path), "init", "--mode", "lab", "--data-dir", str(root / "state")],
            [sys.executable, str(ROOT / "bin/opiha"), "--config", str(config_path), "render"],
        ]
        results = run_checks(commands)
        failure = next((item for item in results if item["status"] == "fail"), None)
        return (
            {"name": "config-render", "status": "fail", "reason": failure["reason"]}
            if failure
            else {"name": "config-render", "status": "pass"}
        )


def _shell_files() -> list[Path]:
    files = list((ROOT / "scripts").rglob("*.sh")) + list((ROOT / "image").rglob("*.sh"))
    return sorted(files)


def validation_checks(include_images: bool, docker_smoke: bool) -> list[dict]:
    commands = [
        [sys.executable, str(ROOT / "scripts/scan-public.py")],
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q"],
    ]
    commands.extend([["bash", "-n", str(path)] for path in _shell_files()])
    checks = run_checks(commands)
    checks.append(_compile_sources())
    checks.append(_render_check())
    checks.append(_package_check())
    for executable in ("age", "age-keygen"):
        checks.append(
            {"name": executable, "status": "pass"}
            if shutil.which(executable)
            else {"name": executable, "status": "skip", "reason": f"{executable} not installed"}
        )
    try:
        import cv2  # type: ignore

        checks.append({"name": "opencv", "status": "pass", "version": cv2.__version__})
    except ImportError:
        checks.append({"name": "opencv", "status": "skip", "reason": "OpenCV not installed"})
    if include_images:
        images = json.loads((ROOT / "config/image-defaults.json").read_text())["images"]
        image_results = validate_images(images)
        checks.extend(
            {
                "name": f"image-{item['name']}",
                "status": "pass" if item["arm64"] else "fail",
                "image": item["image"],
                "arm64": item["arm64"],
                **({"reason": item["error"]} if "error" in item else {}),
            }
            for item in image_results
        )
    if docker_smoke:
        checks.extend(run_checks([["bash", str(ROOT / "scripts/docker-smoke.sh")]]))
    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images", action="store_true", help="Inspect registry indexes for linux/arm64")
    parser.add_argument("--docker-smoke", action="store_true", help="Run the opt-in real-container smoke test")
    args = parser.parse_args(argv)
    summary = summarize(validation_checks(args.images, args.docker_smoke))
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
