import subprocess

import pytest

from opiha import admin
from opiha.common import ApplianceError


def test_admin_commands_expand_to_fixed_argument_vectors():
    calls = []
    runner = lambda argv: calls.append(argv) or subprocess.CompletedProcess(argv, 0)

    for command in ("daemon-reload", "start", "stop", "restart", "status", "render", "doctor", "compose-ps", "journal", "kiosk-daemon-reload", "kiosk-start", "kiosk-stop", "kiosk-status", "kiosk-journal", "keyboard-start", "keyboard-stop", "keyboard-restart", "keyboard-status", "keyboard-journal"):
        admin.dispatch(command, runner=runner)

    assert calls[0] == ["/bin/systemctl", "daemon-reload"]
    assert calls[1] == ["/bin/systemctl", "start", "orangepi-homeassistant.service"]
    assert "orangepi-homeassistant.service" in calls[4]
    assert calls[5][-1] == "render"
    assert calls[6][-1] == "doctor"
    assert calls[7][-1] == "ps"
    assert calls[8][0] == "/bin/journalctl"
    kiosk_control = ["/bin/systemctl", "--user", "--machine=orangepi@.host"]
    assert calls[9] == kiosk_control + ["daemon-reload"]
    assert calls[10] == kiosk_control + ["start", "orangepi-homeassistant-kiosk.service"]
    assert calls[11] == kiosk_control + ["stop", "orangepi-homeassistant-kiosk.service"]
    assert calls[12] == kiosk_control + ["status", "orangepi-homeassistant-kiosk.service", "--no-pager"]
    assert calls[13] == [
        "/bin/journalctl",
        "_SYSTEMD_USER_UNIT=orangepi-homeassistant-kiosk.service",
        "--since",
        "-30 minutes",
        "--no-pager",
        "-n",
        "300",
    ]
    assert calls[14] == kiosk_control + ["start", "orangepi-homeassistant-keyboard.service"]
    assert calls[15] == kiosk_control + ["stop", "orangepi-homeassistant-keyboard.service"]
    assert calls[16] == kiosk_control + ["restart", "orangepi-homeassistant-keyboard.service"]
    assert calls[17] == kiosk_control + ["status", "orangepi-homeassistant-keyboard.service", "--no-pager"]
    assert calls[18][0] == "/bin/journalctl"


@pytest.mark.parametrize("command", ["", "shell", "../../bin/sh", "start extra", "reboot", "enable"])
def test_admin_rejects_every_unlisted_command(command):
    with pytest.raises(ApplianceError, match="Allowed commands"):
        admin.dispatch(command)


def test_admin_runner_failure_is_reported_without_fallback_shell():
    def failed(argv):
        return subprocess.CompletedProcess(argv, 5)

    with pytest.raises(ApplianceError, match="failed with exit code 5"):
        admin.dispatch("status", runner=failed)


def test_native_app_manager_commands_are_fixed_and_cannot_touch_ha_or_apps():
    calls = []
    runner = lambda argv: calls.append(argv) or subprocess.CompletedProcess(argv, 0)
    for command in ("apps-start", "apps-stop", "apps-restart", "apps-status", "apps-doctor", "apps-journal"):
        admin.dispatch(command, runner=runner)
    assert all(call[0] in {"/bin/systemctl", "/usr/bin/python3", "/bin/journalctl"} for call in calls)
    assert calls[0] == ["/bin/systemctl", "start", "orangepi-apps.service"]
    assert calls[4][-1] == "doctor" and calls[4][2] == "--config"
    assert all("orangepi-homeassistant.service" not in call for call in calls)
    for rejected in ("apps-install", "apps", "apps-start nodered"):
        with pytest.raises(ApplianceError):
            admin.dispatch(rejected, runner=runner)
