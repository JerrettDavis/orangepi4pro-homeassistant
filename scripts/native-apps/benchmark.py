#!/usr/bin/env python3
"""Read-only before/after sampler. Does not generate load or change HA/app configuration."""
from pathlib import Path
import argparse
import json
import math
import os
import statistics
import sys
import time
from urllib.parse import urlsplit
from urllib.request import Request,urlopen
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'src'))
from opiha_apps.resources import sample

def cpu():
    fields=[int(x) for x in Path('/proc/stat').read_text().splitlines()[0].split()[1:]]
    # guest/guest_nice are already counted in user/nice; do not double count them.
    return sum(fields[:8]),fields[3]+fields[4]

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--seconds',type=int,default=60);p.add_argument('--ha-url',default='http://127.0.0.1:8123/');p.add_argument('--output',type=Path,required=True);p.add_argument('--label',default='baseline');a=p.parse_args()
    if not 4<=a.seconds<=600:p.error('--seconds must be between 4 and 600')
    u=urlsplit(a.ha_url)
    if u.scheme not in {'http','https'} or u.username or u.password or u.query or u.fragment:p.error('Use a credential-free HTTP(S) URL, no tokens in the address')
    if a.output.exists():p.error('Output already exists')
    samples=[];end=time.monotonic()+a.seconds;previous=cpu()
    while time.monotonic()<end:
        row=sample(Path('/'));current=cpu();delta=current[0]-previous[0];row['cpu_busy_percent']=100*(1-(current[1]-previous[1])/delta) if delta else None;previous=current
        started=time.perf_counter()
        try:
            with urlopen(Request(a.ha_url,headers={'User-Agent':'opiha-readonly-benchmark/1'}),timeout=5) as response:
                row['ha_http_status']=response.status;response.read(256)
            row['ha_response_ms']=(time.perf_counter()-started)*1000
        except Exception:row['ha_error']='HTTP request failed (no private URL/details recorded)'
        samples.append(row);time.sleep(min(2,max(0,end-time.monotonic())))
    times=sorted(s['ha_response_ms'] for s in samples if 'ha_response_ms' in s)
    result={'label':a.label,'scope':'Observed HTTP responsiveness and host counters, not end-to-end automation latency','samples':samples,
            'summary':{'ha_successful_samples':len(times),'ha_failed_samples':len(samples)-len(times),'ha_median_ms':statistics.median(times) if times else None,'ha_p95_ms':times[max(0,math.ceil(.95*len(times))-1)] if times else None,'min_available_memory':min((s['memory_available'] for s in samples if s['memory_available'] is not None),default=None)}}
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,indent=2)+'\n');os.chmod(a.output,0o600);print(json.dumps(result['summary'],indent=2))
if __name__=='__main__':main()
