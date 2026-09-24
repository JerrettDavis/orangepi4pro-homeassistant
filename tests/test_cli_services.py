import copy
import io
import json
from pathlib import Path
import sqlite3
import threading
import urllib.request
import pytest
from opiha import backup, cli, config, inventory, status
from opiha.common import ApplianceError, atomic_json
from opiha.server import make_server
from opiha.vision import Presence


def test_inventory_redaction(populated):
    result = inventory.inventory(Path(populated['data_dir']) / 'ha')
    output = json.dumps(result)
    assert result['entity_ids'] == ['light.fixture']
    assert 'TEST_ONLY_NOT_A_REAL_TOKEN' not in output
    assert 'fixture.invalid' not in output
    assert 'TEST_ONLY_PRIVATE_VALUE' not in output


def test_compare_identity_diff(populated):
    before = inventory.inventory(Path(populated['data_dir']) / 'ha')
    after = copy.deepcopy(before)
    after['entity_ids'] = []
    result = inventory.compare(before, after)
    assert not result['matches']
    assert result['differences']['entity_ids']['missing'] == ['light.fixture']
    assert inventory.compare(before, before)['matches']

@pytest.mark.parametrize('source,target,allow,valid', [('2026.9.3','2026.9.3',False,True),
    ('2026.9.3','2026.8.3',True,False), ('2026.8.3','2026.9.3',False,False),
    ('2026.8.3','2026.9.3',True,True)])
def test_version_gate(cfg, source, target, allow, valid):
    cfg['ha_version'] = target
    if valid: cli.check_version(source, cfg, allow)
    else:
        with pytest.raises(ApplianceError): cli.check_version(source, cfg, allow)


def test_start_restored_production_requires_activation(prod, monkeypatch):
    atomic_json(Path(prod['work_dir']) / 'restored.json', {})
    called = []
    monkeypatch.setattr(cli.compose, 'command', lambda *a, **k: called.append(a))
    with pytest.raises(ApplianceError): cli.start(prod, onboarding=True)
    assert called == []


def test_optional_device_failure_does_not_block_ha(prod, monkeypatch):
    prod['features']['camera'] = True
    prod['camera_device'] = '/dev/nonexistent-fixture'
    calls = []
    monkeypatch.setattr(cli.compose, 'command', lambda cfg, *a, **k: calls.append(a))
    cli.start(prod, onboarding=True)
    assert ('up', '-d', '--remove-orphans', 'homeassistant') in calls
    assert not any(args[-1] == 'camera' for args in calls)


def test_cli_backup_and_restore(populated, cfg_path, tmp_path):
    artifact = tmp_path / 'backup.tar.gz'
    assert cli.main(['--config',str(cfg_path),'backup','--output',str(artifact),'--plaintext','--offline','--source-stopped']) == 0
    data = Path(populated['data_dir'])
    (data / 'ha/configuration.yaml').write_text('changed')
    args = ['--config',str(cfg_path),'restore','--bundle',str(artifact),'--offline','--source-stopped']
    assert cli.main(args) == 0
    assert (data / 'ha/configuration.yaml').read_text() == 'changed'
    assert cli.main(args + ['--apply','--replace']) == 0
    assert (data / 'ha/configuration.yaml').read_text() == 'default_config:\n'


def test_raw_config_import_preserves_other_components(cfg, cfg_path, tmp_path):
    source = tmp_path / 'source-config'
    source.mkdir()
    (source / 'configuration.yaml').write_text('default_config:\n')
    (source / '.HA_VERSION').write_text('2026.9.3')
    (source / '.storage').mkdir()
    (source / '.storage/auth').write_text('fixture-auth')
    data = Path(cfg['data_dir'])
    (data / 'zwave/cache.json').write_text('fixture-cache')
    assert cli.main(['--config',str(cfg_path),'import-config','--source',str(source),'--source-stopped','--offline','--apply','--replace']) == 0
    assert (data / 'ha/.storage/auth').read_text() == 'fixture-auth'
    assert (data / 'zwave/cache.json').read_text() == 'fixture-cache'


def test_sqlite_integrity(tmp_path):
    path = tmp_path / 'ha.db'
    con = sqlite3.connect(path)
    con.execute('CREATE TABLE states (id INTEGER PRIMARY KEY, value TEXT)')
    con.execute("INSERT INTO states(value) VALUES ('fixture')")
    con.commit(); con.close()
    assert inventory.sqlite_check(path) == 'ok'


def test_presence_debounce_and_expiry():
    p = Presence(hold=10, hits=2)
    assert not p.update(True, 0)
    assert p.update(True, 1)
    assert p.update(False, 8)
    assert not p.update(False, 12)
    assert not p.update(True, 13, available=False)
    assert not p.update(True, 14)


def test_stale_vision_unavailable(tmp_path):
    atomic_json(tmp_path / 'vision.json', {'timestamp':100,'available':True,'person':True})
    assert status.vision_status(tmp_path, now=105)['person']
    assert not status.vision_status(tmp_path, now=120)['available']
    assert not status.vision_status(tmp_path, now=120)['person']
    assert not status.vision_status(tmp_path, now=90)['available']


def test_actual_status_http_server(cfg, monkeypatch):
    monkeypatch.setattr(status, 'responding', lambda url: True)
    server = make_server(cfg, port=0)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        base = 'http://127.0.0.1:' + str(server.server_port)
        with urllib.request.urlopen(base + '/health.json') as response:
            data = json.load(response)
            assert data['homeassistant']['responding']
            assert response.headers['Cache-Control'] == 'no-store'
        with urllib.request.urlopen(base + '/') as response:
            assert b'Home Control' in response.read()
        with pytest.raises(urllib.error.HTTPError) as e: urllib.request.urlopen(base + '/../../etc/passwd')
        assert e.value.code == 404
        request = urllib.request.Request(base + '/', data=b'{}', method='POST')
        with pytest.raises(urllib.error.HTTPError) as e: urllib.request.urlopen(request)
        assert e.value.code == 501
    finally:
        server.shutdown(); server.server_close(); t.join()


def test_status_cannot_listen_on_lan(cfg):
    with pytest.raises(ValueError): make_server(cfg, host='0.0.0.0', port=0)


def test_actual_hog_inference_on_blank_frame():
    cv2 = pytest.importorskip('cv2')
    np = pytest.importorskip('numpy')
    from opiha.vision import HogDetector
    detector = HogDetector()
    assert detector.detect(np.zeros((480,640,3), dtype=np.uint8)) == 0
    assert detector.detect(np.zeros((64,32,3), dtype=np.uint8)) == 0
