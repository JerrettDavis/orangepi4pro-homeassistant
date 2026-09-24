import copy
import json
from pathlib import Path
import pytest
from opiha import config, compose
from opiha.common import ApplianceError, guarded_root, safe_relative


def test_lab_is_quarantined_even_when_features_enabled(cfg):
    cfg['features'] = {'zwave': True, 'mqtt': True, 'camera': True}
    cfg['zwave_device'] = '/dev/serial/by-id/fixture'
    cfg['camera_device'] = '/dev/video0'
    c = compose.generate(cfg)
    assert list(c['services']) == ['homeassistant']
    assert c['networks']['quarantine']['internal'] is True
    s = c['services']['homeassistant']
    # Docker suppresses published ports on internal networks. Do not advertise
    # a host binding that the daemon cannot create or tempt callers to weaken
    # the quarantine network to make it reachable.
    assert 'ports' not in s
    assert 'devices' not in s and 'network_mode' not in s
    assert 'privileged' not in s


def test_production_local_admin_ports(prod):
    prod['features'] = {x: True for x in prod['features']}
    prod['zwave_device'] = '/dev/serial/by-id/fixture'
    prod['camera_device'] = '/dev/v4l/by-id/fixture'
    c = compose.generate(prod)
    assert c['services']['homeassistant']['network_mode'] == 'host'
    for name, s in c['services'].items():
        assert not s.get('privileged', False)
        assert all(port.startswith('127.0.0.1:') for port in s.get('ports', []))
        assert '/var/run/docker.sock' not in json.dumps(s)
    assert c['services']['zwave']['environment']['ZWAVE_PORT'] == '/dev/zwave'
    assert c['services']['zwave']['devices'] == ['/dev/serial/by-id/fixture:/dev/zwave']
    assert c['services']['camera']['mem_limit'] == '384m'


def test_cached_images_never_pull(cfg):
    cfg['images']['homeassistant'] = 'opiha-cache/homeassistant:' + 'a' * 64
    assert compose.generate(cfg)['services']['homeassistant']['pull_policy'] == 'never'

@pytest.mark.parametrize('root', ['/', '/etc', '/srv', '/var/lib', '/home', '/tmp'])
def test_dangerous_roots_rejected(root):
    with pytest.raises(ApplianceError): guarded_root(Path(root))

@pytest.mark.parametrize('name', ['../escape', '/absolute', 'ha/../../escape', 'ha/./bad', 'C:/escape', 'ha\\escape', ''])
def test_unsafe_archive_names(name):
    with pytest.raises(ApplianceError): safe_relative(name)


def test_symlink_roots_rejected(tmp_path):
    (tmp_path / 'actual').mkdir()
    (tmp_path / 'link').symlink_to(tmp_path / 'actual', target_is_directory=True)
    with pytest.raises(ApplianceError): guarded_root(tmp_path / 'link/state')

@pytest.mark.parametrize('reference', ['repo:latest', 'repo:stable', 'repo:master', 'repo;rm:-rf'])
def test_bad_images(cfg, reference):
    cfg['images']['homeassistant'] = reference
    with pytest.raises(ApplianceError): config.validate(cfg)


def test_nested_roots_rejected(cfg):
    cfg['work_dir'] = cfg['data_dir'] + '/work'
    with pytest.raises(ApplianceError): config.validate(cfg)


def test_unstable_zwave_device_rejected(cfg):
    cfg['features']['zwave'] = True
    cfg['zwave_device'] = '/dev/ttyUSB0'
    with pytest.raises(ApplianceError): config.validate(cfg)


def test_reinit_does_not_overwrite(cfg_path):
    before = cfg_path.read_bytes()
    with pytest.raises(ApplianceError): config.initialize(cfg_path, 'lab')
    assert cfg_path.read_bytes() == before


def test_seed_never_overwrites(populated):
    p = Path(populated['data_dir']) / 'ha/configuration.yaml'
    before = p.read_bytes()
    config.seed(populated)
    assert p.read_bytes() == before


def test_seed_new_install(cfg):
    config.seed(cfg)
    d = Path(cfg['data_dir'])
    assert (d / 'ha/configuration.yaml').exists()
    assert (d / 'ha/dashboards/orangepi.yaml').exists()


def test_zwave_session_secrets_only_in_private_state(prod):
    prod['features']['zwave'] = True
    prod['zwave_device'] = '/dev/serial/by-id/fixture'
    rendered = compose.prepare(prod)
    data = Path(prod['data_dir'])
    secret = data / 'private/zwave.env'
    assert secret.exists() and (secret.stat().st_mode & 0o777) == 0o600
    before = secret.read_bytes()
    assert b'SESSION_SECRET=' in before
    assert before.decode().splitlines()[0].split('=')[1] not in rendered.read_text()
    compose.prepare(prod)
    assert secret.read_bytes() == before


def test_custom_lab_port_does_not_change_container_health_port(cfg):
    cfg['lab_port'] = 28123
    cfg['ha_url'] = 'http://127.0.0.1:28123'
    health = compose.generate(cfg)['services']['homeassistant']['healthcheck']['test'][-1]
    assert ':8123/' in health and ':28123/' not in health


def test_reject_dollar_in_compose_paths(cfg):
    from opiha.config import validate
    from opiha.common import ApplianceError
    import pytest
    cfg = dict(cfg)
    cfg['data_dir'] += '/$HOME'
    with pytest.raises(ApplianceError):
        validate(cfg)
