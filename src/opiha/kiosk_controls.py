"""Fixed touch actions for the full-screen kiosk browser, which has no address bar or reload button."""
from __future__ import annotations

import subprocess
from typing import Callable

HOME_URL = "http://127.0.0.1:8123/"
KIOSK_UNIT = "orangepi-homeassistant-kiosk.service"

# Argument vectors only; nothing is evaluated by a shell and nothing is user-supplied.
ACTIONS: dict[str, list[list[str]]] = {
    # Hard reload picks up a new custom panel script as well as new data.
    "reload": [["xdotool", "key", "--clearmodifiers", "ctrl+shift+r"]],
    "home": [
        ["xdotool", "key", "--clearmodifiers", "ctrl+l"],
        ["xdotool", "type", "--delay", "20", HOME_URL],
        ["xdotool", "key", "Return"],
    ],
    # Closing Firefox also lets snapd apply a pending browser update on the next launch.
    "restart": [["systemctl", "--user", "restart", KIOSK_UNIT]],
}
# Silences the snapd "update available" popup that otherwise covers the page header.
QUIET_NOTIFICATIONS = ["xfconf-query", "-c", "xfce4-notifyd", "-p", "/do-not-disturb", "-n", "-t", "bool", "-s", "true"]


def run(action: str, runner: Callable = subprocess.run) -> bool:
    commands = ACTIONS.get(action)
    if commands is None:
        raise ValueError("Unknown kiosk action")
    ok = True
    for argv in commands:
        completed = runner(argv, check=False, timeout=15, capture_output=True)
        ok = ok and completed.returncode == 0
    return ok
