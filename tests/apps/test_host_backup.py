import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import pytest
from opiha_apps.common import AppError, checked_path, defaults, initialize, read_json, read_token, write_json
from opiha_apps.install import install, SOURCE
from opiha_apps.filesystem import copy_tree, inventory
from opiha_apps import backup
from conftest import execute

@pytest.fixture
def host(tmp_path):
    root=tmp_path/'root';(root/'etc').mkdir(parents=True);(root/'etc/os-release').write_text('ID=ubuntu\n')
    ha=root/'srv/homeassistant/ha';ha.mkdir(parents=True);(ha/'configuration.yaml').write_text('default_config:\nhttp:\n  use_x_forwarded_for: true\n  trusted_proxies:\n    - 127.0.0.1\n')
    write_json(root/'etc/orangepi-homeassistant/appliance.json',{'mode':'appliance','data_dir':'/srv/homeassistant'})
    return root

def test_host_preview_no_mutation(host):
    before=sorted(str(p) for p in host.rglob('*'));result=install(root=host)
    assert sorted(str(p) for p in host.rglob('*'))==before and not result['applied']

def test_host_apply_preserves_ha_proxy_and_no_service_start(host):
    original=(host/'srv/homeassistant/ha/configuration.yaml').read_bytes()
    out=install(root=host,apply=True,architecture='arm64')
    assert out['applied'] and not out['starts_services'] and not out['changes_boot']
    current=(host/'srv/homeassistant/ha/configuration.yaml').read_bytes();assert current.startswith(original)
    assert current.count(b'opiha_apps:')==1
    connection=read_json(host/'srv/homeassistant/ha/opiha-apps-connection.json');assert len(connection['token'])>=48
    assert (host/'srv/homeassistant/ha/opiha-apps-connection.json').stat().st_mode&0o777==0o600
    assert not (host/'etc/systemd/system/multi-user.target.wants').exists()
    assert (host/'opt/orangepi-apps/current').is_symlink()
    assert not (host/'etc/systemd/system/orangepi-homeassistant.service').exists()

def test_host_reapply_idempotent(host):
    install(root=host,apply=True,architecture='arm64');first=(host/'srv/homeassistant/ha/opiha-apps-connection.json').read_bytes()
    install(root=host,apply=True,architecture='arm64');assert (host/'srv/homeassistant/ha/opiha-apps-connection.json').read_bytes()==first
    assert (host/'srv/homeassistant/ha/configuration.yaml').read_text().count('opiha_apps:')==1

def test_unowned_component_rejected(host):
    (host/'srv/homeassistant/ha/custom_components/opiha_apps').mkdir(parents=True)
    with pytest.raises(AppError):install(root=host,apply=True)

def test_edited_managed_file_not_overwritten(host):
    install(root=host,apply=True,architecture='arm64')
    unit=host/'etc/systemd/system/orangepi-apps.service';unit.write_text('local change')
    with pytest.raises(AppError):install(root=host,apply=True)
    assert unit.read_text()=='local change'

def test_installer_will_not_convert_lab(host):
    p=host/'etc/orangepi-homeassistant/appliance.json';v=read_json(p);v['mode']='lab';write_json(p,v)
    with pytest.raises(AppError):install(root=host)

@pytest.mark.parametrize('path',['/','/var/lib','relative/path','/srv/x/../y','/srv/a,b'])
def test_managed_path_guards(path):
    with pytest.raises(AppError):checked_path(path,directory=True)

def test_symlink_parent_rejected(tmp_path):
    (tmp_path/'real').mkdir();(tmp_path/'alias').symlink_to(tmp_path/'real')
    with pytest.raises(AppError):checked_path(tmp_path/'alias/file')

def test_internal_symlink_copy_and_escape_rejection(tmp_path):
    root=tmp_path/'data';root.mkdir();(root/'target').write_text('x');(root/'link').symlink_to('target')
    copy_tree(root,tmp_path/'copy');assert (tmp_path/'copy/link').is_symlink()
    (root/'bad').symlink_to('/etc/passwd')
    with pytest.raises(AppError):inventory(root)

def test_native_backup_restore_roundtrip(manager,tmp_path):
    execute(manager,'nodered','install');execute(manager,'nodered','start')
    data=manager.app_dir('nodered')/'data';(data/'a').write_text('private');(data/'link').symlink_to('a')
    output=tmp_path/'backup.tar.gz';result=backup.create(manager,output,plaintext=True)
    assert not result['encrypted'] and not result['includes_homeassistant'] and manager.engine.owned('nodered')['State']['Running']
    dest=tmp_path/'restored';preview=backup.restore(output,dest)
    assert preview['verified'] and not dest.exists()
    result=backup.restore(output,dest,apply=True);assert result['staged'] and not result['started_apps']
    assert (dest/'apps/nodered/data/a').read_text()=='private' and (dest/'apps/nodered/data/link').is_symlink()

