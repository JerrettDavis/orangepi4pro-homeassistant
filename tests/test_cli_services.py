import copy
import io
import json
from pathlib import Path
import sqlite3
import threading
import urllib.request
import pytest
from opiha import backup, cli, config, hardware, host, inventory, status
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


def test_blank_onboarding_can_restart_after_ha_creates_auth_storage(prod, monkeypatch):
    auth = Path(prod["data_dir"]) / "ha/.storage/auth"
    auth.parent.mkdir(parents=True, exist_ok=True)
    auth.write_text('{"version": 1, "data": {"users": []}}')
    calls = []
    monkeypatch.setattr(cli.compose, "command", lambda cfg, *args, **kwargs: calls.append(args))

    cli.start(prod, onboarding=True)

    assert ("up", "-d", "--remove-orphans", "homeassistant") in calls


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


def test_hardware_inventory_cli_emits_sanitized_json(monkeypatch, capsys):
    monkeypatch.setattr(
        hardware,
        "collect_inventory",
        lambda private=False: {"system": {"architecture": "aarch64"}, "address": "redacted"},
    )
    assert cli.main(["hardware", "inventory"]) == 0
    output = capsys.readouterr().out
    assert '"architecture": "aarch64"' in output
    assert '"address": "redacted"' in output


def test_hardware_storage_cli_does_not_require_appliance_config(monkeypatch, capsys):
    monkeypatch.setattr(
        hardware,
        "collect_section",
        lambda section: {"section": section, "protected": ["root"]},
    )
    assert cli.main(["hardware", "storage"]) == 0
    assert '"section": "storage"' in capsys.readouterr().out


def test_host_plan_cli_does_not_require_appliance_config(monkeypatch, capsys):
    monkeypatch.setattr(host, "plan", lambda **kwargs: {"apply": False, "changes": []})
    assert cli.main(["host", "plan"]) == 0
    assert '"apply": false' in capsys.readouterr().out


def test_host_install_cli_is_dry_run_without_apply(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(host, "plan", lambda **kwargs: calls.append(kwargs) or {"apply": False})
    monkeypatch.setattr(host, "install", lambda **kwargs: pytest.fail("must not apply"))
    assert cli.main(["host", "install", "--root", "/fixture"]) == 0
    assert calls[0]["root"] == Path("/fixture")


def test_host_install_live_root_requires_elevation(monkeypatch, capsys):
    monkeypatch.setattr(cli.os, "geteuid", lambda: 1000)
    assert cli.main(["host", "install", "--apply"]) == 2
    assert "requires root" in capsys.readouterr().err


def test_host_install_synthetic_root_can_apply_without_elevation(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(cli.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(host, "install", lambda **kwargs: calls.append(kwargs) or {"applied": True})
    assert cli.main(["host", "install", "--root", str(tmp_path), "--apply"]) == 0
    assert calls[0]["root"] == tmp_path
