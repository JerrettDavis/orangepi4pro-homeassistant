#!/usr/bin/env python3
"""OPT-IN real native Docker smoke test, for a private test machine with no existing app network."""
from pathlib import Path
import argparse
import json
import platform
import sys
import tempfile
import time
from urllib.request import urlopen
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'src'))
from opiha_apps.common import defaults,write_json,AppError
from opiha_apps.manager import Manager
from opiha_apps.catalog import PREFIX

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--app',choices=['nodered','go2rtc','esphome'],default='nodered');p.add_argument('--apply',action='store_true');p.add_argument('--confirm-network-access',action='store_true');a=p.parse_args()
    if not a.apply:print('Preview: pull, create, start, HTTP-probe and remove one blank native app. No HA state or hardware. Requires --apply --confirm-network-access.');return 0
    if not a.confirm_network_access:p.error('Acknowledge that the blank app can reach the network')
    workspace=Path(tempfile.mkdtemp(prefix='opiha-native-smoke-'))
    cfg=defaults();cfg.update(data_dir=str(workspace/'state'),token_file=str(workspace/'token'),architecture={'aarch64':'arm64','x86_64':'amd64'}.get(platform.machine(),'unsupported'))
    write_json(workspace/'config.json',cfg);manager=Manager(cfg)
    def do(action):
        plan=manager.plan(a.app,action);job=manager.submit(plan['id'],True)
        while manager.job(job['id'])['status'] in {'queued','running'}:time.sleep(.2)
        row=manager.job(job['id'])
        if row['status']!='succeeded':raise AppError(row['stage'])
    try:
        do('install');do('start');port=manager.record(a.app)['options']['port'];path='/' if a.app=='esphome' else PREFIX+a.app+'/'
        last=None
        for _ in range(60):
            try:
                with urlopen(f'http://127.0.0.1:{port}{path}',timeout=3) as response:
                    if response.status==200:print('Real app HTTP startup passed');return 0
            except Exception as exc:last=exc
            time.sleep(2)
        raise AppError('App did not return HTTP 200 within the smoke-test window')
    finally:
        row=manager.engine.owned(a.app)
        if row:
            if row['State'].get('Running'):do('stop')
            do('remove')
        manager.close()
        print('Private test state retained at '+str(workspace)+'; no image/network pruning performed.')
if __name__=='__main__':raise SystemExit(main())
