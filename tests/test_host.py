from pathlib import Path

import pytest

from opiha import host
from opiha.common import ApplianceError


def linux_root(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    (root / "etc").mkdir(parents=True)
    (root / "etc/os-release").write_text("ID=ubuntu\nVERSION_ID=22.04\n")
    return root


def test_layout_uses_dedicated_public_private_and_generated_roots(tmp_path):
    layout = host.Layout.for_root(tmp_path)
    assert layout.install_root == tmp_path / "opt/orangepi-homeassistant"
    assert layout.current == tmp_path / "opt/orangepi-homeassistant/current"
    assert layout.state_root == tmp_path / "srv/homeassistant"
    assert layout.work_root == tmp_path / "var/lib/orangepi-homeassistant"
    assert layout.config == tmp_path / "etc/orangepi-homeassistant/appliance.json"
    assert layout.unit == tmp_path / "etc/systemd/system/orangepi-homeassistant.service"


def test_plan_is_read_only_and_lists_first_install_changes(tmp_path):
    root = linux_root(tmp_path)
    before = sorted(path.relative_to(root) for path in root.rglob("*"))
    result = host.plan(root=root, release="0.1.0a1")
    after = sorted(path.relative_to(root) for path in root.rglob("*"))

    assert before == after
    assert result["apply"] is False
    assert result["release"] == "0.1.0a1"
    assert "install-release" in result["changes"]
    assert "create-private-state" in result["changes"]
    assert "install-disabled-unit" in result["changes"]
    assert result["starts_services"] is False
    assert result["changes_boot_or_network"] is False


def test_plan_rejects_non_linux_root(tmp_path):
    with pytest.raises(ApplianceError, match="Linux root"):
        host.plan(root=tmp_path, release="0.1.0a1")


def test_plan_rejects_symlinked_destination_ancestor(tmp_path):
    root = linux_root(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "opt").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ApplianceError, match="symlink"):
        host.plan(root=root, release="0.1.0a1")


def test_plan_refuses_unowned_existing_unit(tmp_path):
    root = linux_root(tmp_path)
    unit = root / "etc/systemd/system/orangepi-homeassistant.service"
    unit.parent.mkdir(parents=True)
    unit.write_text("unrelated service")
    with pytest.raises(ApplianceError, match="not owned"):
        host.plan(root=root, release="0.1.0a1")
