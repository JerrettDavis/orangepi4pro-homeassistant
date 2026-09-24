import json

import pytest

from opiha import hardware
from opiha.common import ApplianceError


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
