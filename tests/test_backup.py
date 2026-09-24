import io
import json
from pathlib import Path
import shutil
import tarfile
import pytest
from opiha import backup, config
from opiha.common import ApplianceError, atomic_json


def archive(path, members):
    with tarfile.open(path, 'w') as a:
        for name, content, kind in members:
            info = tarfile.TarInfo(name)
            info.type = kind
            if kind == tarfile.REGTYPE:
                info.size = len(content)
                a.addfile(info, io.BytesIO(content))
            else:
                info.linkname = '/etc/passwd'
                a.addfile(info)


def test_snapshot_roundtrip(populated, tmp_path):
    data = Path(populated['data_dir'])
    (data / 'ha/home-assistant_v2.db-wal').write_bytes(b'fixture-wal')
    destination = tmp_path / 'backup.tar.gz'
    manifest = backup.create_tar(data, destination, config.portable_settings(populated))
    staged = tmp_path / 'staged'
    result = backup.extract_verified(destination, staged)
    assert result == manifest
    for file, name in backup.state_files(data):
        assert (staged / name).read_bytes() == file.read_bytes()
    assert (staged / 'ha/home-assistant_v2.db-wal').exists()
    assert (destination.stat().st_mode & 0o777) == 0o600

@pytest.mark.parametrize('name,kind', [('../escape', tarfile.REGTYPE), ('/escape', tarfile.REGTYPE),
    ('ha/symlink', tarfile.SYMTYPE), ('ha/hardlink', tarfile.LNKTYPE), ('ha/fifo', tarfile.FIFOTYPE),
    ('ha/directory', tarfile.DIRTYPE), ('unknown/data', tarfile.REGTYPE), ('ha', tarfile.REGTYPE)])
def test_rejects_malicious_archive(tmp_path, name, kind):
    src = tmp_path / 'bad.tar'
    archive(src, [(name, b'bad', kind)])
    with pytest.raises(ApplianceError): backup.extract_verified(src, tmp_path / 'staged')
    assert not (tmp_path / 'escape').exists()


def test_duplicate_members_rejected(tmp_path):
    src = tmp_path / 'bad.tar'
    archive(src, [('ha/a', b'one', tarfile.REGTYPE), ('ha/a', b'two', tarfile.REGTYPE)])
    with pytest.raises(ApplianceError, match='Duplicate'): backup.extract_verified(src, tmp_path / 's')


def test_checksum_tamper_rejected(tmp_path):
    m = {'format': backup.FORMAT, 'files': {'ha/a': {'size': 3, 'sha256': 'wrong'}}}
    src = tmp_path / 'bad.tar'
    archive(src, [('ha/a', b'one', tarfile.REGTYPE), ('manifest.json', json.dumps(m).encode(), tarfile.REGTYPE)])
    with pytest.raises(ApplianceError, match='integrity'): backup.extract_verified(src, tmp_path / 's')


def test_size_limit_enforced(tmp_path):
    src = tmp_path / 'bad.tar'
    archive(src, [('ha/a', b'0123456789', tarfile.REGTYPE)])
    with pytest.raises(ApplianceError, match='size limit'): backup.extract_verified(src, tmp_path / 's', max_bytes=5)


def test_official_backup_is_not_misclassified(tmp_path):
    src = tmp_path / 'ha.tar'
    archive(src, [('backup.json', b'{}', tarfile.REGTYPE)])
    with pytest.raises(ApplianceError, match='Home Assistant backup'): backup.extract_verified(src, tmp_path / 's')


def test_cache_and_browser_locks_excluded(populated, tmp_path):
    data = Path(populated['data_dir'])
    (data / 'ha/deps').mkdir()
    (data / 'ha/deps/old.so').write_bytes(b'architecture-specific')
    (data / 'kiosk/SingletonLock').symlink_to('/unreachable/test')
    names = [name for _, name in backup.state_files(data)]
    assert all('deps' not in n and 'SingletonLock' not in n for n in names)


def test_unknown_state_symlink_rejected(populated):
    data = Path(populated['data_dir'])
    (data / 'ha/stolen').symlink_to('/etc/passwd')
    with pytest.raises(ApplianceError): list(backup.state_files(data))


def test_partial_file_is_never_deleted(populated, tmp_path):
    target = tmp_path / 'existing.tar'
    partial = tmp_path / 'existing.tar.partial'
    partial.write_text('previous-attempt')
    with pytest.raises(ApplianceError): backup.create_tar(Path(populated['data_dir']), target, {})
    assert partial.read_text() == 'previous-attempt'


def test_atomic_commit_retains_previous_and_disarms(populated, tmp_path):
    cfg = populated
    data = Path(cfg['data_dir'])
    stage = data.parent / 'new-state'
    config.create_state(stage)
    (stage / 'ha/configuration.yaml').write_text('new configuration')
    atomic_json(Path(cfg['work_dir']) / 'activated.json', {'approved': True})
    previous = backup.commit_state(cfg, stage)
    assert (previous / 'ha/configuration.yaml').read_text() == 'default_config:\n'
    assert (data / 'ha/configuration.yaml').read_text() == 'new configuration'
    assert not (Path(cfg['work_dir']) / 'activated.json').exists()
    assert (Path(cfg['work_dir']) / 'restored.json').exists()


def test_repair_interrupted_commit(populated):
    cfg = populated
    data = Path(cfg['data_dir'])
    old = data.with_name(data.name + '.rollback-test')
    data.rename(old)
    work = Path(cfg['work_dir'])
    atomic_json(work / 'restore-journal.json', {'data': str(data), 'previous': str(old), 'staging': str(data.parent / 'staged'), 'phase': 'previous_moved'})
    backup.repair_restore(cfg)
    assert (data / 'ha/configuration.yaml').exists()
    assert not (work / 'restore-journal.json').exists()


def test_offline_snapshot_requires_attestation(cfg):
    with pytest.raises(ApplianceError):
        with backup.quiesced(cfg, offline=True): pass

@pytest.mark.skipif(not shutil.which('openssl'), reason='OpenSSL is not installed')
def test_real_signature_and_tamper_detection(tmp_path):
    from opiha.common import run
    private, public = tmp_path / 'private.pem', tmp_path / 'public.pem'
    run(['openssl', 'genpkey', '-algorithm', 'ED25519', '-out', str(private)])
    run(['openssl', 'pkey', '-in', str(private), '-pubout', '-out', str(public)])
    source, signature = tmp_path / 'backup', tmp_path / 'backup.sig'
    source.write_bytes(b'fixture data' * 1000)
    backup.sign(source, signature, private)
    backup.verify_signature(source, signature, public)
    source.write_bytes(b'tampered')
    with pytest.raises(ApplianceError): backup.verify_signature(source, signature, public)

@pytest.mark.skipif(not shutil.which('age') or not shutil.which('age-keygen'), reason='age/age-keygen not installed')
def test_real_age_roundtrip(tmp_path):
    from opiha.common import run
    identity = tmp_path / 'identity.txt'
    run(['age-keygen', '-o', str(identity)], capture=True)
    recipient = run(['age-keygen', '-y', str(identity)], capture=True).stdout.strip()
    source, encrypted, clear = tmp_path / 'source', tmp_path / 'state.tar.age', tmp_path / 'clear'
    source.write_bytes(b'private-test-data' * 1024)
    backup.encrypt(source, encrypted, recipient)
    backup.decrypt(encrypted, clear, identity)
    assert clear.read_bytes() == source.read_bytes()
