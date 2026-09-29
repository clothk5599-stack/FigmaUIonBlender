"""Push a PNG to the bridge without Figma.

Examples:

    python tools/push_test.py                          # generated 2048x460 test UI
    python tools/push_test.py --size 1920x720          # different aspect ratio
    python tools/push_test.py --file my_ui.png --name Home
    python tools/push_test.py --loop 1.0               # push a new variant every second
    python tools/push_test.py --save test_ui.png       # only write the PNG (Phase 1 testing)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pngtools import encode_rgba  # noqa: E402

PALETTE = [(64, 160, 255), (255, 120, 64), (80, 220, 140), (220, 90, 220)]


def make_test_ui(width: int, height: int, variant: int = 0) -> bytes:
    """A transparent test frame: border, top bar, corner blocks and center cross.

    Everything is aligned to known pixel positions so pixel accuracy and
    aspect ratio are easy to verify in the Blender viewport.
    """
    r, g, b = PALETTE[variant % len(PALETTE)]
    buf = bytearray(width * height * 4)  # fully transparent

    def fill(x0, y0, x1, y1, rgba):
        x0, x1 = max(0, x0), min(width, x1)
        y0, y1 = max(0, y0), min(height, y1)
        if x0 >= x1:
            return
        row = bytes(rgba) * (x1 - x0)
        for y in range(max(0, y0), y1):
            start = (y * width + x0) * 4
            buf[start:start + len(row)] = row

    bar = max(8, height // 8)
    fill(0, 0, width, bar, (r, g, b, 200))                      # top bar
    fill(0, height - bar // 2, width, height, (20, 20, 20, 160))  # bottom strip
    t = 2
    fill(0, 0, width, t, (255, 255, 255, 255))                   # 2 px border
    fill(0, height - t, width, height, (255, 255, 255, 255))
    fill(0, 0, t, height, (255, 255, 255, 255))
    fill(width - t, 0, width, height, (255, 255, 255, 255))
    c = max(16, min(width, height) // 6)
    for cx, cy in ((0, 0), (width - c, 0), (0, height - c), (width - c, height - c)):
        fill(cx, cy, cx + c, cy + c, (r, g, b, 255))              # corner blocks
    fill(width // 2 - 1, height // 4, width // 2 + 1, height * 3 // 4, (255, 255, 255, 220))
    fill(width // 2 - height // 4, height // 2 - 1, width // 2 + height // 4, height // 2 + 1,
         (255, 255, 255, 220))
    # Variant indicator: N small squares under the top bar.
    for i in range(variant % 8 + 1):
        x = 3 * c // 2 + i * (c // 2)
        fill(x, bar + 8, x + c // 3, bar + 8 + c // 3, (255, 255, 255, 255))
    return encode_rgba(width, height, bytes(buf))


def multipart(fields: dict, file_field: str, filename: str, data: bytes):
    boundary = uuid.uuid4().hex
    parts = []
    for key, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'
            .encode("utf-8"))
    parts.append(
        (f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; '
         f'filename="{filename}"\r\nContent-Type: image/png\r\n\r\n').encode("utf-8"))
    parts.append(data)
    parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def push(url: str, png: bytes, name: str, width: float, height: float, scale: float = 1.0):
    fields = {"name": name, "width": width, "height": height, "scale": scale,
              "updatedAt": time.time()}
    body, content_type = multipart(fields, "image", "frame.png", png)
    req = urllib.request.Request(url.rstrip("/") + "/ui", data=body, method="POST",
                                 headers={"Content-Type": content_type})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://127.0.0.1:8765")
    ap.add_argument("--size", default="2048x460", help="WxH of the generated test UI")
    ap.add_argument("--file", help="push this PNG instead of a generated one")
    ap.add_argument("--name", default="TestFrame")
    ap.add_argument("--variant", type=int, default=0)
    ap.add_argument("--loop", type=float, help="push a new variant every N seconds")
    ap.add_argument("--save", help="write the generated PNG here and exit")
    args = ap.parse_args()

    width, height = (int(v) for v in args.size.lower().split("x"))

    if args.save:
        with open(args.save, "wb") as f:
            f.write(make_test_ui(width, height, args.variant))
        print(f"wrote {args.save} ({width}x{height})")
        return 0

    variant = args.variant
    while True:
        if args.file:
            with open(args.file, "rb") as f:
                png = f.read()
        else:
            png = make_test_ui(width, height, variant)
        result = push(args.url, png, args.name, width if not args.file else 0,
                      height if not args.file else 0)
        print(json.dumps(result))
        if not args.loop:
            return 0
        variant += 1
        time.sleep(args.loop)


if __name__ == "__main__":
    sys.exit(main())
