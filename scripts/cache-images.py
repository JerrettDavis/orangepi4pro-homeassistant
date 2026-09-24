#!/usr/bin/env python3
"""Build a public ARM64/AMD64 Docker cache, with immutable local aliases and image-ID checks."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from opiha.common import ApplianceError, atomic_json, run, sha256
from opiha.config import load

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--config', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
p.add_argument('--platform', choices=('linux/arm64', 'linux/amd64'), required=True)
a = p.parse_args()
try:
    cfg = load(a.config)
    if a.output.exists() and any(a.output.iterdir()):
        raise ApplianceError('Cache output must be empty')
    a.output.mkdir(parents=True, exist_ok=True)
    entries = {}
    for name, source in cfg['images'].items():
        run(['docker', 'pull', '--platform', a.platform, source])
        metadata = json.loads(run(['docker', 'image', 'inspect', source], capture=True).stdout)[0]
        if metadata['Architecture'] != a.platform.split('/')[-1]:
            raise ApplianceError('Image platform mismatch')
        image_id = metadata['Id']
        tag = f'opiha-cache/{name}:{image_id.split(":")[1]}'
        run(['docker', 'tag', image_id, tag])
        entries[name] = {'source': source, 'cache_ref': tag, 'image_id': image_id,
                         'repo_digests': metadata.get('RepoDigests', [])}
    archive = a.output / 'images.tar'
    run(['docker', 'save', '--output', str(archive), *[e['cache_ref'] for e in entries.values()]])
    atomic_json(a.output / 'manifest.json', {'format': 'opiha-image-cache-v1', 'platform': a.platform,
                'ha_version': cfg['ha_version'], 'sha256': sha256(archive), 'images': entries}, 0o644)
    print('Public container cache prepared. It contains upstream software, not household state.')
except (ApplianceError, OSError, ValueError, KeyError) as e:
    raise SystemExit(f'cache-images: {e}')
