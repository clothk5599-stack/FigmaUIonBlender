"""Local bridge between the Figma plugin and the Blender add-on.

Figma POSTs the exported frame to ``/ui``; Blender polls ``/status`` and
downloads ``/latest.png`` whenever the version number changes.

Only the latest image and its metadata are kept on disk:

    data/latest.png
    data/metadata.json

Run with:

    python server.py            # or: uvicorn server:app --host 127.0.0.1 --port 8765
"""

from __future__ import annotations

import inspect
import json
import os
import struct
import threading
import time
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

HOST = os.environ.get("FIGMA_BRIDGE_HOST", "127.0.0.1")
PORT = int(os.environ.get("FIGMA_BRIDGE_PORT", "8765"))
MAX_UPLOAD_BYTES = int(os.environ.get("FIGMA_BRIDGE_MAX_BYTES", str(64 * 1024 * 1024)))

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def png_size(data: bytes) -> tuple[int, int]:
    """Return (width, height) from a PNG's IHDR chunk, or raise ValueError."""
    if len(data) < 24 or not data.startswith(PNG_SIGNATURE) or data[12:16] != b"IHDR":
        raise ValueError("not a PNG file")
    width, height = struct.unpack(">II", data[16:24])
    if width == 0 or height == 0:
        raise ValueError("PNG has zero size")
    return width, height


def _atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


class UIStore:
    """Holds the latest UI image + metadata, persisted to ``data_dir``."""

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.image_path = self.data_dir / "latest.png"
        self.meta_path = self.data_dir / "metadata.json"
        self._lock = threading.Lock()
        self._meta: Optional[dict] = None
        self._version = 0
        self._load()

    def _load(self) -> None:
        try:
            meta = json.loads(self.meta_path.read_text("utf-8"))
        except (OSError, ValueError):
            return
        self._version = int(meta.get("version", 0))
        if self.image_path.is_file():
            self._meta = meta

    @property
    def version(self) -> int:
        with self._lock:
            return self._version

    def save(self, image: bytes, name: str, width: float, height: float,
             scale: float, updated_at: Optional[float]) -> dict:
        pixel_w, pixel_h = png_size(image)
        with self._lock:
            self._version += 1
            meta = {
                "version": self._version,
                "name": name,
                "width": width,
                "height": height,
                "scale": scale,
                "pixelWidth": pixel_w,
                "pixelHeight": pixel_h,
                "updatedAt": updated_at if updated_at is not None else time.time(),
                "receivedAt": time.time(),
            }
            # Image first, then metadata: a reader never sees metadata for
            # an image that is not on disk yet.
            _atomic_write(self.image_path, image)
            _atomic_write(self.meta_path, json.dumps(meta, indent=2).encode("utf-8"))
            self._meta = meta
            return dict(meta)

    def metadata(self) -> Optional[dict]:
        with self._lock:
            return dict(self._meta) if self._meta else None

    def latest(self) -> Optional[tuple[bytes, dict]]:
        """Image bytes and matching metadata, read consistently."""
        with self._lock:
            if not self._meta:
                return None
            try:
                data = self.image_path.read_bytes()
            except OSError:
                return None
            return data, dict(self._meta)


def create_app(data_dir: Optional[Path] = None) -> FastAPI:
    store = UIStore(data_dir or Path(__file__).resolve().parent / "data")
    app = FastAPI(title="Figma → Blender bridge")
    app.state.store = store

    # The Figma plugin UI runs in an iframe with a "null" origin.
    cors = dict(
        allow_origins=["*"],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-UI-Version", "X-UI-Name", "X-UI-Width", "X-UI-Height", "X-UI-Scale"],
    )
    # Chromium's Private Network Access preflight for requests to localhost.
    native_pna = "allow_private_network" in inspect.signature(CORSMiddleware.__init__).parameters
    if native_pna:
        cors["allow_private_network"] = True
    app.add_middleware(CORSMiddleware, **cors)

    if not native_pna:
        @app.middleware("http")
        async def private_network_access(request: Request, call_next):
            response = await call_next(request)
            if request.headers.get("access-control-request-private-network"):
                response.headers["Access-Control-Allow-Private-Network"] = "true"
            return response

    @app.post("/ui")
    async def push_ui(
        image: UploadFile = File(...),
        name: str = Form(""),
        width: Optional[float] = Form(None),
        height: Optional[float] = Form(None),
        scale: float = Form(1.0),
        updatedAt: Optional[float] = Form(None),
    ):
        data = await image.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "image too large")
        try:
            pixel_w, pixel_h = png_size(data)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if scale <= 0:
            raise HTTPException(400, "scale must be positive")
        # Frame size in design units; fall back to the PNG size divided by scale.
        frame_w = width if width and width > 0 else pixel_w / scale
        frame_h = height if height and height > 0 else pixel_h / scale
        meta = store.save(data, name or "Untitled", frame_w, frame_h, scale, updatedAt)
        return {
            "ok": True,
            "version": meta["version"],
            "width": meta["width"],
            "height": meta["height"],
            "pixelWidth": meta["pixelWidth"],
            "pixelHeight": meta["pixelHeight"],
        }

    @app.get("/status")
    def status():
        meta = store.metadata()
        if not meta:
            return {"available": False, "version": store.version}
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

    @app.get("/metadata")
    def metadata():
        meta = store.metadata()
        if not meta:
            return JSONResponse({"detail": "no UI pushed yet"}, status_code=404)
        return meta

    @app.get("/latest.png")
    def latest_png():
        latest = store.latest()
        if latest is None:
            raise HTTPException(404, "no UI pushed yet")
        data, meta = latest
        return Response(
            content=data,
            media_type="image/png",
            headers={
                "Cache-Control": "no-store",
                # Metadata describing exactly these bytes, so a client never
                # pairs an image with the dimensions of a different push.
                "X-UI-Version": str(meta["version"]),
                "X-UI-Name": quote(meta["name"]),
                "X-UI-Width": str(meta["width"]),
                "X-UI-Height": str(meta["height"]),
                "X-UI-Scale": str(meta["scale"]),
            },
        )

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    print(f"Figma → Blender bridge on http://{HOST}:{PORT}")
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
