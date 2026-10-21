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
window { background: #111111; border: 1px solid #3a3f45; border-radius: 10px; }
button { min-width: 92px; min-height: 56px; padding: 0 8px; font-size: 15px; color: #e1e1e1;
         background: #262a2e; background-image: none; border: 1px solid #3a3f45; border-radius: 8px;
         box-shadow: none; text-shadow: none; }
button:hover { background: #2e3136; }
button:active { background: #03a9f4; color: #ffffff; border-color: #03a9f4; }
button.handle { min-width: 22px; padding: 0 4px; font-size: 20px; color: #03a9f4; }
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
        # Tap toggles; dragging the handle moves the strip and the spot is remembered.
        self.handle.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK | Gdk.EventMask.POINTER_MOTION_MASK)
        self.handle.connect("button-press-event", self.on_press)
        self.handle.connect("motion-notify-event", self.on_motion)
        self.handle.connect("button-release-event", self.on_release)
        self.drag = None
        self.pos = kiosk_controls.load_position()
        self.box.pack_start(self.handle, False, False, 0)
        self.actions = []
        for label, action in (("Reload", "reload"), ("Home", "home"), ("Restart", "restart")):
            button = Gtk.Button(label=label)
            button.connect("clicked", self.on_action, action)
            self.actions.append(button)
            self.box.pack_start(button, False, False, 0)
        self.timer = None
        self.show_all()
        self.collapse()

    def place(self):
        w, h = self.get_preferred_size()[1].width, self.get_preferred_size()[1].height
        screen = self.get_screen()
        cw = self.collapsed_width()
        if self.pos is None:
            # Bottom centre: clear of the sidebar profile entry and the on-screen keyboard button.
            self.pos = ((screen.get_width() - cw) // 2, screen.get_height() - h - 8)
        x, right = kiosk_controls.strip_x(self.pos[0], cw, w, screen.get_width())
        # Keep the handle under the finger: it sits at the end the strip grows away from.
        self.box.reorder_child(self.handle, -1 if right else 0)
        # Clamp only for display so a strip that expanded near an edge returns to its saved spot.
        self.move(*kiosk_controls.clamp(x, self.pos[1], w, h, screen.get_width(), screen.get_height()))

    def collapsed_width(self):
        return self.handle.get_preferred_width()[1] + 2 * self.box.get_margin_start()

    def on_press(self, _widget, event):
        self.drag = {"rx": event.x_root, "ry": event.y_root, "start": self.pos or self.get_position(), "moved": False}
        return True

    def on_motion(self, _widget, event):
        d = self.drag
        if not d:
            return False
        dx, dy = event.x_root - d["rx"], event.y_root - d["ry"]
        if not d["moved"] and max(abs(dx), abs(dy)) < kiosk_controls.DRAG_THRESHOLD:
            return True
        if not d["moved"]:
            d["moved"] = True
            if self.timer:
                GLib.source_remove(self.timer)
                self.timer = None
        w, h = self.collapsed_width(), self.get_preferred_size()[1].height
        screen = self.get_screen()
        self.pos = kiosk_controls.clamp(d["start"][0] + dx, d["start"][1] + dy, w, h, screen.get_width(), screen.get_height())
        self.place()
        return True

    def on_release(self, _widget, _event):
        d, self.drag = self.drag, None
        if d and d["moved"]:
            kiosk_controls.save_position(*self.pos)
            if self.actions[0].get_visible():
                self.timer = GLib.timeout_add_seconds(8, self.auto_collapse)
        elif d:
            self.toggle()
        return True

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
