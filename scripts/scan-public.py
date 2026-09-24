#!/usr/bin/env python3
"""Check allowlisted source files for known private artifacts; not a general secret detector."""
import re
from pathlib import Path
from release_manifest import ROOT, candidates

BAD_SUFFIXES = ('.age', '.age.sig', '.img', '.vhdx', '.db', '.db-wal', '.db-shm', '.key')
PATTERNS = (
    re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----\r?\n[A-Za-z0-9+/=]{16,}'),
    re.compile(rb'AGE-SECRET-KEY-1[0-9A-Z]{40,}'),
    re.compile(rb'\bgh[pousr]_[A-Za-z0-9]{32,}\b'),
    re.compile(rb'\bgithub_pat_[A-Za-z0-9_]{40,}\b'),
    re.compile(rb'\bAKIA[0-9A-Z]{16}\b'),
)


def scan(root=ROOT):
    problems = []
    checked = 0
    for path in candidates(root):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            problems.append((relative, 'source symlinks are not permitted'))
            continue
        if path.name in ('identity.txt','appliance.json','secrets.yaml') or relative.endswith(BAD_SUFFIXES):
            problems.append((relative, 'private/generated artifact name'))
        if path.suffix in ('.zip','.tar','.gz'):
            if not (relative == 'vendor/hacs.zip' and (root/'vendor/hacs.lock.json').is_file()):
                problems.append((relative, 'unreviewed binary archive'))
            # Optional HACS archive provenance is handled by its fetch/seed checksum checks.
            continue
        content = path.read_bytes()
        if any(pattern.search(content) for pattern in PATTERNS):
            problems.append((relative, 'possible real credential material'))
        checked += 1
    return checked, problems


if __name__ == '__main__':
    count, issues = scan()
    for filename, reason in issues:
        print(f'BLOCKED: {filename}: {reason}')
    print(f'Checked {count} allowlisted text/source files; {len(issues)} issue(s).')
    print('This is a known-pattern check, not proof that arbitrary personal data is absent.')
    raise SystemExit(1 if issues else 0)
