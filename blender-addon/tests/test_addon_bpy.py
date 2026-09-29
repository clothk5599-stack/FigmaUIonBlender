"""Smoke test with the ``bpy`` module (pip install bpy). GPU drawing is not
available in background mode, so this covers registration, settings,
PNG decoding and the bridge poller, not the draw call itself."""

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

bpy = pytest.importorskip("bpy")
np = pytest.importorskip("numpy")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "blender-addon"))
sys.path.insert(0, str(ROOT / "tools"))

import figma_preview  # noqa: E402
from figma_preview import network  # noqa: E402
from figma_preview.state import state  # noqa: E402
from push_test import make_test_ui  # noqa: E402


@pytest.fixture(scope="module")
def addon():
    figma_preview.register()
    yield
    figma_preview.unregister()


def test_register_and_settings(addon):
    s = bpy.context.scene.figma_preview
    assert (s.visible, s.opacity, s.display_mode, s.dim_outside) == (True, 1.0, "FIT", True)


def test_png_decodes_to_unconverted_srgb_rgba(addon, tmp_path):
    path = tmp_path / "ui.png"
    path.write_bytes(make_test_ui(300, 100, variant=0))
    before = len(bpy.data.images)
    image = bpy.data.images.load(str(path), check_existing=False)
    image.colorspace_settings.name = "Non-Color"
    w, h = image.size
    px = np.empty(w * h * image.channels, dtype=np.float32)
    image.pixels.foreach_get(px)
    bpy.data.images.remove(image)
    assert len(bpy.data.images) == before
    px = px.reshape(h, w, 4)
    # Blender rows are bottom-up: the PNG's top-left corner block is the last row.
    assert np.allclose(px[h - 1, 0] * 255, (64, 160, 255, 255), atol=0.5)
    assert np.allclose(px[h // 2, w // 4], 0)  # transparent stays transparent


class _Bridge(BaseHTTPRequestHandler):
    png = b""
    version = 7

    def do_GET(self):
        if self.path == "/status":
            body = json.dumps({"available": True, "version": self.version}).encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/latest.png":
            self.send_response(200)
            for k, v in (("X-UI-Version", self.version), ("X-UI-Name", "Home%20%E2%9C%93"),
                         ("X-UI-Width", "300"), ("X-UI-Height", "100")):
                self.send_header(k, str(v))
            self.end_headers()
            self.wfile.write(self.png)

    def log_message(self, *args):
        pass


def test_poller_downloads_new_versions(tmp_path):
    _Bridge.png = make_test_ui(300, 100)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Bridge)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    poller = network.BridgePoller()
    try:
        poller.start(f"http://127.0.0.1:{server.server_port}", interval=0.05)
        events = []
        deadline = time.time() + 5
        while time.time() < deadline and not any(e[0] == "image" for e in events):
            try:
                events.append(poller.events.get(timeout=0.1))
            except Exception:
                pass
        assert events[0][0] == "connected"
        _, path, meta = next(e for e in events if e[0] == "image")
        assert meta == {"version": 7, "name": "Home ✓", "width": 300.0, "height": 100.0}
        assert Path(path).read_bytes() == _Bridge.png
        time.sleep(0.3)  # same version: no second download
        assert all(e[0] != "image" for e in list(poller.events.queue))
    finally:
        poller.stop()
        server.shutdown()


def test_connect_disconnect_operators(addon):
    assert bpy.ops.figma_preview.connect() == {"FINISHED"}
    assert network.poller.running
    assert bpy.ops.figma_preview.disconnect() == {"FINISHED"}
    assert not network.poller.running and not state.connected


def test_failed_load_keeps_previous_image_and_removes_temp_file(addon, tmp_path, monkeypatch):
    from figma_preview import overlay, sync

    def fake_texture(path):
        if "bad" in str(path):
            raise ValueError("corrupt")
        return object(), 300, 100

    monkeypatch.setattr(overlay, "load_texture", fake_texture)
    good, bad = tmp_path / "good.png", tmp_path / "bad.png"
    good.write_bytes(b"x")
    bad.write_bytes(b"x")

    sync._handle(("image", str(good), {"version": 3, "name": "Home", "width": 150.0, "height": 50.0}))
    shown = state.texture
    assert shown is not None and (state.version, state.frame_name) == (3, "Home")
    assert state.content_size() == (150.0, 50.0) and (state.pixel_width, state.pixel_height) == (300, 100)
    assert not good.exists()

    sync._handle(("image", str(bad), {"version": 4, "name": "Nav", "width": 1.0, "height": 1.0}))
    assert state.texture is shown and state.version == 3  # old UI stays up
    assert "corrupt" in state.last_error and not bad.exists()

    bpy.ops.figma_preview.match_render_resolution()
    render = bpy.context.scene.render
    assert (render.resolution_x, render.resolution_y, render.resolution_percentage) == (150, 50, 100)
    overlay.clear_image()
    assert state.texture is None
