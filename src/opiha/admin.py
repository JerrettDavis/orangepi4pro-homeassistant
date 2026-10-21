from __future__ import annotations

import subprocess
from typing import Callable

from .common import ApplianceError


OPIHA = "/opt/orangepi-homeassistant/current/bin/opiha"
CONFIG = "/etc/orangepi-homeassistant/appliance.json"
WORK = "/var/lib/orangepi-homeassistant"
UNIT = "orangepi-homeassistant.service"
KIOSK_UNIT = "orangepi-homeassistant-kiosk.service"
KEYBOARD_UNIT = "orangepi-homeassistant-keyboard.service"
CONTROLS_UNIT = "orangepi-homeassistant-kiosk-controls.service"
APPS_UNIT = "orangepi-apps.service"
APPS_CLI = "/opt/orangepi-apps/current/bin/opiha-apps"
APPS_CONFIG = "/etc/orangepi-apps/config.json"
KIOSK_SYSTEMCTL = ["/bin/systemctl", "--user", "--machine=orangepi@.host"]

COMMANDS = {
    "daemon-reload": ["/bin/systemctl", "daemon-reload"],
    "start": ["/bin/systemctl", "start", UNIT],
    "stop": ["/bin/systemctl", "stop", UNIT],
    "restart": ["/bin/systemctl", "restart", UNIT],
    "status": ["/bin/systemctl", "status", UNIT, "--no-pager"],
    "render": [OPIHA, "--config", CONFIG, "render"],
    "doctor": [OPIHA, "--config", CONFIG, "doctor"],
    "compose-ps": [
        "/usr/bin/docker", "compose", "--env-file", f"{WORK}/empty.env",
        "--project-directory", WORK, "-p", "opiha", "-f", f"{WORK}/compose.json", "ps",
    ],
    "journal": [
        "/bin/journalctl", "-u", UNIT, "--since", "-30 minutes", "--no-pager", "-n", "300",
    ],
    "apps-start": ["/bin/systemctl", "start", APPS_UNIT],
    "apps-stop": ["/bin/systemctl", "stop", APPS_UNIT],
    "apps-restart": ["/bin/systemctl", "restart", APPS_UNIT],
    "apps-status": ["/bin/systemctl", "status", APPS_UNIT, "--no-pager"],
    "apps-doctor": ["/usr/bin/python3", APPS_CLI, "--config", APPS_CONFIG, "doctor"],
    "apps-journal": ["/bin/journalctl", "-u", APPS_UNIT, "--since", "-30 minutes", "--no-pager", "-n", "300"],
    "kiosk-daemon-reload": KIOSK_SYSTEMCTL + ["daemon-reload"],
    "kiosk-start": KIOSK_SYSTEMCTL + ["start", KIOSK_UNIT],
    "kiosk-stop": KIOSK_SYSTEMCTL + ["stop", KIOSK_UNIT],
    "kiosk-status": KIOSK_SYSTEMCTL + ["status", KIOSK_UNIT, "--no-pager"],
    "kiosk-journal": [
        "/bin/journalctl", f"_SYSTEMD_USER_UNIT={KIOSK_UNIT}",
        "--since", "-30 minutes", "--no-pager", "-n", "300",
    ],
    "controls-start": KIOSK_SYSTEMCTL + ["start", CONTROLS_UNIT],
    "controls-stop": KIOSK_SYSTEMCTL + ["stop", CONTROLS_UNIT],
    "controls-restart": KIOSK_SYSTEMCTL + ["restart", CONTROLS_UNIT],
    "controls-status": KIOSK_SYSTEMCTL + ["status", CONTROLS_UNIT, "--no-pager"],
    "keyboard-start": KIOSK_SYSTEMCTL + ["start", KEYBOARD_UNIT],
    "keyboard-stop": KIOSK_SYSTEMCTL + ["stop", KEYBOARD_UNIT],
    "keyboard-restart": KIOSK_SYSTEMCTL + ["restart", KEYBOARD_UNIT],
    "keyboard-status": KIOSK_SYSTEMCTL + ["status", KEYBOARD_UNIT, "--no-pager"],
    "keyboard-journal": [
        "/bin/journalctl", f"_SYSTEMD_USER_UNIT={KEYBOARD_UNIT}",
        "--since", "-30 minutes", "--no-pager", "-n", "300",
    ],
}


def dispatch(command: str, runner: Callable = subprocess.run) -> None:
    argv = COMMANDS.get(command)
    if argv is None:
        raise ApplianceError("Allowed commands: " + ", ".join(sorted(COMMANDS)))
    completed = runner(argv)
    if completed.returncode:
        raise ApplianceError(f"Administrative command failed with exit code {completed.returncode}")
