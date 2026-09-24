#!/usr/bin/env python3
"""Produce deterministic source archives from an explicit allowlist, never from the worktree wholesale."""
import argparse
import gzip
import hashlib
import importlib.util
import io
from pathlib import Path
import tarfile
import zipfile
from release_manifest import ROOT, candidates

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--output', type=Path, default=ROOT/'dist')
a = p.parse_args()
spec = importlib.util.spec_from_file_location('scan_public', ROOT/'scripts/scan-public.py')
scanner = importlib.util.module_from_spec(spec); spec.loader.exec_module(scanner)
count, problems = scanner.scan()
if problems:
    raise SystemExit('Source scanner blocked packaging: ' + ', '.join(x[0] for x in problems))
version = (ROOT/'VERSION').read_text().strip()
prefix = 'orangepi4pro-homeassistant'
name = prefix + '-v' + version
files = sorted(set(candidates()), key=lambda path: path.relative_to(ROOT).as_posix())
a.output.mkdir(parents=True, exist_ok=True)
zip_path = a.output/(name+'.zip')
tar_path = a.output/(name+'.tar.gz')
for target in (zip_path,tar_path):
    if target.exists():
        raise SystemExit(f'Output already exists: {target}')
def permission(path):
    relative = path.relative_to(ROOT).as_posix()
    return 0o755 if relative.startswith('bin/') or path.suffix in ('.py','.sh') else 0o644
with zipfile.ZipFile(zip_path,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
    for file in files:
        info = zipfile.ZipInfo(prefix+'/'+file.relative_to(ROOT).as_posix(), (2026,9,23,0,0,0))
        info.create_system = 3
        info.external_attr = (0o100000 | permission(file)) << 16
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info,file.read_bytes())
with tar_path.open('wb') as raw:
    with gzip.GzipFile(filename='',mode='wb',fileobj=raw,mtime=0) as compressed:
        with tarfile.open(fileobj=compressed,mode='w') as archive:
            for file in files:
                data=file.read_bytes()
                info=tarfile.TarInfo(prefix+'/'+file.relative_to(ROOT).as_posix())
                info.size=len(data); info.mode=permission(file); info.mtime=0; info.uid=info.gid=0
                archive.addfile(info,io.BytesIO(data))
checksums=[]
for target in (zip_path,tar_path):
    checksums.append(hashlib.sha256(target.read_bytes()).hexdigest()+'  '+target.name)
(a.output/(name+'.SHA256SUMS')).write_text('\n'.join(checksums)+'\n')
print(f'Packaged {len(files)} allowlisted files into {zip_path} and {tar_path}')
