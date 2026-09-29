"""Main-thread glue between the image sources and the overlay.

Two ways to receive frames from Figma (add-on preferences → Receive Mode):

- BUILTIN: Blender listens on 127.0.0.1:<port> itself (``receiver.py``);
  the Figma plugin pushes straight into Blender. No other process needed.
- BRIDGE:  Blender polls an external ``bridge/server.py`` (``network.py``).

Both run on background threads and post events to queues drained here.
"""

import os
import queue

import bpy

from . import overlay
from .network import poller
from .receiver import receiver
from .state import state

PUMP_INTERVAL = 0.05
DEFAULT_PORT = 8765


def _prefs():
    from .properties import get_prefs

    return get_prefs()


def mode():
    prefs = _prefs()
    return prefs.receive_mode if prefs else "BUILTIN"


def connect():
    disconnect()
    prefs = _prefs()
    state.last_error = ""
    if mode() == "BUILTIN":
        port = prefs.port if prefs else DEFAULT_PORT
        try:
            receiver.start("127.0.0.1", port)
        except OSError as exc:
            state.last_error = (f"Port {port} is in use (is bridge/server.py running?)"
                                if getattr(exc, "errno", None) in (48, 98, 10048) else str(exc))
            print(f"[Figma Preview] Could not start receiver: {exc}")
        state.connected = receiver.running
    else:
        url = prefs.bridge_url if prefs else f"http://127.0.0.1:{DEFAULT_PORT}"
        interval = prefs.poll_interval if prefs else 0.25
        state.connecting = True
        poller.start(url, interval)
    overlay.tag_redraw()


def disconnect():
    receiver.stop()
    poller.stop()
    state.connecting = False
    state.connected = False
    overlay.tag_redraw()


def is_running():
    return receiver.running or poller.running


def reload():
    if receiver.running:
        receiver.resend_latest()
    elif poller.running:
        poller.force_reload()


def _handle(event):
    kind = event[0]
    if kind == "connected":
        state.connected, state.connecting, state.last_error = True, False, ""
    elif kind == "disconnected":
        state.connected, state.connecting, state.last_error = False, False, event[1]
    elif kind == "image":
        _, path, meta = event
        try:
            overlay.set_image(path, name=meta["name"], width=meta["width"],
                              height=meta["height"], version=meta["version"], source="figma")
            state.last_error = ""
        except Exception as exc:  # keep the previous image on any load failure
            state.last_error = f"Could not load UI image: {exc}"
            print(f"[Figma Preview] {state.last_error}")
        finally:
            try:
                os.remove(path)
            except OSError:
                pass


def _pump():
    changed = False
    for events in (receiver.events, poller.events):
        while True:
            try:
                event = events.get_nowait()
            except queue.Empty:
                break
            _handle(event)
            changed = True
    if changed:
        overlay.tag_redraw()  # viewport overlay and sidebar panel
    return PUMP_INTERVAL


def _auto_connect():
    prefs = _prefs()
    if prefs is None or prefs.auto_connect:
        connect()
    return None


def register():
    if not bpy.app.timers.is_registered(_pump):
        bpy.app.timers.register(_pump, first_interval=PUMP_INTERVAL, persistent=True)
    bpy.app.timers.register(_auto_connect, first_interval=0.5)


def unregister():
    for fn in (_pump, _auto_connect):
        if bpy.app.timers.is_registered(fn):
            bpy.app.timers.unregister(fn)
    disconnect()
