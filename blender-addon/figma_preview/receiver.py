"""Built-in receiver: the Figma plugin pushes straight into Blender.

A small HTTP server (standard library only) runs on a background thread
inside Blender, on loopback only (127.0.0.1 and ::1), and speaks the same API
as ``bridge/server.py``:

    POST /ui          multipart: image (PNG), name, width, height, scale
    GET  /status      availability + version (the plugin's connection check)
    GET  /latest.png  the last received image
    GET  /metadata    metadata of the last received image

Like ``network.py`` it never touches ``bpy``: received images are written to
a temp file and announced on ``events``; a main-thread timer uploads them.
Nothing is kept on disk after it has been loaded.
"""

import json
import os
import queue
import re
import shutil
import socket
import struct
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote

MAX_UPLOAD_BYTES = 64 * 1024 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def png_size(data):
    """Return (width, height) from a PNG's IHDR chunk, or raise ValueError."""
    if len(data) < 24 or not data.startswith(PNG_SIGNATURE) or data[12:16] != b"IHDR":
        raise ValueError("not a PNG file")
    width, height = struct.unpack(">II", data[16:24])
    if width == 0 or height == 0:
        raise ValueError("PNG has zero size")
    return width, height


_BOUNDARY_RE = re.compile(r'boundary="?([^";]+)"?', re.IGNORECASE)
_NAME_RE = re.compile(r'(?:^|;)\s*name="([^"]*)"', re.IGNORECASE)
_FILENAME_RE = re.compile(r'(?:^|;)\s*filename="([^"]*)"', re.IGNORECASE)


def parse_multipart(body, content_type):
    """Split a multipart/form-data body into ``(fields, files)``.

    Byte-exact for file parts (the boundary never occurs inside a part).
    """
    match = _BOUNDARY_RE.search(content_type or "")
    if not content_type.lower().startswith("multipart/form-data") or not match:
        raise ValueError("expected multipart/form-data")
    delimiter = b"--" + match.group(1).encode("latin-1")
    fields, files = {}, {}
    for part in body.split(delimiter)[1:]:
        if part.startswith(b"--"):
            break  # closing delimiter
        if part.startswith(b"\r\n"):
            part = part[2:]
        head, sep, data = part.partition(b"\r\n\r\n")
        if not sep:
            continue
        if data.endswith(b"\r\n"):
            data = data[:-2]
        disposition = ""
        for line in head.decode("utf-8", "replace").split("\r\n"):
            key, _, value = line.partition(":")
            if key.strip().lower() == "content-disposition":
                disposition = value
        name = _NAME_RE.search(disposition)
        if not name:
            continue
        if _FILENAME_RE.search(disposition):
            files[name.group(1)] = data
        else:
            fields[name.group(1)] = data.decode("utf-8", "replace")
    return fields, files


def _number(fields, key, default):
    try:
        value = float(fields.get(key, ""))
    except ValueError:
        return default
    return value if value > 0 else default


class _HTTPServerV6(ThreadingHTTPServer):
    address_family = socket.AF_INET6


