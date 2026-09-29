"""Background polling of the local bridge.

A worker thread polls ``GET /status`` and downloads ``/latest.png`` when the
version changes. It never touches ``bpy``: results go through a queue that a
main-thread timer drains (texture uploads must happen on the main thread).
Blender's UI therefore never blocks on the network.
"""

import json
import os
import queue
import shutil
import tempfile
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import unquote

# Always talk to the bridge directly, even if a system HTTP proxy is set.
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class BridgePoller:
    def __init__(self):
        self.events = queue.Queue()
        self._thread = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._lock = threading.Lock()
        self._base_url = ""
        self._interval = 0.25
        self._known_version = None
        self._tmpdir = None

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self, base_url, interval=0.25):
        self.stop()
        self._base_url = base_url.rstrip("/")
        self._interval = max(0.05, float(interval))
        self._known_version = None
        self._tmpdir = tempfile.mkdtemp(prefix="figma_preview_")
        # A fresh event per thread: a slow thread from a previous start()
        # stays stopped and cannot post stale events.
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(self._stop, self._tmpdir),
                                        name="FigmaPreviewPoller", daemon=True)
        self._thread.start()

    def stop(self):
        thread = self._thread
        if thread is None:
            return
        self._stop.set()
        self._wake.set()
        thread.join(timeout=2.0)
        self._thread = None
        # Queued downloads live in the temp dir that is removed below.
        while True:
            try:
                self.events.get_nowait()
            except queue.Empty:
                break
        if self._tmpdir:
            shutil.rmtree(self._tmpdir, ignore_errors=True)
            self._tmpdir = None

    def force_reload(self):
        """Re-download the latest image on the next poll."""
        with self._lock:
            self._known_version = None
        self._wake.set()

    # -- worker thread -----------------------------------------------------

    def _get(self, path, timeout):
        return _opener.open(self._base_url + path, timeout=timeout)

    def _run(self, stop, tmpdir):
        def post(*event):
            if not stop.is_set():
                self.events.put(event)

        was_connected = None
        while not stop.is_set():
            started = time.monotonic()
            try:
                with self._get("/status", timeout=1.0) as resp:
                    status = json.loads(resp.read())
                if was_connected is not True:
                    was_connected = True
                    post("connected", status)
                with self._lock:
                    known = self._known_version
                if status.get("available") and status.get("version") != known:
                    self._download(tmpdir, post)
            except (urllib.error.URLError, OSError, ValueError) as exc:
                if was_connected is not False:
                    was_connected = False
                    post("disconnected", str(getattr(exc, "reason", exc)))
            elapsed = time.monotonic() - started
            self._wake.wait(max(0.0, self._interval - elapsed))
            self._wake.clear()

    def _download(self, tmpdir, post):
        with self._get("/latest.png", timeout=10.0) as resp:
            data = resp.read()
            headers = resp.headers
        # The headers describe exactly these bytes, even if another push
        # landed between /status and this request.
        version = int(headers.get("X-UI-Version", "0"))
        meta = {
            "version": version,
            "name": unquote(headers.get("X-UI-Name", "")),
            "width": float(headers.get("X-UI-Width", "0") or 0),
            "height": float(headers.get("X-UI-Height", "0") or 0),
        }
        path = os.path.join(tmpdir, f"ui_{version}_{time.monotonic_ns()}.png")
        with open(path, "wb") as f:
            f.write(data)
        with self._lock:
            self._known_version = version
        post("image", path, meta)


poller = BridgePoller()
