import json
import os
from pathlib import Path

import pytest

from opiha import hardware
from opiha.common import ApplianceError, REPO


def test_redact_removes_private_identifiers_recursively():
    source = {
        "address": "192.0.2.12",
        "mac": "00:11:22:33:44:55",
        "uuid": "11111111-2222-3333-4444-555555555555",
        "serial": "SECRET-SERIAL",
        "hostname": "private-host",
        "nested": ["token=secret-value", {"safe": "aarch64"}],
    }

    text = json.dumps(hardware.redact(source))

    for secret in (
        "192.0.2.12",
        "00:11:22:33:44:55",
        "11111111-2222-3333-4444-555555555555",
        "SECRET-SERIAL",
        "private-host",
        "secret-value",
    ):
        assert secret not in text
    assert "aarch64" in text


def test_redact_scrubs_sensitive_shapes_in_free_text():
    result = hardware.redact(
        "host deck-private has 2001:db8::1 and token=topsecret on 192.0.2.44"
    )
    assert result == "host [redacted] has [redacted] and [redacted] on [redacted]"


def test_parse_lsblk_accepts_json_and_preserves_ancestry():
    rows = hardware.parse_lsblk(
        '{"blockdevices":[{"name":"nvme0n1","path":"/dev/nvme0n1",'
        '"type":"disk","children":[{"name":"nvme0n1p3",'
        '"path":"/dev/nvme0n1p3","type":"part","pkname":"nvme0n1",'
        '"mountpoints":["/"]}]}]}'
    )

    assert rows[1]["parent"] == "/dev/nvme0n1"
    assert rows[1]["mountpoints"] == ["/"]
    assert "children" not in rows[0]


def test_parse_lsblk_normalizes_null_mountpoints_and_rejects_malformed_json():
    rows = hardware.parse_lsblk(
        '{"blockdevices":[{"name":"sda","path":"/dev/sda","type":"disk",'
        '"mountpoints":null}]}'
    )
    assert rows[0]["mountpoints"] == []
    with pytest.raises(ApplianceError, match="lsblk"):
        hardware.parse_lsblk("not-json")


def test_parse_findmnt_maps_only_absolute_targets():
    text = "/ /dev/nvme0n1p3\n/boot /dev/nvme0n1p2\nSWAP /dev/zram0\n"
    assert hardware.parse_findmnt(text) == {
        "/": "/dev/nvme0n1p3",
        "/boot": "/dev/nvme0n1p2",
    }


def test_parse_devices_returns_unique_device_paths_without_missing_globs():
    text = "/dev/video2\n/dev/video0\n/dev/video2\n/dev/video*\n"
    assert hardware.parse_devices(text) == ["/dev/video0", "/dev/video2"]


def fixture_rows(with_mounted_sd=False):
    rows = [
        {"path": "/dev/nvme0n1", "type": "disk", "parent": None, "mountpoints": []},
        {"path": "/dev/nvme0n1p1", "type": "part", "parent": "/dev/nvme0n1", "mountpoints": ["/boot/efi"]},
        {"path": "/dev/nvme0n1p2", "type": "part", "parent": "/dev/nvme0n1", "mountpoints": ["/boot"]},
        {"path": "/dev/nvme0n1p3", "type": "part", "parent": "/dev/nvme0n1", "mountpoints": ["/"]},
        {"path": "/dev/mmcblk1", "type": "disk", "parent": None, "mountpoints": []},
        {
            "path": "/dev/mmcblk1p1",
            "type": "part",
            "parent": "/dev/mmcblk1",
            "mountpoints": ["/mnt/check"] if with_mounted_sd else [],
        },
    ]
    return rows


def test_current_root_boot_and_efi_parent_disk_is_rejected():
    result = hardware.classify_flash_target(
        "/dev/nvme0n1",
        fixture_rows(),
        {
            "/": "/dev/nvme0n1p3",
            "/boot": "/dev/nvme0n1p2",
            "/boot/efi": "/dev/nvme0n1p1",
        },
    )
    assert not result["safe"]
    assert result["reasons"] == ["boot", "efi", "mounted", "root"]


