import os
from pathlib import Path
import shutil
import subprocess

import pytest


REPO = Path(__file__).resolve().parents[1]


def bash_path(path: Path) -> str:
    value = str(path)
    if os.name == "nt":
        drive, rest = os.path.splitdrive(value)
        return f"/{drive[0].lower()}{rest.replace(os.sep, '/')}"
    return value


@pytest.mark.skipif(os.name != "posix", reason="POSIX executable semantics are required")
def test_keyboard_session_enables_focus_show_and_starts_hidden(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    calls = tmp_path / "calls"
    gsettings = fake_bin / "gsettings"
    gsettings.write_text(
        f"#!/bin/sh\nprintf 'gsettings %s\\n' \"$*\" >> '{bash_path(calls)}'\n"
    )
    onboard = fake_bin / "onboard"
    onboard.write_text(
        f"#!/bin/sh\nprintf 'onboard %s\\n' \"$*\" >> '{bash_path(calls)}'\n"
    )
    gsettings.chmod(0o755)
    onboard.chmod(0o755)

    env = os.environ.copy()
    env.update(
        GSETTINGS_COMMAND=bash_path(gsettings),
        ONBOARD_COMMAND=bash_path(onboard),
    )
    result = subprocess.run(
        ["bash", "scripts/keyboard-session.sh"],
        cwd=REPO,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    recorded = calls.read_text()
    assert "gsettings set org.onboard.auto-show enabled true" in recorded
    assert "gsettings set org.onboard start-minimized true" in recorded
    assert "gsettings set org.onboard.icon-palette in-use true" in recorded
    assert "gsettings set org.onboard.window docking-enabled false" in recorded
    assert "gsettings set org.onboard.window force-to-top true" in recorded
    assert "gsettings set org.onboard.window.landscape x 0" in recorded
    assert "gsettings set org.onboard.window.landscape y 395" in recorded
    assert "gsettings set org.onboard.window.landscape width 1024" in recorded
    assert "onboard --not-show-in=" in recorded


@pytest.mark.skipif(os.name != "posix", reason="POSIX executable semantics are required")
def test_keyboard_toggle_calls_onboard_session_interface(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    calls = tmp_path / "calls"
    dbus_send = fake_bin / "dbus-send"
    dbus_send.write_text(
        f"#!/bin/sh\nprintf '%s\\n' \"$*\" > '{bash_path(calls)}'\n"
    )
    dbus_send.chmod(0o755)

    env = os.environ.copy()
    env.update(DBUS_SEND_COMMAND=bash_path(dbus_send))
    result = subprocess.run(
        ["bash", "scripts/keyboard-toggle.sh"],
        cwd=REPO,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert calls.read_text().strip() == (
        "--session --type=method_call --dest=org.onboard.Onboard "
        "/org/onboard/Onboard/Keyboard org.onboard.Onboard.Keyboard.ToggleVisible"
    )
