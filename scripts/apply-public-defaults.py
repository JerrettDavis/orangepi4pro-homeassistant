#!/usr/bin/env python3
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from opiha.config import load, validate
from opiha.common import atomic_json
cfg_path, defaults_path = map(Path, sys.argv[1:])
cfg = load(cfg_path)
if defaults_path.exists():
    defaults = json.loads(defaults_path.read_text())
    allowed = {"ha_version", "images", "timezone", "dashboard_path"}
    if set(defaults) - allowed:
        raise SystemExit("Public defaults contain unsupported or private fields")
    cfg.update(defaults)
    validate(cfg)
    atomic_json(cfg_path, cfg)
