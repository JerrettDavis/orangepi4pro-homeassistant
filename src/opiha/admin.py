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
    "kiosk-daemon-reload": KIOSK_SYSTEMCTL + ["daemon-reload"],
    "kiosk-start": KIOSK_SYSTEMCTL + ["start", KIOSK_UNIT],
    "kiosk-stop": KIOSK_SYSTEMCTL + ["stop", KIOSK_UNIT],
    "kiosk-status": KIOSK_SYSTEMCTL + ["status", KIOSK_UNIT, "--no-pager"],
    "kiosk-journal": [
        "/bin/journalctl", f"_SYSTEMD_USER_UNIT={KIOSK_UNIT}",
        "--since", "-30 minutes", "--no-pager", "-n", "300",
    ],
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