def test_empty_manager_backup(manager,tmp_path):
    p=tmp_path/'empty.tar.gz';backup.create(manager,p,plaintext=True)
    assert backup.restore(p,tmp_path/'recovery',apply=True)['verified']

def test_backup_destination_outside_state(manager):
    with pytest.raises(AppError):backup.create(manager,manager.root/'backups/out',plaintext=True)

def test_missing_age_does_not_stop_apps(manager,tmp_path,monkeypatch):
    execute(manager,'nodered','install');execute(manager,'nodered','start')
    monkeypatch.setattr(shutil,'which',lambda _:None)
    with pytest.raises(AppError):backup.create(manager,tmp_path/'out.age',recipient='age1test')
    assert manager.engine.owned('nodered')['State']['Running']

def malicious_archive(path,names,*,manifest_path=None,link=None):
    rows=[]
    for name in names:
        rows.append({'path':name,'type':'file','size':1,'sha256':hashlib.sha256(b'x').hexdigest(),'mode':0o600})
    if link:rows.append({'path':link[0],'type':'link','target':link[1]})
    with tarfile.open(path,'w:gz') as t:
        content=json.dumps({'format':'opiha-native-apps-v1','files':rows}).encode();i=tarfile.TarInfo('manifest.json');i.size=len(content);t.addfile(i,io.BytesIO(content))
        for name in names:
            i=tarfile.TarInfo(name);i.size=1;t.addfile(i,io.BytesIO(b'x'))
        if link:
            i=tarfile.TarInfo(link[0]);i.type=tarfile.SYMTYPE;i.linkname=link[1];t.addfile(i)

@pytest.mark.parametrize('name',['../bad','/etc/passwd','apps/../../escape','apps/x/./a','elsewhere','apps\\x','apps//x'])
def test_archive_traversal_rejected(tmp_path,name):
    p=tmp_path/'bad.tar.gz';malicious_archive(p,[name])
    with pytest.raises(AppError):backup.extract(p,tmp_path/'target')
    assert not (tmp_path/'target').exists()

def test_archive_duplicate_rejected(tmp_path):
    p=tmp_path/'bad.tar.gz';malicious_archive(p,['apps/a','apps/a'])
    with pytest.raises(AppError):backup.extract(p,tmp_path/'target')

def test_archive_symlink_escape_rejected(tmp_path):
    p=tmp_path/'bad.tar.gz';malicious_archive(p,[],link=('apps/x/link','../../../../etc'))
    with pytest.raises(AppError):backup.extract(p,tmp_path/'target')

def test_recovery_never_overwrites_existing(manager,tmp_path):
    p=tmp_path/'backup.tar.gz';backup.create(manager,p,plaintext=True);target=tmp_path/'existing';target.mkdir();(target/'important').write_text('keep')
    with pytest.raises(AppError):backup.restore(p,target,apply=True)
    assert (target/'important').read_text()=='keep'

def test_real_ed25519_signature_and_tamper(tmp_path):
    if not shutil.which('openssl'):pytest.skip('openssl not installed')
    private=tmp_path/'private.pem';public=tmp_path/'public.pem';bundle=tmp_path/'bundle';sig=tmp_path/'sig'
    subprocess.run(['openssl','genpkey','-algorithm','ED25519','-out',str(private)],check=True,capture_output=True)
    subprocess.run(['openssl','pkey','-in',str(private),'-pubout','-out',str(public)],check=True,capture_output=True)
    bundle.write_bytes(b'non-secret synthetic bundle');backup.sign(bundle,private,sig);backup.verify(bundle,sig,public)
    bundle.write_bytes(b'changed')
    with pytest.raises(AppError):backup.verify(bundle,sig,public)

def test_real_age_roundtrip(manager,tmp_path):
    if not shutil.which('age') or not shutil.which('age-keygen'):pytest.skip('age and age-keygen are not installed; encrypted roundtrip not executed')
    identity=tmp_path/'identity';subprocess.run(['age-keygen','-o',str(identity)],check=True,capture_output=True)
    recipient=subprocess.check_output(['age-keygen','-y',str(identity)],text=True).strip()
    p=tmp_path/'bundle.age';backup.create(manager,p,recipient=recipient)
    assert backup.restore(p,tmp_path/'restored',identity=identity,apply=True)['staged']
