import subprocess

import pytest

from opiha import admin
from opiha.common import ApplianceError


def test_admin_commands_expand_to_fixed_argument_vectors():
    calls = []
    runner = lambda argv: calls.append(argv) or subprocess.CompletedProcess(argv, 0)

    for command in ("daemon-reload", "start", "stop", "restart", "status", "render", "doctor", "compose-ps", "journal", "kiosk-start", "kiosk-stop", "kiosk-status"):
        admin.dispatch(command, runner=runner)

    assert calls[0] == ["/bin/systemctl", "daemon-reload"]
    assert calls[1] == ["/bin/systemctl", "start", "orangepi-homeassistant.service"]
    assert "orangepi-homeassistant.service" in calls[4]
    assert calls[5][-1] == "render"
    assert calls[6][-1] == "doctor"
    assert calls[7][-1] == "ps"
    assert calls[8][0] == "/bin/journalctl"
    assert calls[9] == ["/bin/systemctl", "start", "orangepi-homeassistant-kiosk@orangepi.service"]
    assert calls[10] == ["/bin/systemctl", "stop", "orangepi-homeassistant-kiosk@orangepi.service"]
    assert "orangepi-homeassistant-kiosk@orangepi.service" in calls[11]


@pytest.mark.parametrize("command", ["", "shell", "../../bin/sh", "start extra", "reboot", "enable"])
def test_admin_rejects_every_unlisted_command(command):
    with pytest.raises(ApplianceError, match="Allowed commands"):
        admin.dispatch(command)


def test_admin_runner_failure_is_reported_without_fallback_shell():
    def failed(argv):
        return subprocess.CompletedProcess(argv, 5)

    with pytest.raises(ApplianceError, match="failed with exit code 5"):
        admin.dispatch("status", runner=failed)
