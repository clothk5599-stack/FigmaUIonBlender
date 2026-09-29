import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bridge"))
sys.path.insert(0, str(ROOT / "tools"))

from pngtools import encode_rgba  # noqa: E402
from server import create_app, png_size  # noqa: E402


def png(w, h):
    return encode_rgba(w, h, bytes(w * h * 4))


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(tmp_path))


def push(client, data, **fields):
    return client.post("/ui", files={"image": ("frame.png", data, "image/png")}, data=fields)


def test_status_before_any_push(client):
    assert client.get("/status").json() == {"available": False, "version": 0}
    assert client.get("/latest.png").status_code == 404
    assert client.get("/metadata").status_code == 404


def test_push_then_status_and_image(client):
    data = png(64, 16)
    r = push(client, data, name="MasterLayout", width="64", height="16")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "version": 1, "width": 64, "height": 16,
                        "pixelWidth": 64, "pixelHeight": 16}

    s = client.get("/status").json()
    assert s["available"] and s["version"] == 1
    assert (s["frame"], s["width"], s["height"]) == ("MasterLayout", 64, 16)

    img = client.get("/latest.png")
    assert img.content == data
    assert img.headers["x-ui-version"] == "1"
    assert img.headers["cache-control"] == "no-store"


def test_version_increments_and_only_latest_kept(client, tmp_path):
    push(client, png(8, 8), name="A")
    push(client, png(30, 10), name="B")
    s = client.get("/status").json()
    assert s["version"] == 2 and s["frame"] == "B"
    assert (s["width"], s["height"]) == (30, 10)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["latest.png", "metadata.json"]
    assert png_size(client.get("/latest.png").content) == (30, 10)


def test_missing_dimensions_fall_back_to_png_and_scale(client):
    r = push(client, png(40, 20), name="Scaled", scale="2")
    assert (r.json()["width"], r.json()["height"]) == (20, 10)


def test_rejects_non_png(client):
    r = push(client, b"GIF89a....", name="bad")
    assert r.status_code == 400
    assert client.get("/status").json()["available"] is False


def test_version_survives_restart(tmp_path):
    push(TestClient(create_app(tmp_path)), png(4, 4), name="X")
    restarted = TestClient(create_app(tmp_path))
    assert restarted.get("/status").json()["version"] == 1
    assert push(restarted, png(4, 4)).json()["version"] == 2
    assert json.loads((tmp_path / "metadata.json").read_text())["version"] == 2


def test_cors_and_private_network_preflight(client):
    r = client.options("/ui", headers={
        "Origin": "null",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Private-Network": "true",
    })
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] in ("*", "null")
    assert r.headers["access-control-allow-private-network"] == "true"