class UIReceiver:
    def __init__(self):
        self.events = queue.Queue()
        self._servers = []
        self._threads = []
        self._lock = threading.Lock()
        self._version = 0
        self._latest = None  # (png bytes, meta)
        self._tmpdir = None

    @property
    def running(self):
        return any(thread.is_alive() for thread in self._threads)

    @property
    def port(self):
        return self._servers[0].server_address[1] if self._servers else 0

    @property
    def address(self):
        return f"http://localhost:{self.port}" if self._servers else ""

    def start(self, host="127.0.0.1", port=8765):
        """Start listening. Raises OSError if the port is already in use.

        The Figma plugin connects to ``localhost`` (Figma rejects IP
        addresses in the manifest), which may resolve to IPv4 or IPv6
        loopback, so on 127.0.0.1 also listen on ::1 when it is available.
        """
        self.stop()
        handler = _make_handler(self)
        primary = ThreadingHTTPServer((host, port), handler)
        servers = [primary]
        if host == "127.0.0.1" and socket.has_ipv6:
            try:
                servers.append(_HTTPServerV6(("::1", primary.server_address[1]), handler))
            except OSError:
                pass  # no IPv6 loopback, or ::1 port taken; IPv4 still works
        self._tmpdir = tempfile.mkdtemp(prefix="figma_preview_")
        for server in servers:
            server.daemon_threads = True
            thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.2},
                                      name="FigmaPreviewReceiver", daemon=True)
            thread.start()
            self._servers.append(server)
            self._threads.append(thread)

    def stop(self):
        servers, threads = self._servers, self._threads
        self._servers, self._threads = [], []
        for server in servers:
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=2.0)
        # Queued images live in the temp dir that is removed below.
        while True:
            try:
                self.events.get_nowait()
            except queue.Empty:
                break
        if self._tmpdir:
            shutil.rmtree(self._tmpdir, ignore_errors=True)
            self._tmpdir = None

    def resend_latest(self):
        """Announce the last received image again (Reload button)."""
        with self._lock:
            latest = self._latest
        if latest is not None:
            self._announce(*latest)

    # -- called from HTTP handler threads ----------------------------------

    def status(self):
        with self._lock:
            if self._latest is None:
                return {"available": False, "version": self._version}
            meta = self._latest[1]
            return {
                "available": True,
                "version": meta["version"],
                "frame": meta["name"],
                "width": meta["width"],
                "height": meta["height"],
                "scale": meta["scale"],
                "pixelWidth": meta["pixelWidth"],
                "pixelHeight": meta["pixelHeight"],
                "updatedAt": meta["updatedAt"],
            }

    def latest(self):
        with self._lock:
            return self._latest

    def receive(self, png, fields):
        """Validate and store a pushed frame, then hand it to Blender."""
        pixel_w, pixel_h = png_size(png)
        scale = _number(fields, "scale", 1.0)
        with self._lock:
            self._version += 1
            meta = {
                "version": self._version,
                "name": fields.get("name") or "Untitled",
                # Frame size in design units; fall back to the PNG size / scale.
                "width": _number(fields, "width", pixel_w / scale),
                "height": _number(fields, "height", pixel_h / scale),
                "scale": scale,
                "pixelWidth": pixel_w,
                "pixelHeight": pixel_h,
                "updatedAt": _number(fields, "updatedAt", time.time()),
            }
            self._latest = (png, meta)
        self._announce(png, meta)
        return meta

    def _announce(self, png, meta):
        tmpdir = self._tmpdir
        if tmpdir is None:
            return
        path = os.path.join(tmpdir, f"ui_{meta['version']}_{time.monotonic_ns()}.png")
        with open(path, "wb") as f:
            f.write(png)
        self.events.put(("image", path, meta))


_EXPOSED_HEADERS = "X-UI-Version, X-UI-Name, X-UI-Width, X-UI-Height, X-UI-Scale"


def _make_handler(receiver):
    class Handler(BaseHTTPRequestHandler):
        server_version = "FigmaPreviewBlender/1.0"

        def log_message(self, fmt, *args):
            pass  # keep Blender's console quiet

        def _cors(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Expose-Headers", _EXPOSED_HEADERS)

        def _send(self, status, body, content_type="application/json", headers=()):
            self.send_response(status)
            self._cors()
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for key, value in headers:
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status, obj):
            self._send(status, json.dumps(obj).encode("utf-8"))

        def do_OPTIONS(self):
            # CORS preflight; the Figma plugin UI runs in a "null" origin iframe.
            self.send_response(204)
            self._cors()
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            requested = self.headers.get("Access-Control-Request-Headers")
            self.send_header("Access-Control-Allow-Headers", requested or "*")
            if self.headers.get("Access-Control-Request-Private-Network"):
                self.send_header("Access-Control-Allow-Private-Network", "true")
            self.send_header("Access-Control-Max-Age", "600")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/status":
                self._json(200, receiver.status())
            elif path == "/metadata":
                latest = receiver.latest()
                if latest is None:
                    self._json(404, {"detail": "no UI pushed yet"})
                else:
                    self._json(200, latest[1])
            elif path == "/latest.png":
                latest = receiver.latest()
                if latest is None:
                    self._json(404, {"detail": "no UI pushed yet"})
                    return
                png, meta = latest
                self._send(200, png, "image/png", headers=(
                    ("X-UI-Version", str(meta["version"])),
                    ("X-UI-Name", quote(meta["name"])),
                    ("X-UI-Width", str(meta["width"])),
                    ("X-UI-Height", str(meta["height"])),
                    ("X-UI-Scale", str(meta["scale"])),
                ))
            else:
                self._json(404, {"detail": "not found"})

        def do_POST(self):
            if self.path.split("?", 1)[0] != "/ui":
                self._json(404, {"detail": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                self._json(411, {"detail": "Content-Length required"})
                return
            if length > MAX_UPLOAD_BYTES:
                self._json(413, {"detail": "image too large"})
                return
            body = self.rfile.read(length)
            try:
                fields, files = parse_multipart(body, self.headers.get("Content-Type", ""))
                if "image" not in files:
                    raise ValueError("missing 'image' file field")
                meta = receiver.receive(files["image"], fields)
            except ValueError as exc:
                self._json(400, {"detail": str(exc)})
                return
            self._json(200, {
                "ok": True,
                "version": meta["version"],
                "width": meta["width"],
                "height": meta["height"],
                "pixelWidth": meta["pixelWidth"],
                "pixelHeight": meta["pixelHeight"],
            })

    return Handler


receiver = UIReceiver()
