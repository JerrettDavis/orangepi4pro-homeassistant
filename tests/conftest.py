from pathlib import Path
import pytest
from opiha import config
from opiha.common import atomic_json

@pytest.fixture
def cfg(tmp_path):
    p = tmp_path / 'workspace/appliance.json'
    return config.initialize(p, 'lab')

@pytest.fixture
def cfg_path(cfg):
    return Path(cfg['work_dir']).parent / 'appliance.json'

@pytest.fixture
def prod(cfg, cfg_path):
    cfg['mode'] = 'appliance'
    cfg['ha_url'] = 'http://127.0.0.1:8123'
    atomic_json(cfg_path, cfg)
    return cfg

@pytest.fixture
def populated(cfg):
    d = Path(cfg['data_dir'])
    (d / 'ha/configuration.yaml').write_text('default_config:\n')
    (d / 'ha/.HA_VERSION').write_text('2026.9.3')
    store = d / 'ha/.storage'
    store.mkdir()
    atomic_json(store / 'core.config_entries', {'data': {'entries': [
        {'entry_id': 'fixture-entry', 'domain': 'zwave_js', 'data': {'url': 'ws://fixture.invalid:3000', 'token': 'TEST_ONLY_NOT_A_REAL_TOKEN'}}]}})
    atomic_json(store / 'core.entity_registry', {'data': {'entities': [{'entity_id': 'light.fixture', 'unique_id': 'fixture'}]}})
    atomic_json(store / 'core.device_registry', {'data': {'devices': [{'id': 'fixture-device'}]}})
    atomic_json(store / 'core.area_registry', {'data': {'areas': [{'id': 'fixture-area'}]}})
    (d / 'private/test-secret.txt').write_text('TEST_ONLY_PRIVATE_VALUE')
    return cfg
