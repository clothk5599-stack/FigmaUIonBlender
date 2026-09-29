"""Screen-space layout math for the overlay.

Pure Python (no ``bpy``/``gpu``) so it can be unit-tested outside Blender.
All rectangles are ``(x, y, width, height)`` in region pixels, origin at the
bottom-left, matching Blender's ``POST_PIXEL`` draw space. Results are
integers so the UI image lands on whole pixels.
"""

from __future__ import annotations

FIT = "FIT"
ONE_TO_ONE = "ONE_TO_ONE"


def visible_bounds(region_w, region_h, overlaps=()):
    """Part of the region not covered by overlapping side/top/bottom regions.

    ``overlaps`` are rects (relative to the region) of regions drawn on top of
    the viewport when "Region Overlap" is enabled: toolbar, sidebar, headers.
    Tall regions shrink the bounds horizontally, wide ones vertically.
    """
    x0, y0, x1, y1 = 0, 0, region_w, region_h
    for ox, oy, ow, oh in overlaps:
        if ow <= 1 or oh <= 1:
            continue  # hidden/collapsed region
        if ox >= region_w or oy >= region_h or ox + ow <= 0 or oy + oh <= 0:
            continue  # does not intersect
        if oh >= region_h * 0.5:  # side region
            if ox + ow / 2 < region_w / 2:
                x0 = max(x0, ox + ow)
            else:
                x1 = min(x1, ox)
        elif ow >= region_w * 0.5:  # header/footer
            if oy + oh / 2 < region_h / 2:
                y0 = max(y0, oy + oh)
            else:
                y1 = min(y1, oy)
    if x1 - x0 < 16 or y1 - y0 < 16:
        return 0, 0, region_w, region_h  # overlaps leave nothing useful
    return int(x0), int(y0), int(x1 - x0), int(y1 - y0)


def place(bounds, content_w, content_h, mode=FIT):
    """Rect for content of ``content_w x content_h`` centered in ``bounds``.

    FIT scales uniformly to the largest size that fits (letterbox or
    pillarbox), never stretching. ONE_TO_ONE draws one design pixel per
    screen pixel and may overflow the bounds.
    """
    bx, by, bw, bh = bounds
    if content_w <= 0 or content_h <= 0 or bw <= 0 or bh <= 0:
        return None
    if mode == ONE_TO_ONE:
        w, h = round(content_w), round(content_h)
    else:
        scale = min(bw / content_w, bh / content_h)
        w = max(1, round(content_w * scale))
        h = max(1, round(content_h * scale))
    x = bx + (bw - w) // 2
    y = by + (bh - h) // 2
    return int(x), int(y), int(w), int(h)


def outside(region_w, region_h, rect):
    """Up to four rects covering the region outside ``rect`` (for dimming)."""
    x, y, w, h = rect
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(region_w, x + w), min(region_h, y + h)
    if x0 >= x1 or y0 >= y1:
        return [(0, 0, region_w, region_h)]
    rects = [
        (0, y1, region_w, region_h - y1),   # top band
        (0, 0, region_w, y0),               # bottom band
        (0, y0, x0, y1 - y0),               # left
        (x1, y0, region_w - x1, y1 - y0),   # right
    ]
    return [r for r in rects if r[2] > 0 and r[3] > 0]


def inset(rect, fraction):
    """Shrink ``rect`` by ``fraction`` of its size on every side (safe area)."""
    x, y, w, h = rect
    dx, dy = round(w * fraction), round(h * fraction)
    return x + dx, y + dy, max(0, w - 2 * dx), max(0, h - 2 * dy)


def outline(rect, thickness=1):
    """Four thin rects forming the border of ``rect``, drawn inside it."""
    x, y, w, h = rect
    t = thickness
    if w <= 2 * t or h <= 2 * t:
        return [rect]
    return [
        (x, y, w, t),
        (x, y + h - t, w, t),
        (x, y + t, t, h - 2 * t),
        (x + w - t, y + t, t, h - 2 * t),
    ]


def center_lines(rect, thickness=1):
    """A vertical and a horizontal line through the center of ``rect``."""
    x, y, w, h = rect
    t = thickness
    return [
        (x + (w - t) // 2, y, t, h),
        (x, y + (h - t) // 2, w, t),
    ]
