import importlib.util
from pathlib import Path
import subprocess
import sys
import zipfile
import pytest
from opiha.common import REPO


def load_scanner(monkeypatch):
    monkeypatch.syspath_prepend(str(REPO/'scripts'))
    spec=importlib.util.spec_from_file_location('source_scan',REPO/'scripts/scan-public.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_source_scanner_excludes_private_workspace(tmp_path, monkeypatch):
    scanner=load_scanner(monkeypatch)
    (tmp_path/'.local').mkdir()
    (tmp_path/'.local/identity.txt').write_text('AGE-SECRET-KEY-1'+'A'*50)
    (tmp_path/'README.md').write_text('# clean source')
    count,issues=scanner.scan(tmp_path)
    assert count==1 and not issues


def test_source_scanner_blocks_real_shaped_private_key(tmp_path, monkeypatch):
    scanner=load_scanner(monkeypatch)
    (tmp_path/'config').mkdir()
    (tmp_path/'config/accidental.pem').write_text('-----BEGIN PRIVATE KEY-----\n'+'A'*40+'\n')
    _,issues=scanner.scan(tmp_path)
    assert issues and 'credential' in issues[0][1]


def test_packages_only_public_files_and_is_deterministic(tmp_path):
    archives=[]
    for name in ('first','second'):
        output=tmp_path/name
        subprocess.run([sys.executable,str(REPO/'scripts/package.py'),'--output',str(output)],check=True,capture_output=True)
        archives.append(next(output.glob('*.zip')))
    assert archives[0].read_bytes()==archives[1].read_bytes()
    with zipfile.ZipFile(archives[0]) as archive:
        names=archive.namelist()
        assert 'orangepi4pro-homeassistant/README.md' in names
        assert 'orangepi4pro-homeassistant/src/opiha/cli.py' in names
        assert not any('/.local/' in name or '/__pycache__/' in name for name in names)
        assert not any(name.endswith(('identity.txt','.age','appliance.json')) for name in names)


@pytest.mark.parametrize(
    "value",
    [
        "10.23.45.67",
        "00:11:22:33:44:55",
        "UUID=11111111-2222-3333-4444-555555555555",
        "AGE-SECRET-KEY-1" + "A" * 40,
    ],
)
def test_source_scanner_blocks_private_machine_identifiers(tmp_path, monkeypatch, value):
    scanner = load_scanner(monkeypatch)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/LIVE-HARDWARE-BASELINE.md").write_text(value)
    _, issues = scanner.scan(tmp_path)
    assert issues


def test_source_scanner_cli_scans_explicit_capture_directory(tmp_path):
    (tmp_path / "hardware-inventory.json").write_text("10.23.45.67")
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts/scan-public.py"), str(tmp_path)],
        text=True,
        capture_output=True,
    )
    assert result.returncode == 1
    assert "possible private machine identifier" in result.stdout
