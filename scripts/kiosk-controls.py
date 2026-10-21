#!/usr/bin/env python3
"""Small always-on-top touch strip (Reload / Home / Restart browser) for the kiosk."""
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("DISPLAY", ":0")

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import GLib, Gdk, Gtk  # noqa: E402

from opiha import kiosk_controls  # noqa: E402

CSS = b"""
window { background: rgba(20,20,20,0.92); border-radius: 10px; }
button { min-width: 92px; min-height: 56px; font-size: 15px; color: #f0f0f0;
         background: #2c2c2c; border: 1px solid #555; border-radius: 8px; }
button.handle { min-width: 52px; min-height: 52px; font-size: 22px; }
"""


class Strip(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.POPUP)
        self.set_keep_above(True)
        self.set_accept_focus(False)  # never steal focus from the browser
        self.set_focus_on_map(False)
        self.set_skip_taskbar_hint(True)
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.box = Gtk.Box(spacing=6, margin=4)
        self.add(self.box)
        self.handle = Gtk.Button(label="⋮")
        self.handle.get_style_context().add_class("handle")
        self.handle.connect("clicked", lambda *_: self.toggle())
        self.box.pack_start(self.handle, False, False, 0)
        self.actions = []
        for label, action in (("Reload", "reload"), ("Home", "home"), ("Restart\nbrowser", "restart")):
            button = Gtk.Button(label=label)
            button.connect("clicked", self.on_action, action)
            self.actions.append(button)
            self.box.pack_start(button, False, False, 0)
        self.timer = None
        self.show_all()
        self.collapse()

    def place(self):
        _, h = self.get_size()
        screen = self.get_screen()
        w, _ = self.get_size()
        # Bottom centre: clear of the sidebar profile entry and the on-screen keyboard button.
        self.move((screen.get_width() - w) // 2, screen.get_height() - h - 8)

    def collapse(self):
        for b in self.actions:
            b.hide()
        self.resize(1, 1)
        GLib.idle_add(self.place)

    def expand(self):
        for b in self.actions:
            b.show()
        self.resize(1, 1)
        GLib.idle_add(self.place)
        self.timer = GLib.timeout_add_seconds(8, self.auto_collapse)

    def auto_collapse(self):
        self.timer = None
        self.collapse()
        return False

    def toggle(self):
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = None
        if self.actions[0].get_visible():
            self.collapse()
        else:
            self.expand()

    def on_action(self, _button, action):
        self.collapse()
        GLib.timeout_add(150, lambda: (kiosk_controls.run(action), False)[1])


def main():
    subprocess.run(kiosk_controls.QUIET_NOTIFICATIONS, check=False, capture_output=True, timeout=10)
    Strip()
    Gtk.main()


if __name__ == "__main__":
    main()