def test_mounted_sd_is_rejected_even_when_not_boot_disk():
    result = hardware.classify_flash_target(
        "/dev/mmcblk1", fixture_rows(with_mounted_sd=True), {"/": "/dev/nvme0n1p3"}
    )
    assert not result["safe"]
    assert result["reasons"] == ["mounted"]


def test_unmounted_unprotected_disk_is_safe_candidate():
    result = hardware.classify_flash_target(
        "/dev/mmcblk1", fixture_rows(), {"/": "/dev/nvme0n1p3"}
    )
    assert result == {"path": "/dev/mmcblk1", "safe": True, "reasons": []}


def test_ambiguous_or_non_disk_target_is_rejected():
    missing = hardware.classify_flash_target("/dev/missing", fixture_rows(), {})
    partition = hardware.classify_flash_target("/dev/nvme0n1p3", fixture_rows(), {})
    duplicate = hardware.classify_flash_target(
        "/dev/mmcblk1", fixture_rows() + [fixture_rows()[4]], {}
    )
    assert missing["reasons"] == ["unknown-device"]
    assert partition["reasons"] == ["not-whole-disk"]
    assert duplicate["reasons"] == ["ambiguous"]


def test_unresolved_protected_device_ancestry_fails_closed():
    rows = fixture_rows()
    rows[3]["parent"] = "/dev/device-mapper-missing"
    result = hardware.classify_flash_target(
        "/dev/mmcblk1", rows, {"/": "/dev/nvme0n1p3"}
    )
    assert not result["safe"]
    assert result["reasons"] == ["ambiguous"]


def test_private_inventory_refuses_repository_and_symlink_paths(tmp_path):
    with pytest.raises(ApplianceError, match="outside the repository"):
        hardware.write_inventory(
            {"private": True}, REPO / "private-inventory.json", private=True
        )
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(ApplianceError, match="symlink"):
        hardware.write_inventory(
            {"private": True}, link / "private.json", private=True
        )


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode assertion")
def test_private_inventory_file_is_mode_0600(tmp_path):
    target = tmp_path / "private.json"
    hardware.write_inventory({"private": True}, target, private=True)
    assert target.stat().st_mode & 0o777 == 0o600


def test_run_command_reports_missing_and_permission_denied(monkeypatch):
    missing = hardware.run_command(["opiha-command-that-does-not-exist"])
    assert missing.status == "unavailable"
    assert missing.returncode is None

    class Denied:
        returncode = 1
        stdout = ""
        stderr = "permission denied"

    monkeypatch.setattr(hardware.subprocess, "run", lambda *args, **kwargs: Denied())
    denied = hardware.run_command(["docker", "info"])
    assert denied.status == "permission-denied"
    assert denied.stdout == ""


def test_collect_inventory_uses_fixed_commands_and_sanitizes_public_result():
    calls = []

    def runner(argv):
        calls.append(tuple(argv))
        fixtures = {
            ("uname", "-m"): "aarch64\n",
            ("uname", "-r"): "5.15.147-sun60iw2-cyberdeck\n",
            ("hostname",): "private-host\n",
            ("lsblk", "--json", "-o", "NAME,PATH,TYPE,PKNAME,SIZE,FSTYPE,MOUNTPOINTS,MODEL"): '{"blockdevices":[]}',
            ("findmnt", "-rn", "-o", "TARGET,SOURCE"): "/ /dev/nvme0n1p3\n",
        }
        return hardware.CommandResult(tuple(argv), 0, fixtures.get(tuple(argv), ""), "ok")

    result = hardware.collect_inventory(runner=runner)
    text = json.dumps(result)
    assert result["system"]["architecture"] == "aarch64"
    assert "private-host" not in text
    assert all(isinstance(call, tuple) for call in calls)
    assert not any(call[0] in {"sh", "bash", "sudo"} for call in calls)
