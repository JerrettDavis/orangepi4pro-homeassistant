import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import zipfile
import pytest
from opiha.common import ApplianceError, REPO, atomic_json, sha256
from opiha import vendor


def module_at(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_overlay_never_copies_local_state(tmp_path):
    module = module_at('overlay', REPO / 'image/overlay.py')
    root = tmp_path / 'rootfs'
    (root / 'etc').mkdir(parents=True)
    (root / 'etc/os-release').write_text('ID=ubuntu\n')
    (root / 'boot').mkdir()
    boot = root / 'boot/boot.scr'
    boot.write_bytes(b'known-boot-asset')
    module.apply(root, False, False, REPO / 'config/image-defaults.json')
    dest = root / 'opt/orangepi4pro-homeassistant'
    assert (dest / 'bin/opiha').exists()
    assert not (dest / '.local').exists()
    assert not (root / 'etc/opiha/appliance.json').exists()
    assert boot.read_bytes() == b'known-boot-asset'
    assert (root / 'etc/systemd/system/multi-user.target.wants/opiha-firstboot.service').is_symlink()


def test_overlay_live_root_guard():
    module = module_at('overlay_guard', REPO / 'image/overlay.py')
    with pytest.raises(ApplianceError): module.apply(Path('/'), False, False, REPO / 'config/image-defaults.json')


def test_overlay_rejects_private_defaults(tmp_path):
    module = module_at('overlay_private', REPO / 'image/overlay.py')
    root = tmp_path / 'rootfs'
    (root / 'etc').mkdir(parents=True)
    (root / 'etc/os-release').write_text('ID=ubuntu')
    defaults = tmp_path / 'private.json'
    defaults.write_text('{"token": "fixture"}')
    with pytest.raises(ApplianceError): module.apply(root, False, False, defaults)


def test_scrub_locks_passwords_and_preserves_boot(tmp_path):
    root = tmp_path / 'rootfs'
    for d in ('etc/ssh','root/.ssh','home/vendor','boot','var/log','etc/NetworkManager/system-connections'):
        (root / d).mkdir(parents=True, exist_ok=True)
    (root / 'etc/os-release').write_text('ID=ubuntu')
    (root / 'etc/shadow').write_text('vendor:fixture-password-hash:1:2:3:4:5:6:7\n')
    (root / 'root/.ssh/id_ed25519').write_text('fixture-private-key')
    (root / 'etc/ssh/ssh_host_fixture_key').write_text('fixture-host-key')
    (root / 'var/log/fixture.log').write_text('fixture-private-log')
    (root / 'boot/boot.scr').write_bytes(b'boot')
    subprocess.run([sys.executable, str(REPO / 'image/scrub.py'), '--root', str(root), '--apply'], check=True)
    assert ':!:' in (root / 'etc/shadow').read_text()
    assert not (root / 'root/.ssh/id_ed25519').exists()
    assert (root / 'boot/boot.scr').read_bytes() == b'boot'
    subprocess.run([sys.executable, str(REPO / 'image/audit-rootfs.py'), str(root)], check=True)


def test_image_builder_dry_run_does_not_write_image(tmp_path):
    base = tmp_path / 'base.img'
    base.write_bytes(b'fixture-only-not-a-real-image')
    target = tmp_path / 'new.img'
    result = subprocess.run(['bash', str(REPO / 'image/build-from-base.sh'), '--base', str(base),
        '--sha256', sha256(base), '--root-partition','3','--output',str(target)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert 'DRY RUN' in result.stdout and not target.exists()


def test_image_builder_rejects_bad_checksum(tmp_path):
    base = tmp_path / 'base.img'; base.write_bytes(b'fixture')
    result = subprocess.run(['bash', str(REPO / 'image/build-from-base.sh'), '--base', str(base),
        '--sha256','0'*64,'--root-partition','3','--output',str(tmp_path/'new.img')], capture_output=True)
    assert result.returncode != 0


def test_vendor_hacs_checksum_and_nonoverwrite(tmp_path, monkeypatch):
    (tmp_path / 'vendor').mkdir()
    archive = tmp_path / 'vendor/hacs.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('manifest.json', '{"domain":"hacs","version":"0.0.0-fixture"}')
        z.writestr('__init__.py', '# fixture')
    atomic_json(tmp_path / 'vendor/hacs.lock.json', {'sha256':sha256(archive)})
    monkeypatch.setattr(vendor, 'REPO', tmp_path)
    config = tmp_path / 'ha'
    assert vendor.seed_hacs(config)
    target = config / 'custom_components/hacs/__init__.py'
    target.write_text('existing runtime version')
    assert not vendor.seed_hacs(config)
    assert target.read_text() == 'existing runtime version'


def test_vendor_hacs_rejects_bad_checksum(tmp_path, monkeypatch):
    (tmp_path / 'vendor').mkdir()
    (tmp_path / 'vendor/hacs.zip').write_bytes(b'bad')
    atomic_json(tmp_path / 'vendor/hacs.lock.json', {'sha256':'bad'})
    monkeypatch.setattr(vendor, 'REPO', tmp_path)
    with pytest.raises(ApplianceError): vendor.seed_hacs(tmp_path / 'ha')


def test_yaml_seeds_and_workflows_parse():
    yaml = pytest.importorskip('yaml')
    class Loader(yaml.SafeLoader): pass
    Loader.add_multi_constructor('!', lambda loader, tag, node: loader.construct_scalar(node))
    for f in (REPO / 'homeassistant').rglob('*.yaml'):
        yaml.load(f.read_text(), Loader=Loader)
    for f in (REPO / '.github/workflows').glob('*.yml'):
        yaml.safe_load(f.read_text())
