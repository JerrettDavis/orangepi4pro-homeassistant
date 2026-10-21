import os
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(os.name != "posix", reason="POSIX executable semantics are required")
def test_kiosk_sets_two_minute_dpms_off_timeout(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    xset_calls = tmp_path / "xset-calls"

    commands = {
        "xset": f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> '{xset_calls}'\n",
        "curl": "#!/bin/sh\nexit 0\n",
        "firefox": "#!/bin/sh\nexit 0\n",
    }
    for name, content in commands.items():
        path = fake_bin / name
        path.write_text(content)
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
    assert [call for call in xset_calls.read_text().splitlines() if call != "q"] == [
        "s off",
        "+dpms",
        "dpms 0 0 120",
    ]


@pytest.mark.parametrize(
    ("failing_command", "diagnostic"),
    [
        ("s off", "screen-saver disable hint"),
        ("+dpms", "DPMS enable hint"),
        ("dpms 0 0 120", "DPMS timeout hint"),
    ],
)
@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is required")
def test_display_power_hint_failure_does_not_block_firefox(tmp_path, failing_command, diagnostic):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    calls = tmp_path / "firefox-calls"

    commands = {
        "xset": f"#!/bin/sh\n[ \"$*\" = \"{failing_command}\" ] && exit 1\nexit 0\n",
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
    assert diagnostic in result.stderr


@pytest.mark.skipif(os.name != "posix", reason="POSIX executable semantics are required")
def test_firefox_receives_xinput2_for_native_touch_scrolling(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    firefox_environment = tmp_path / "firefox-environment"

    commands = {
        "xset": "#!/bin/sh\nexit 0\n",
        "curl": "#!/bin/sh\nexit 0\n",
        "firefox": (
            "#!/bin/sh\n"
            f"printf '%s\\n' \"${{MOZ_USE_XINPUT2-unset}}\" > '{firefox_environment}'\n"
        ),
    }
    for name, text in commands.items():
        path = fake_bin / name
        path.write_text(text)
        path.chmod(0o755)

    env = os.environ.copy()
    env.pop("MOZ_USE_XINPUT2", None)
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
    assert firefox_environment.read_text() == "1\n"
