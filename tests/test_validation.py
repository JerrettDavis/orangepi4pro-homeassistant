import importlib.util
from pathlib import Path
import subprocess

import pytest

from opiha.common import REPO


def load_validation():
    path = REPO / "scripts/validate.py"
    spec = importlib.util.spec_from_file_location("opiha_validation", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_manifest_platforms_ignores_attestations():
    validation = load_validation()
    raw = "Platform: linux/amd64\nPlatform: unknown/unknown\nPlatform: linux/arm64/v8\n"
    assert validation.manifest_platforms(raw) == {"linux/amd64", "linux/arm64/v8"}


def test_missing_arm64_is_failure():
    validation = load_validation()
    result = validation.validate_images(
        {"fixture": "example.invalid/app:1"},
        inspector=lambda _: "Platform: linux/amd64\n",
    )
    assert result == [
        {"name": "fixture", "image": "example.invalid/app:1", "arm64": False}
    ]


def test_arm64_v8_and_arm64_both_satisfy_architecture_check():
    validation = load_validation()
    for platform in ("linux/arm64", "linux/arm64/v8"):
        result = validation.validate_images(
            {"fixture": "example.invalid/app:1"},
            inspector=lambda _, value=platform: f"Platform: {value}\n",
        )
        assert result[0]["arm64"] is True


def test_validation_aggregate_preserves_skip_reason():
    validation = load_validation()
    summary = validation.summarize(
        [{"name": "age", "status": "skip", "reason": "age not installed"}]
    )
    assert summary["passed"] == 0
    assert summary["failed"] == 0
    assert summary["skipped"] == 1
    assert summary["checks"][0]["reason"] == "age not installed"


def test_run_checks_records_failures_without_running_a_shell():
    validation = load_validation()
    calls = []

    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 7, "", "fixture failure")

    results = validation.run_checks([["python3", "fixture.py"]], runner=runner)
    assert results[0]["status"] == "fail"
    assert results[0]["reason"] == "exit 7: fixture failure"
    assert calls[0][0] == ["python3", "fixture.py"]
    assert calls[0][1]["shell"] is False


def test_validate_images_reports_inspection_error_as_failure():
    validation = load_validation()

    def broken(_):
        raise subprocess.CalledProcessError(1, ["docker"], stderr="not found")

    result = validation.validate_images({"fixture": "example.invalid/app:1"}, broken)
    assert result == [
        {
            "name": "fixture",
            "image": "example.invalid/app:1",
            "arm64": False,
            "error": "inspection failed",
        }
    ]


def test_registry_index_platforms_reads_oci_index_and_ignores_attestations():
    validation = load_validation()
    document = {
        "manifests": [
            {"platform": {"os": "linux", "architecture": "amd64"}},
            {"platform": {"os": "unknown", "architecture": "unknown"}},
            {"platform": {"os": "linux", "architecture": "arm64", "variant": "v8"}},
        ]
    }
    assert validation.registry_index_platforms(document) == {
        "linux/amd64",
        "linux/arm64/v8",
    }
