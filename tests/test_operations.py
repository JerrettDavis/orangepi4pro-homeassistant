import argparse
import copy
from pathlib import Path
import shutil
import pytest
from opiha import cli, backup, compose, config
from opiha.common import ApplianceError, atomic_json, run


def test_backup_docker_orchestration_resumes_exact_services(populated, cfg_path, tmp_path, monkeypatch):
    events = []
    monkeypatch.setattr(compose, 'running', lambda cfg: ['homeassistant'])
    monkeypatch.setattr(compose, 'command', lambda cfg, *args, **kw: events.append(args))
    assert cli.main(['--config', str(cfg_path), 'backup', '--output', str(tmp_path/'state.tar'), '--plaintext']) == 0
    assert events == [('down','--timeout','120'), ('up','-d','homeassistant')]


def test_restore_apply_remains_stopped(populated, cfg_path, tmp_path, monkeypatch):
    source = tmp_path / 'state.tar'
    backup.create_tar(Path(populated['data_dir']), source, config.portable_settings(populated))
    events=[]
    monkeypatch.setattr(compose, 'running', lambda cfg: ['homeassistant'])
    monkeypatch.setattr(compose, 'command', lambda cfg, *args, **kw: events.append(args))
    assert cli.main(['--config',str(cfg_path),'restore','--bundle',str(source),'--apply','--replace']) == 0
    assert events == [('down','--timeout','120')]


def test_restore_settings_cannot_escape_lab(populated, cfg_path, tmp_path):
    settings = config.portable_settings(populated)
    settings['mode'] = 'appliance'
    settings['features'] = {'zwave':True,'camera':True,'mqtt':True}
    settings['zwave_device'] = '/dev/serial/by-id/fixture'
    settings['camera_device'] = '/dev/video0'
    source = tmp_path / 'state.tar'
    backup.create_tar(Path(populated['data_dir']), source, settings)
    assert cli.main(['--config',str(cfg_path),'restore','--bundle',str(source),'--apply','--replace','--apply-settings','--offline','--source-stopped']) == 0
    result = config.load(cfg_path)
    assert result['mode']=='lab' and not any(result['features'].values())


def test_signature_required_pair(populated, cfg_path, tmp_path):
    assert cli.main(['--config',str(cfg_path),'restore','--bundle',str(tmp_path/'none'),'--trust-key',str(tmp_path/'key')]) == 2


def test_signed_recovery_rejects_occupied_state(prod, tmp_path):
    d=Path(prod['data_dir']); (d/'ha/configuration.yaml').write_text('existing')
    key=tmp_path/'public'; key.write_text('fixture')
    a=argparse.Namespace(trust_key=key, media=tmp_path)
    with pytest.raises(ApplianceError, match='empty fresh'): cli.recover(a,prod,tmp_path/'cfg')


def test_unique_lab_project_names(cfg):
    other=copy.deepcopy(cfg)
    other['data_dir'] += '-other'
    assert compose.generate(cfg)['name'] != compose.generate(other)['name']


def test_failed_swap_immediately_restores_original(populated, monkeypatch):
    d=Path(populated['data_dir']); stage=d.parent/'staged'
    config.create_state(stage)
    original=backup.os.replace
    def interrupted(src,dst):
        if Path(src)==stage: raise OSError('injected failure')
        return original(src,dst)
    monkeypatch.setattr(backup.os,'replace',interrupted)
    with pytest.raises(OSError): backup.commit_state(populated,stage)
    assert (d/'ha/configuration.yaml').read_text()=='default_config:\n'
    assert not (Path(populated['work_dir'])/'restore-journal.json').exists()
