#!/usr/bin/env python3
"""Root-only: publish settings needed by unprivileged status/vision/kiosk services."""
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from opiha.config import load
from opiha.common import atomic_json
from opiha.cli import fix_runtime_permissions
cfg = load(Path(sys.argv[1]))
fix_runtime_permissions(cfg)
os.chmod(cfg["data_dir"], 0o711)
# cfg contains paths/settings, never network keys, HA tokens or broker passwords.
atomic_json(Path("/run/opiha/runtime.json"), cfg, 0o644)
