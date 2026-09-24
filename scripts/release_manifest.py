"""Explicit source-release allowlist, shared by scanning and packaging."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIRECTORIES = ('.github', 'bin', 'config', 'docs', 'examples', 'homeassistant', 'image',
               'reports', 'scripts', 'src', 'systemd', 'tests', 'vendor', 'web')
FILES = ('README.md', 'VERSION', 'LICENSE', 'SECURITY.md', 'CONTRIBUTING.md',
         'CHANGELOG.md', '.gitignore', '.gitattributes', 'Makefile', 'pyproject.toml')
EXCLUDED = {'.local', '.build', 'dist', '.venv', '.git', '__pycache__', '.pytest_cache', '.storage'}


def candidates(root: Path = ROOT):
    for name in FILES:
        path = root / name
        if path.is_file():
            yield path
    for name in DIRECTORIES:
        path = root / name
        if not path.is_dir():
            continue
        for file in sorted(path.rglob('*')):
            if set(file.relative_to(root).parts) & EXCLUDED or file.suffix in ('.pyc', '.pyo'):
                continue
            if file.is_file() or file.is_symlink():
                yield file
