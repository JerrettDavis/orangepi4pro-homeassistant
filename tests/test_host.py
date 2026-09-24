from pathlib import Path
import os

import pytest

from opiha import host
from opiha import compose, config
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
    assert layout.kiosk_unit == tmp_path / "etc/systemd/user/orangepi-homeassistant-kiosk.service"


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


def test_apply_installs_staged_release_state_config_unit_and_manifest(tmp_path):
    root = linux_root(tmp_path)
    result = host.install(root=root, release="0.1.0a1")
    layout = host.Layout.for_root(root)

    assert result["applied"] is True
    assert (layout.current / "bin/opiha").is_file()
    assert layout.current.resolve() == layout.install_root / "releases/0.1.0a1"
    assert (layout.state_root / ".opiha-state.json").is_file()
    assert (layout.state_root / "ha").is_dir()
    assert layout.config.is_file()
    assert layout.unit.is_file()
    assert "WantedBy" not in layout.unit.read_text()
    manifest = host.read_manifest(layout)
    assert manifest["release"] == "0.1.0a1"
    assert manifest["release_sha256"] == host.tree_sha256(layout.current.resolve())
    assert str(layout.unit.relative_to(root)) in manifest["owned_files"]


def test_installed_config_renders_blank_home_assistant_only(tmp_path):
    root = linux_root(tmp_path)
    host.install(root=root, release="0.1.0a1")
    layout = host.Layout.for_root(root)
    cfg = config.load(layout.config)
    rendered = compose.generate(cfg)

    assert cfg["data_dir"] == "/srv/homeassistant"
    assert cfg["work_dir"] == "/var/lib/orangepi-homeassistant"
    assert cfg["features"] == {"zwave": False, "mqtt": False, "camera": False}
    assert list(rendered["services"]) == ["homeassistant"]
    assert rendered["services"]["homeassistant"]["network_mode"] == "host"


def test_installed_unit_is_disabled_and_has_no_kiosk_or_hardware_services(tmp_path):
    root = linux_root(tmp_path)
    host.install(root=root, release="0.1.0a1")
    layout = host.Layout.for_root(root)
    text = layout.unit.read_text()

    assert "WantedBy=" not in text
    assert "opiha-kiosk" not in text
    assert "vision" not in text
    assert "zwave" not in text
    assert not list((root / "etc/systemd/system").glob("*.wants/orangepi-homeassistant.service"))


def test_installed_kiosk_user_unit_reuses_existing_xfce_session(tmp_path):
    root = linux_root(tmp_path)
    host.install(root=root, release="0.1.0a1")
    layout = host.Layout.for_root(root)
    text = layout.kiosk_unit.read_text()

    assert "User=" not in text
    assert "DISPLAY=:0" in text
    assert "XAUTHORITY=%h/.Xauthority" in text
    assert "ExecStart=/opt/orangepi-homeassistant/current/scripts/kiosk-session.sh" in text
    assert "NoNewPrivileges" not in text
    assert "WantedBy=" not in text
    assert "openbox" not in text.lower()
    assert not list((root / "etc/systemd/user").glob("*.wants/orangepi-homeassistant-kiosk.service"))


def test_upgrade_removes_installer_owned_legacy_system_kiosk_unit(tmp_path):
    root = linux_root(tmp_path)
    host.install(root=root, release="0.1.0a1")
    layout = host.Layout.for_root(root)
    legacy = root / "etc/systemd/system/orangepi-homeassistant-kiosk@.service"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text("legacy")
    manifest = host.read_manifest(layout)
    manifest["owned_files"].append(str(legacy.relative_to(root)))
    layout.manifest.write_text(__import__("json").dumps(manifest))

    host.install(root=root, release="0.1.0a2")

    assert not legacy.exists()


def test_apply_is_idempotent_and_preserves_marked_private_state(tmp_path):
    root = linux_root(tmp_path)
    host.install(root=root, release="0.1.0a1")
    private_file = root / "srv/homeassistant/ha/private-fixture.txt"
    private_file.write_text("keep")

    second = host.install(root=root, release="0.1.0a1")

    assert second["applied"] is True
    assert private_file.read_text() == "keep"
    assert second["changes"] == []


def test_apply_refuses_unowned_populated_state(tmp_path):
    root = linux_root(tmp_path)
    state = root / "srv/homeassistant"
    state.mkdir(parents=True)
    (state / "unknown.txt").write_text("valuable")
    with pytest.raises(ApplianceError, match="unowned populated state"):
        host.install(root=root, release="0.1.0a1")


def test_plan_refuses_preexisting_unowned_release_directory(tmp_path):
    root = linux_root(tmp_path)
    release = root / "opt/orangepi-homeassistant/releases/0.1.0a1"
    release.mkdir(parents=True)
    (release / "unknown").write_text("do not trust")
    with pytest.raises(ApplianceError, match="release is not owned"):
        host.plan(root=root, release="0.1.0a1")


def test_plan_refuses_preexisting_unowned_current_selector(tmp_path):
    root = linux_root(tmp_path)
    current = root / "opt/orangepi-homeassistant/current"
    current.parent.mkdir(parents=True)
    current.symlink_to("somewhere-else")
    with pytest.raises(ApplianceError, match="current selector is not owned"):
        host.plan(root=root, release="0.1.0a1")


def test_installed_release_contains_unit_template_needed_for_upgrade(tmp_path):
    root = linux_root(tmp_path)
    host.install(root=root, release="0.1.0a1")
    layout = host.Layout.for_root(root)
    assert (layout.current / "systemd/orangepi-homeassistant.service").is_file()


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode assertion")
def test_apply_private_roots_are_mode_0700(tmp_path):
    root = linux_root(tmp_path)
    host.install(root=root, release="0.1.0a1")
    layout = host.Layout.for_root(root)
    assert layout.state_root.stat().st_mode & 0o777 == 0o700
    assert layout.work_root.stat().st_mode & 0o777 == 0o700
    assert layout.config.parent.stat().st_mode & 0o777 == 0o700


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode assertion")
def test_apply_public_release_ancestors_are_traversable(tmp_path):
    root = linux_root(tmp_path)
    host.install(root=root, release="0.1.0a1")
    layout = host.Layout.for_root(root)

    assert layout.install_root.stat().st_mode & 0o777 == 0o755
    assert (layout.install_root / "releases").stat().st_mode & 0o777 == 0o755
    assert layout.current.resolve().stat().st_mode & 0o777 == 0o755
