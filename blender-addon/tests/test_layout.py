import importlib.util
from pathlib import Path

import pytest

# Import layout.py directly: the package __init__ needs bpy.
_spec = importlib.util.spec_from_file_location(
    "figma_layout", Path(__file__).resolve().parents[1] / "figma_preview" / "layout.py")
layout = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(layout)


@pytest.mark.parametrize("region,content", [
    ((1920, 1080), (2048, 460)),   # wide frame -> letterbox
    ((1000, 1000), (1920, 720)),
    ((800, 1200), (2048, 460)),
    ((1920, 1080), (400, 900)),    # tall frame -> pillarbox
    ((1366, 768), (1920, 1080)),
])
def test_fit_preserves_aspect_and_stays_inside(region, content):
    rw, rh = region
    x, y, w, h = layout.place((0, 0, rw, rh), *content, layout.FIT)
    assert 0 <= x and 0 <= y and x + w <= rw and y + h <= rh
    assert w == rw or h == rh  # touches the bounds on one axis
    assert abs(w / h - content[0] / content[1]) < 2 / min(w, h)  # within rounding
    assert all(isinstance(v, int) for v in (x, y, w, h))


def test_fit_is_centered():
    x, y, w, h = layout.place((0, 0, 1920, 1080), 2048, 460, layout.FIT)
    assert (x, w) == (0, 1920)
    assert h == round(460 * 1920 / 2048) == 431
    assert y == (1080 - 431) // 2


def test_resolution_change_updates_aspect():
    a = layout.place((0, 0, 1600, 900), 2048, 460)
    b = layout.place((0, 0, 1600, 900), 1920, 720)
    assert a[2] / a[3] == pytest.approx(2048 / 460, rel=0.01)
    assert b[2] / b[3] == pytest.approx(1920 / 720, rel=0.01)


def test_one_to_one_is_pixel_exact_and_may_overflow():
    assert layout.place((0, 0, 1000, 500), 2048, 460, layout.ONE_TO_ONE) == (-524, 20, 2048, 460)
    assert layout.place((100, 0, 800, 600), 200, 100, layout.ONE_TO_ONE) == (400, 250, 200, 100)


def test_place_rejects_empty():
    assert layout.place((0, 0, 100, 100), 0, 10) is None
    assert layout.place((0, 0, 0, 100), 10, 10) is None


def test_visible_bounds_avoids_sidebar_toolbar_and_header():
    overlaps = [
        (0, 0, 40, 1000),       # toolbar (left)
        (1600, 0, 320, 1000),   # sidebar (right)
        (0, 974, 1920, 26),     # header (top)
        (0, 0, 1, 1),           # hidden region
        (0, 1000, 1920, 26),    # outside the region
    ]
    assert layout.visible_bounds(1920, 1000, overlaps) == (40, 0, 1560, 974)


def test_visible_bounds_falls_back_when_nothing_left():
    assert layout.visible_bounds(100, 100, [(0, 0, 95, 100)]) == (0, 0, 100, 100)


def test_outside_covers_everything_but_rect():
    rw, rh, rect = 200, 100, (50, 20, 100, 60)
    rects = layout.outside(rw, rh, rect)
    area = sum(w * h for _, _, w, h in rects)
    assert area == rw * rh - 100 * 60
    for x, y, w, h in rects:  # no overlap with the preview rect
        assert x + w <= 50 or x >= 150 or y + h <= 20 or y >= 80


def test_outside_with_overflowing_rect():
    assert layout.outside(100, 100, (-50, 10, 200, 50)) == [(0, 60, 100, 40), (0, 0, 100, 10)]


def test_guides():
    assert layout.inset((0, 0, 200, 100), 0.1) == (20, 10, 160, 80)
    assert len(layout.outline((0, 0, 10, 10))) == 4
    v, h = layout.center_lines((0, 0, 101, 51))
    assert v == (50, 0, 1, 51) and h == (0, 25, 101, 1)


def test_bounding_rect_of_projected_corners():
    corners = [(10.4, 20.6), (210.2, 20.1), (210.3, 120.4), (10.1, 120.2), None]
    assert layout.bounding_rect(corners) == (10, 20, 200, 100)
    assert layout.bounding_rect([None, None]) is None
    assert layout.bounding_rect([(5, 5), (5.2, 5.1)]) is None  # degenerate


def test_fit_inside_camera_frame():
    # Camera frame 1000x250 at (100, 200); a 2048x460 UI is fitted inside it.
    x, y, w, h = layout.place((100, 200, 1000, 250), 2048, 460)
    assert (x, w) == (100, 1000) and h == round(460 * 1000 / 2048)
    assert y == 200 + (250 - h) // 2
