from __future__ import annotations

import subprocess
from typing import Callable

from .common import ApplianceError


OPIHA = "/opt/orangepi-homeassistant/current/bin/opiha"
CONFIG = "/etc/orangepi-homeassistant/appliance.json"
WORK = "/var/lib/orangepi-homeassistant"
UNIT = "orangepi-homeassistant.service"

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
}


def dispatch(command: str, runner: Callable = subprocess.run) -> None:
    argv = COMMANDS.get(command)
    if argv is None:
        raise ApplianceError("Allowed commands: " + ", ".join(sorted(COMMANDS)))
    completed = runner(argv)
    if completed.returncode:
        raise ApplianceError(f"Administrative command failed with exit code {completed.returncode}")
