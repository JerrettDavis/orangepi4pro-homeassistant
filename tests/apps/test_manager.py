import copy
import json
from pathlib import Path
import time
import pytest
from opiha_apps import catalog
from opiha_apps.common import AppError, write_json
from opiha_apps.engine import LABEL, APP_LABEL, Docker
from conftest import execute

@pytest.mark.parametrize('slug',list(catalog.CATALOG))
def test_install_stopped_and_digest_locked(manager,slug):
    result=execute(manager,slug,'install')
    assert result['status']=='succeeded', result
    c=manager.engine.owned(slug)
    assert not c['State']['Running'] and c['HostConfig']['RestartPolicy']['Name']=='no'
    assert '@sha256:' in manager.record(slug)['image']
    assert manager.overview()['changes_homeassistant'] is False

@pytest.mark.parametrize('slug',['nodered','esphome','go2rtc','mosquitto'])
def test_full_nonradio_lifecycle(manager,slug):
    assert execute(manager,slug,'install')['status']=='succeeded'
    assert execute(manager,slug,'start')['status']=='succeeded'
    assert manager.engine.owned(slug)['State']['Running']
    assert execute(manager,slug,'restart')['status']=='succeeded'
    assert execute(manager,slug,'stop')['status']=='succeeded'
    assert execute(manager,slug,'remove')['status']=='succeeded'
    assert manager.engine.owned(slug) is None and (manager.app_dir(slug)/'data').is_dir()
    assert manager.record(slug)['installed'] is False

@pytest.mark.parametrize('opts',[{'image':'evil'}, {'mount':'/'},{'privileged':True},{'version':'latest'},{'version':'--privileged'},{'port':8123},{'port':8098},{'memory_mib':True},{'cpu_shares':2048},{'autostart':'yes'},{'device':'/dev/ttyUSB0'},{'radio_reviewed':True}])
def test_options_fail_closed(opts):
    with pytest.raises(AppError):catalog.options('nodered',opts)

@pytest.mark.parametrize('slug',['../nodered','unknown',None,'nodered;sh'])
def test_unknown_catalog(slug):
    with pytest.raises(AppError):catalog.entry(slug)

def test_plan_never_pulls(manager):
    p=manager.plan('nodered','install');assert not manager.engine.calls and not p['starts_app']
    with pytest.raises(AppError):manager.submit(p['id'],False)

def test_plan_one_use_and_expiry(manager):
    p=manager.plan('nodered','install');manager.plans[p['id']]['expires']=0
    with pytest.raises(AppError):manager.submit(p['id'],True)
    execute(manager,'nodered','install')
    p=manager.plan('nodered','start');manager.submit(p['id'],True)
    with pytest.raises(AppError):manager.submit(p['id'],True)

def test_state_change_after_review_fails(manager):
    execute(manager,'nodered','install');p=manager.plan('nodered','start')
    c=manager.engine.owned('nodered');manager.engine.action(c['Id'],'nodered','start')
    j=manager.submit(p['id'],True)
    while manager.job(j['id'])['status'] in {'running','queued'}:time.sleep(.005)
    assert manager.job(j['id'])['status']=='failed'

@pytest.mark.parametrize('kind',['total','available','disk','arch','limits'])
def test_resource_and_native_gates(manager,kind):
    if kind=='total':manager.test_host['memory_total']=2500*1024**2
    if kind=='available':manager.test_host['memory_available']=100*1024**2
    if kind=='disk':manager.test_host['disk_free']=0
    if kind=='arch':manager.engine.arch='amd64'
    if kind=='limits':manager.engine.memory_limit=False
    with pytest.raises(AppError):manager.plan('nodered','install')

def test_external_service_is_not_taken_over(manager):
    manager.engine.rows['external']={'Id':'external','Name':'/legacy','Config':{'Image':'nodered/node-red:5.0.7','Labels':{}},'State':{'Running':True}}
    with pytest.raises(AppError):manager.plan('nodered','install')
    assert next(a for a in manager.overview()['apps'] if a['id']=='nodered')['state']=='externally_managed'

def test_no_radio_start_without_original_store_and_review(manager):
    execute(manager,'zwave','install')
    with pytest.raises(AppError):manager.plan('zwave','start')

def test_install_autostart_requires_explicit_start(manager):
    opts=catalog.options('nodered',{'autostart':True})
    execute(manager,'nodered','install',opts)
    assert manager.engine.owned('nodered')['HostConfig']['RestartPolicy']['Name']=='no'
    execute(manager,'nodered','start')
    assert manager.engine.owned('nodered')['HostConfig']['RestartPolicy']['Name']=='unless-stopped'

def test_update_preserves_data_and_running_state(manager):
    execute(manager,'nodered','install');execute(manager,'nodered','start')
    f=manager.app_dir('nodered')/'data/flow.json';f.write_text('{"preserved":true}')
    opts=catalog.options('nodered',{'version':'5.0.8'})
    assert execute(manager,'nodered','update',opts)['status']=='succeeded'
    assert f.read_text()=='{"preserved":true}' and manager.engine.owned('nodered')['State']['Running']
    assert list((manager.root/'rollbacks').iterdir())

