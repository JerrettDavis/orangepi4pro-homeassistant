import subprocess

import pytest

from opiha import kiosk_controls


def recorder(code=0):
    calls = []

    def runner(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, code)

    return calls, runner


def test_actions_are_fixed_argument_vectors_without_a_shell():
    for argv_list in kiosk_controls.ACTIONS.values():
        for argv in argv_list:
            assert isinstance(argv, list) and argv[0] in {"xdotool", "systemctl"}
            assert not any(part in {"sh", "-c", "bash"} for part in argv)


def test_reload_home_and_restart_commands():
    calls, runner = recorder()
    assert kiosk_controls.run("reload", runner) and calls[-1] == ["xdotool", "key", "--clearmodifiers", "ctrl+shift+r"]
    assert kiosk_controls.run("home", runner) and ["xdotool", "type", "--delay", "20", "http://127.0.0.1:8123/"] in calls
    assert kiosk_controls.run("restart", runner)
    assert calls[-1] == ["systemctl", "--user", "restart", "orangepi-homeassistant-kiosk.service"]


def test_failure_is_reported_and_unknown_actions_rejected():
    _, runner = recorder(1)
    assert kiosk_controls.run("reload", runner) is False
    with pytest.raises(ValueError):
        kiosk_controls.run("reboot", runner)


def test_clamp_keeps_strip_on_screen():
    assert kiosk_controls.clamp(-50, 9999, 300, 60, 1024, 600) == (0, 540)
    assert kiosk_controls.clamp(900, 10, 300, 60, 1024, 600) == (724, 10)
    assert kiosk_controls.clamp(5, 5, 2000, 700, 1024, 600) == (0, 0)


def test_position_round_trip_and_bad_files(tmp_path):
    f = tmp_path / "sub" / "pos.json"
    assert kiosk_controls.load_position(f) is None
    kiosk_controls.save_position(12, 34, f)
    assert kiosk_controls.load_position(f) == (12, 34)
    f.write_text("not json")
    assert kiosk_controls.load_position(f) is None
    kiosk_controls.save_position(1, 2, tmp_path / "pos.json" / "x")  # unwritable: must not raise
