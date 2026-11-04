#!/usr/bin/env python3
"""Entry point for the Paseo fleet tooling. See docs/PASEO-FLEET.md."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from paseo_fleet.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
