import json
from pathlib import Path
import shutil
import subprocess
import sys
import pytest
from opiha_apps import __version__
from opiha_apps.common import AppError
from opiha_apps.install import install
ROOT = Path(__file__).resolve().parents[2]


def test_cli_readonly_commands():
    command = [sys.executable, str(ROOT / 'bin/opiha-apps')]
    assert subprocess.check_output(command + ['--version'], text=True).strip() == __version__
    assert len(json.loads(subprocess.check_output(command + ['catalog'], text=True))) == 5


def test_main_cli_delegates_to_native_apps():
    main = [sys.executable, str(ROOT / 'bin/opiha'), 'apps']
    assert len(json.loads(subprocess.check_output(main + ['catalog'], text=True))) == 5
    assert subprocess.check_output(main + ['--version'], text=True).strip() == __version__


def test_docker_smoke_is_preview_without_apply():
    smoke = ROOT / 'scripts/native-apps/docker-smoke.py'
    assert subprocess.run([sys.executable, str(smoke)], capture_output=True).returncode == 0


# Restored-panel adoption is deliberately separate from ordinary installation.
def test_adopt_byte_identical_restored_panel(tmp_path):
    root = tmp_path / 'root'
    (root / 'etc').mkdir(parents=True)
    (root / 'etc/os-release').write_text('ID=ubuntu')
    ha = root / 'srv/homeassistant/ha'
    ha.mkdir(parents=True)
    (ha / 'configuration.yaml').write_text('default_config:\nopiha_apps:\n')
    (root / 'etc/orangepi-homeassistant').mkdir()
    (root / 'etc/orangepi-homeassistant/appliance.json').write_text(json.dumps({'mode': 'appliance', 'data_dir': '/srv/homeassistant'}))
    shutil.copytree(ROOT / 'homeassistant/custom_components/opiha_apps', ha / 'custom_components/opiha_apps', ignore=shutil.ignore_patterns('__pycache__'))
    with pytest.raises(AppError):
        install(root=root, apply=True)
    assert install(root=root, apply=True, architecture='arm64', adopt_restored=True)['applied']
    assert (ha / 'configuration.yaml').read_text().count('opiha_apps:') == 1
