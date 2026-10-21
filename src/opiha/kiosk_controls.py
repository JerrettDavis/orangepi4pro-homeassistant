"""Fixed touch actions for the full-screen kiosk browser, which has no address bar or reload button."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
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


DRAG_THRESHOLD = 12  # pixels of travel before a touch on the handle is a drag rather than a tap


def position_file() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "opiha" / "kiosk-controls-position.json"


def clamp(x: int, y: int, width: int, height: int, screen_w: int, screen_h: int) -> tuple[int, int]:
    """Keep the whole strip on screen."""
    return max(0, min(int(x), max(0, screen_w - width))), max(0, min(int(y), max(0, screen_h - height)))


def strip_x(x: int, collapsed_w: int, width: int, screen_w: int) -> tuple[int, bool]:
    """Window left edge and whether the strip grows leftwards (handle at its right end).

    Grows away from the nearer screen edge, falling back to the other side when that is the only one it fits.
    """
    right = x + collapsed_w / 2 > screen_w / 2
    left_x, right_x = int(x), int(x) + collapsed_w - width
    if right and right_x < 0 <= screen_w - (left_x + width):
        right = False
    elif not right and left_x + width > screen_w and right_x >= 0:
        right = True
    return (right_x if right else left_x), right


def load_position(path: Path | None = None) -> tuple[int, int] | None:
    try:
        data = json.loads((path or position_file()).read_text())
        return int(data["x"]), int(data["y"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save_position(x: int, y: int, path: Path | None = None) -> None:
    target = path or position_file()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"x": int(x), "y": int(y)}))
    except OSError:
        pass  # a position that cannot be remembered must never break the strip
