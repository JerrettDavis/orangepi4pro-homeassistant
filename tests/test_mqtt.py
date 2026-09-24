from pathlib import Path
from types import SimpleNamespace
from opiha import cli


def test_mqtt_uses_private_staging_and_never_passes_password(cfg, monkeypatch):
    seen = []
    monkeypatch.setattr(cli.shutil, 'which', lambda name: '/usr/bin/mosquitto_passwd')
    def fake_run(args, **kwargs):
        assert args[:2] == ['mosquitto_passwd', '-U']
        stage = Path(args[2])
        raw = stage.read_text()
        user, password = raw.strip().split(':', 1)
        assert all(password not in a for a in args)
        seen.append(password)
        stage.write_text(user + ':$7$SIMULATED_HASH\n')
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(cli, 'run', fake_run)
    monkeypatch.setattr(cli, 'fix_runtime_permissions', lambda cfg: None)
    cli.mqtt_init(cfg, 'testuser')
    d = Path(cfg['data_dir'])
    assert seen and seen[0] not in (d/'mqtt/config/passwordfile').read_text()
    assert seen[0] in (d/'private/mqtt-account.json').read_text()
    assert not list((d/'private').glob('.mqtt-*'))


def test_mqtt_container_fallback_has_no_network(cfg, monkeypatch):
    monkeypatch.setattr(cli.shutil, 'which', lambda name: None)
    def fake_run(args, **kwargs):
        assert args[:5] == ['docker','run','--rm','--network','none']
        mount = args[args.index('--mount') + 1]
        directory = Path(mount.split('source=')[1].split(',target=')[0])
        (directory/'passwordfile').write_text('opiha:$7$SIMULATED_HASH\n')
    monkeypatch.setattr(cli, 'run', fake_run)
    monkeypatch.setattr(cli, 'fix_runtime_permissions', lambda cfg: None)
    cli.mqtt_init(cfg, 'opiha')
