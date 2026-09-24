#!/usr/bin/env python3
"""Load public cached images and use verified local aliases, not ambiguous digest restoration."""
import argparse
import json
from pathlib import Path
import platform
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from opiha.common import ApplianceError, atomic_json, read_json, run, sha256
from opiha.config import load, validate

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--config', type=Path, required=True)
p.add_argument('--cache', type=Path, required=True)
a = p.parse_args()
try:
    cfg = load(a.config)
    m = read_json(a.cache / 'manifest.json')
    architecture = {'aarch64': 'arm64', 'arm64': 'arm64', 'x86_64': 'amd64', 'AMD64': 'amd64'}.get(platform.machine())
    if m.get('format') != 'opiha-image-cache-v1' or m['platform'] != 'linux/' + str(architecture):
        raise ApplianceError('Invalid image cache format/platform')
    if m['ha_version'] != cfg['ha_version']:
        raise ApplianceError('Cache HA version differs from restored state; rebuild the cache for that version')
    if sha256(a.cache / 'images.tar') != m['sha256']:
        raise ApplianceError('Cache archive checksum mismatch')
    if set(m['images']) != set(cfg['images']):
        raise ApplianceError('Cache image set mismatch')
    for name, entry in m['images'].items():
        if cfg['images'][name] not in [entry['source'], entry['cache_ref'], *entry.get('repo_digests', [])]:
            raise ApplianceError(f'Cache does not match the configured {name} version')
    run(['docker', 'load', '--input', str(a.cache / 'images.tar')])
    for name, entry in m['images'].items():
        info = json.loads(run(['docker', 'image', 'inspect', entry['cache_ref']], capture=True).stdout)[0]
        if info['Id'] != entry['image_id'] or info['Architecture'] != architecture:
            raise ApplianceError('Loaded image identity mismatch')
        cfg['images'][name] = entry['cache_ref']
    validate(cfg)
    atomic_json(a.config, cfg)
    print('Loaded and verified public container cache; no registry connection is required for these images.')
except (ApplianceError, OSError, ValueError, KeyError) as e:
    raise SystemExit(f'load-cache: {e}')
