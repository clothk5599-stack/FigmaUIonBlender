"""The built-in receiver (no bpy needed): Figma plugin → Blender directly."""

import importlib.util
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from push_test import make_test_ui, multipart, push  # noqa: E402

# Import receiver.py directly: the package __init__ needs bpy.
_spec = importlib.util.spec_from_file_location(
    "figma_receiver", ROOT / "blender-addon" / "figma_preview" / "receiver.py")
rx = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rx)


@pytest.fixture
def receiver():
    r = rx.UIReceiver()
    r.start("127.0.0.1", 0)
    yield r
    r.stop()


def get(url, headers=None, method="GET"):
    req = urllib.request.Request(url, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as err:
        return err.code, dict(err.headers), err.read()


def test_status_before_push(receiver):
    status, _, body = get(receiver.address + "/status")
    assert status == 200 and json.loads(body) == {"available": False, "version": 0}
    assert get(receiver.address + "/latest.png")[0] == 404


def test_push_is_delivered_to_blender(receiver):
    png = make_test_ui(320, 72, variant=1)
    result = push(receiver.address, png, "Home ✓", 320, 72)
    assert result == {"ok": True, "version": 1, "width": 320.0, "height": 72.0,
                      "pixelWidth": 320, "pixelHeight": 72}

    kind, path, meta = receiver.events.get(timeout=2)
    assert kind == "image" and Path(path).read_bytes() == png
    assert (meta["name"], meta["width"], meta["height"], meta["version"]) == ("Home ✓", 320, 72, 1)

    status = json.loads(get(receiver.address + "/status")[2])
    assert status["available"] and status["frame"] == "Home ✓" and status["version"] == 1
    code, headers, body = get(receiver.address + "/latest.png")
    assert code == 200 and body == png and headers["X-UI-Version"] == "1"


def test_versions_increment_and_reload_resends(receiver):
    push(receiver.address, make_test_ui(40, 20), "A", 40, 20)
    push(receiver.address, make_test_ui(30, 10), "B", 30, 10)
    assert [receiver.events.get(timeout=2)[2]["version"] for _ in range(2)] == [1, 2]
    receiver.resend_latest()
    _, _, meta = receiver.events.get(timeout=2)
    assert (meta["version"], meta["name"]) == (2, "B")


def test_multipart_is_byte_exact():
    # Trailing bytes that look like CRLFs and dashes must survive untouched.
    data = make_test_ui(8, 8) + b"\r\n--\r\n\r\n" + bytes(range(256))
    body, content_type = multipart({"name": "X", "width": 8}, "image", "f.png", data)
    fields, files = rx.parse_multipart(body, content_type)
    assert files["image"] == data and fields == {"name": "X", "width": "8"}


def test_missing_sizes_fall_back_to_png_and_scale(receiver):
    body, content_type = multipart({"name": "S", "scale": 2}, "image", "f.png", make_test_ui(40, 20))
    req = urllib.request.Request(receiver.address + "/ui", data=body, method="POST",
                                 headers={"Content-Type": content_type})
    with urllib.request.urlopen(req, timeout=5) as resp:
        result = json.loads(resp.read())
    assert (result["width"], result["height"]) == (20, 10)


def test_rejects_non_png(receiver):
    body, content_type = multipart({"name": "bad"}, "image", "f.gif", b"GIF89a" + bytes(40))
    req = urllib.request.Request(receiver.address + "/ui", data=body, method="POST",
                                 headers={"Content-Type": content_type})
    with pytest.raises(urllib.error.HTTPError) as err:
        urllib.request.urlopen(req, timeout=5)
    assert err.value.code == 400
    assert receiver.events.empty()


def test_cors_preflight_from_figma_iframe(receiver):
    code, headers, _ = get(receiver.address + "/ui", method="OPTIONS", headers={
        "Origin": "null",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Private-Network": "true",
    })
    assert code == 204
    assert headers["Access-Control-Allow-Origin"] == "*"
    assert headers["Access-Control-Allow-Private-Network"] == "true"


def test_port_in_use_raises(receiver):
    port = int(receiver.address.rsplit(":", 1)[1])
    other = rx.UIReceiver()
    with pytest.raises(OSError):
        other.start("127.0.0.1", port)
    assert not other.running


def test_stop_cleans_up_temp_files(receiver):
    push(receiver.address, make_test_ui(8, 8), "T", 8, 8)
    _, path, _ = receiver.events.get(timeout=2)
    receiver.stop()
    assert not os.path.exists(path) and not receiver.running


def test_reachable_on_ipv4_and_ipv6_loopback(receiver):
    # The Figma plugin uses "localhost", which may resolve to either.
    port = receiver.port
    assert json.loads(get(f"http://127.0.0.1:{port}/status")[2])["version"] == 0
    if len(receiver._servers) < 2:
        pytest.skip("no IPv6 loopback on this machine")
    assert json.loads(get(f"http://[::1]:{port}/status")[2])["version"] == 0