def test_update_failure_restores_matching_old_state(manager):
    execute(manager,'nodered','install');execute(manager,'nodered','start');old=manager.record('nodered')
    f=manager.app_dir('nodered')/'data/flow.json';f.write_text('preserved')
    manager.engine.fail_create=1
    result=execute(manager,'nodered','update',catalog.options('nodered',{'version':'5.0.8'}))
    assert result['status']=='failed' and manager.record('nodered')==old
    assert f.read_text()=='preserved' and manager.engine.owned('nodered')['State']['Running']
    assert not (manager.app_dir('nodered')/'transaction.json').exists()

def test_first_install_failure_keeps_data_not_orphan(manager):
    manager.engine.fail_create=1
    assert execute(manager,'nodered','install')['status']=='failed'
    assert manager.engine.owned('nodered') is None
    assert not (manager.app_dir('nodered')/'transaction.json').exists()
    assert (manager.app_dir('nodered')/'data/settings.js').exists()

def test_interrupted_transaction_blocks_changes(manager):
    execute(manager,'nodered','install');write_json(manager.app_dir('nodered')/'transaction.json',{'phase':'x'})
    with pytest.raises(AppError):manager.plan('nodered','start')
    assert next(a for a in manager.overview()['apps'] if a['id']=='nodered')['state']=='recovery_required'

def test_restored_reinstall_uses_digest_not_mutable_tag(manager):
    execute(manager,'nodered','install');expected=manager.record('nodered')['image'];execute(manager,'nodered','remove')
    execute(manager,'nodered','install');assert [x for x in manager.engine.calls if x[0]=='pull'][-1][1]==expected

def test_no_live_chown_during_update(manager,monkeypatch):
    execute(manager,'nodered','install');execute(manager,'nodered','start')
    monkeypatch.setattr(manager,'_seed',lambda *_:pytest.fail('Would mutate running data'))
    assert execute(manager,'nodered','update')['status']=='succeeded'

def test_engine_unavailable_not_empty_success(manager):
    manager.engine.offline=True
    o=manager.overview();assert o['engine_error'] and all(a['state']=='engine_unavailable' for a in o['apps'])

def test_same_port_collision(manager):
    execute(manager,'nodered','install')
    with pytest.raises(AppError):manager.plan('esphome','install',catalog.options('esphome',{'port':21880}))

def test_malicious_record_image_rejected(manager):
    execute(manager,'nodered','install');r=manager.record('nodered');r['image']='evil/repo@sha256:'+'a'*64
    write_json(manager.app_dir('nodered')/'record.json',r)
    with pytest.raises(AppError):manager.record('nodered')

def test_mqtt_private_password_not_in_command(manager):
    execute(manager,'mosquitto','install');creds=manager.credentials('mosquitto')
    assert len(creds['password'])>40 and creds['password'] not in repr(manager.engine.calls)
    assert creds['password'] not in (manager.app_dir('mosquitto')/'data/config/passwordfile').read_text()

def test_docker_argv_boundary(manager):
    execute(manager,'nodered','install');calls=[]
    d=Docker(manager.owner,runner=lambda args,timeout:(calls.append(args) or (0,'c'*64)))
    d.create('nodered',manager.spec('nodered',manager.record('nodered')))
    args=calls[0];assert '--privileged' not in args and '/var/run/docker.sock' not in ' '.join(args)
    assert '--cap-drop' in args and '127.0.0.1:21880:1880' in args
    assert '--memory' in args and '--cpu-shares' in args and '--cpus' not in args
    assert not any('homeassistant' in x for x in args)

def test_docker_error_does_not_leak_output():
    d=Docker('x'*32,runner=lambda *_:(1,'SECRET_VALUE'))
    with pytest.raises(AppError) as e:d.command(['info'])
    assert 'SECRET_VALUE' not in str(e.value)

@pytest.mark.parametrize('arch',['amd64','arm'])
def test_docker_pull_rejects_wrong_arch(arch):
    def runner(args,timeout):
        if args[:2]==['image','inspect']:return 0,json.dumps([{'Architecture':arch,'Os':'linux','RepoDigests':['nodered/node-red@sha256:'+'a'*64],'Id':'sha256:'+'b'*64}])
        return 0,''
    with pytest.raises(AppError):Docker('x'*32,runner=runner).pull('nodered/node-red:5.0.7','nodered/node-red','arm64')


def test_port_check_tolerates_a_just_removed_apps_lingering_listener(manager):
    import socket, threading, time
    holder = socket.socket()
    for port in range(25200, 25300):
        try:
            holder.bind(('127.0.0.1', port))
            break
        except OSError:
            continue
    else:
        pytest.skip('no free test port')
    manager.check_port = True
    threading.Timer(1.0, holder.close).start()
    started = time.monotonic()
    plan = manager.plan('nodered', 'install', {'port': port})
    assert plan['action'] == 'install' and time.monotonic() - started >= 0.5


def test_a_finished_job_never_blocks_the_next_submit(manager):
    # Regression: "succeeded" used to be published before the worker was marked free, so an immediate follow-up
    # submit could be refused ("Another app job is already running") under load.
    seen = []
    real = manager._job_stage

    def spy(job_id, stage, **extra):
        if extra.get("status") in {"succeeded", "failed"}:
            seen.append(manager.active)
        return real(job_id, stage, **extra)
    manager._job_stage = spy
    assert execute(manager, 'nodered', 'install')['status'] == 'succeeded'
    assert execute(manager, 'nodered', 'start')['status'] == 'succeeded'
    assert execute(manager, 'nodered', 'stop')['status'] == 'succeeded'
    assert seen and not any(seen)
