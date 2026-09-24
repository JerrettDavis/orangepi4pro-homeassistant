import os
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is required")
def test_display_power_hint_failure_does_not_block_firefox(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    calls = tmp_path / "firefox-calls"

    commands = {
        "xset": "#!/bin/sh\n[ \"$*\" = \"s off\" ] && exit 1\nexit 0\n",
        "curl": "#!/bin/sh\nexit 0\n",
        "firefox": f"#!/bin/sh\nprintf '%s\\n' \"$*\" > '{calls}'\n",
    }
    for name, text in commands.items():
        path = fake_bin / name
        path.write_text(text)
        path.chmod(0o755)

    env = os.environ.copy()
    env.update(HOME=str(tmp_path / "home"), PATH=f"{fake_bin}:/usr/bin:/bin")
    result = subprocess.run(
        ["bash", "scripts/kiosk-session.sh"],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "--kiosk http://127.0.0.1:8123/" in calls.read_text()
