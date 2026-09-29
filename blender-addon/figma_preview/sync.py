"""Main-thread glue between the bridge poller and the overlay."""

import os
import queue

import bpy

from . import overlay
from .network import poller
from .state import state

PUMP_INTERVAL = 0.05


def connect():
    from .properties import get_prefs

    prefs = get_prefs()
    url = prefs.bridge_url if prefs else "http://127.0.0.1:8765"
    interval = prefs.poll_interval if prefs else 0.25
    state.connecting = True
    state.connected = False
    state.last_error = ""
    poller.start(url, interval)
    overlay.tag_redraw()


def disconnect():
    poller.stop()
    state.connecting = False
    state.connected = False
    overlay.tag_redraw()


def is_connected_or_connecting():
    return poller.running


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
                              height=meta["height"], version=meta["version"], source="bridge")
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
    while True:
        try:
            event = poller.events.get_nowait()
        except queue.Empty:
            break
        _handle(event)
        changed = True
    if changed:
        overlay.tag_redraw()  # viewport overlay and sidebar panel
    return PUMP_INTERVAL


def _auto_connect():
    from .properties import get_prefs

    prefs = get_prefs()
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
    poller.stop()
