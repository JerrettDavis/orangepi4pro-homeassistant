from __future__ import annotations
import copy
from pathlib import Path
import time
import pytest
from opiha_apps.common import AppError, defaults, initialize
from opiha_apps.engine import APP_LABEL, LABEL
from opiha_apps.manager import Manager


class FakeDocker:
    """Explicit test double: no image is pulled and no container is launched."""
    def __init__(self, owner):
        self.owner=owner; self.rows={}; self.calls=[]; self.serial=0; self.fail_create=0
        self.arch="arm64"; self.memory_limit=True; self.offline=False
    def info(self): return {"Architecture":self.arch,"OSType":"linux","MemoryLimit":self.memory_limit}
    def containers(self):
        if self.offline: raise AppError("Fake engine unavailable")
        return copy.deepcopy(list(self.rows.values()))
    def owned(self,slug):
        found=[c for c in self.containers() if c['Config']['Labels'].get(LABEL)==self.owner and c['Config']['Labels'].get(APP_LABEL)==slug]
        if len(found)>1: raise AppError("Duplicate owned app")
        return found[0] if found else None
    def assert_owned(self,identifier,slug):
        row=copy.deepcopy(self.rows[identifier])
        if row['Config']['Labels'].get(LABEL)!=self.owner or row['Config']['Labels'].get(APP_LABEL)!=slug:raise AppError('Wrong owner')
        return row
    def pull(self,ref,repository,architecture):
        self.calls.append(('pull',ref,architecture));return repository+'@sha256:'+'a'*64,'sha256:'+'b'*64
    def ensure_network(self,name):self.calls.append(('network',name))
    def build(self,tag,context,args,arch):
        self.calls.append(('build',tag,context,dict(args),arch));return 'sha256:'+'c'*64
    def create(self,slug,spec):
        self.calls.append(('create',slug,copy.deepcopy(spec)))
        if self.fail_create:self.fail_create-=1;raise AppError('Synthetic create failure')
        self.serial+=1;identifier=f'{self.serial:064x}'
        self.rows[identifier]={'Id':identifier,'Name':'/opiha-apps-'+slug,'Config':{'Image':spec['image'],'Labels':{LABEL:self.owner,APP_LABEL:slug}},'State':{'Running':False,'Status':'created'},'HostConfig':{'PortBindings':{str(c)+'/tcp':[{'HostPort':str(h)}] for h,c in spec['ports']},'RestartPolicy':{'Name':'unless-stopped' if spec['autostart'] else 'no'},'Devices':[]}}
        return identifier
    def action(self,identifier,slug,action):
        self.assert_owned(identifier,slug);self.calls.append((action,slug))
        if action=='remove':del self.rows[identifier]
        elif action=='stop':self.rows[identifier]['State']={'Running':False,'Status':'exited'}
        else:self.rows[identifier]['State']={'Running':True,'Status':'running'}
    def restart_policy(self,identifier,slug,auto):
        self.assert_owned(identifier,slug);self.calls.append(('policy',slug,auto));self.rows[identifier]['HostConfig']['RestartPolicy']['Name']='unless-stopped' if auto else 'no'
    def command(self,args,timeout=30):
        self.calls.append(('command',args))
        mount=args[args.index('--mount')+1]
        source=Path(mount.split('src=',1)[1].split(',',1)[0])
        (source/'passwordfile').write_text('opiha:$7$FAKE_HASH_FOR_TEST_ONLY\n')
        return ''
    def logs(self,identifier,slug):self.assert_owned(identifier,slug);return 'synthetic app output'
    def stats(self,ids):return [{'ID':i,'CPUPerc':'0.00%'} for i in ids]


@pytest.fixture
def manager(tmp_path):
    cfg=defaults();cfg.update(data_dir=str(tmp_path/'state'),token_file=str(tmp_path/'etc/token'),appliance_config=str(tmp_path/'etc/appliance.json'))
    owner=initialize(cfg);engine=FakeDocker(owner)
    host={'memory_total':6*1024**3,'memory_available':5*1024**3,'disk_free':20*1024**3}
    m=Manager(cfg,engine=engine,sampler=lambda _:copy.deepcopy(host),check_port=False);m.test_host=host
    yield m
    m.close()


def wait(m,job):
    deadline=time.monotonic()+5
    while m.job(job['id'])['status'] in {'queued','running'}:
        if time.monotonic()>deadline:raise AssertionError('Synthetic lifecycle timed out')
        time.sleep(.005)
    return m.job(job['id'])


def execute_addon(m,repo,folder,options=None):
    plan=m.plan_addon(repo,folder,options);return wait(m,m.submit(plan['id'],True))


def execute(m,slug,action,options=None):
    plan=m.plan(slug,action,options);job=m.submit(plan['id'],True)
    deadline=time.monotonic()+5
    while m.job(job['id'])['status'] in {'queued','running'}:
        if time.monotonic()>deadline:raise AssertionError('Synthetic lifecycle timed out')
        time.sleep(.005)
    return m.job(job['id'])
