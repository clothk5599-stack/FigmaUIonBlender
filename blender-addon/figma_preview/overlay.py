"""Screen-space drawing of the Figma UI in the 3D viewport.

The image is drawn in a ``POST_PIXEL`` handler: 2D region pixel space, after
the 3D scene. It never goes through the view/camera projection, so orbiting,
moving the camera or changing focal length cannot move or distort it.
"""

import os

import bpy
import gpu
import numpy as np
from bpy_extras.view3d_utils import location_3d_to_region_2d
from gpu_extras.batch import batch_for_shader

from . import layout
from .state import state

_handle = None
_shaders = {}

# Regions that may be drawn over the viewport when "Region Overlap" is on.
_OVERLAP_REGIONS = {"TOOLS", "UI", "HEADER", "TOOL_HEADER", "ASSET_SHELF", "ASSET_SHELF_HEADER"}
_QUAD_INDICES = ((0, 1, 2), (2, 1, 3))


_IMAGE_VERT = """
void main()
{
    uv = texCoord;
    gl_Position = ModelViewProjectionMatrix * vec4(pos, 0.0, 1.0);
}
"""

# The texture holds display (sRGB) values, like Figma's PNG. Blender sets
# the built-in ``srgbTarget`` uniform when the bound framebuffer stores sRGB
# (the 3D viewport overlay does); convert to linear there so the hardware's
# re-encode reproduces the original pixels, as Blender's own UI shaders do.
_IMAGE_FRAG = """
vec3 srgb_to_linear(vec3 c)
{
    return mix(c / 12.92, pow((c + 0.055) / 1.055, vec3(2.4)), step(vec3(0.04045), c));
}

void main()
{
    vec4 color = texture(image, uv);
    color.a *= opacity;
    if (srgbTarget) {
        color.rgb = srgb_to_linear(color.rgb);
    }
    fragColor = color;
}
"""


def _shader(name):
    shader = _shaders.get(name)
    if shader is None:
        shader = _shaders[name] = gpu.shader.from_builtin(name)
    return shader


def _create_image_shader():
    iface = gpu.types.GPUStageInterfaceInfo("figma_preview_image_iface")
    iface.smooth("VEC2", "uv")
    info = gpu.types.GPUShaderCreateInfo()
    info.push_constant("MAT4", "ModelViewProjectionMatrix")
    info.push_constant("FLOAT", "opacity")
    info.push_constant("BOOL", "srgbTarget")
    info.sampler(0, "FLOAT_2D", "image")
    info.vertex_in(0, "VEC2", "pos")
    info.vertex_in(1, "VEC2", "texCoord")
    info.vertex_out(iface)
    info.fragment_out(0, "VEC4", "fragColor")
    info.vertex_source(_IMAGE_VERT)
    info.fragment_source(_IMAGE_FRAG)
    return gpu.shader.create_from_info(info)


def _image_shader():
    """``(shader, is_custom)``; falls back to the built-in IMAGE_COLOR shader
    (correct opacity, but no sRGB framebuffer handling) if compiling fails."""
    if "image" not in _shaders:
        try:
            _shaders["image"] = (_create_image_shader(), True)
        except Exception as exc:
            print(f"[Figma Preview] custom image shader unavailable ({exc}); using IMAGE_COLOR")
            _shaders["image"] = (gpu.shader.from_builtin("IMAGE_COLOR"), False)
    return _shaders["image"]


# ---------------------------------------------------------------------------
# Texture loading
# ---------------------------------------------------------------------------

def load_texture(path):
    """Decode a PNG into a GPU texture. Returns ``(texture, width, height)``.

    Uses a temporary image datablock only for decoding and removes it right
    away, so repeated pushes never accumulate images in the .blend file.
    Pixel values are uploaded unconverted: the built-in 2D image shaders
    expect display (sRGB) values, which is exactly what Figma exports.
    """
    image = bpy.data.images.load(os.path.abspath(path), check_existing=False)
    try:
        try:
            image.colorspace_settings.name = "Non-Color"
        except TypeError:
            pass  # custom OCIO config without "Non-Color"
        width, height = image.size
        channels = image.channels
        if width == 0 or height == 0:
            raise ValueError(f"could not read image: {path}")
        pixels = np.empty(width * height * channels, dtype=np.float32)
        image.pixels.foreach_get(pixels)
    finally:
        bpy.data.images.remove(image)

    if channels != 4:
        pixels = pixels.reshape(-1, channels)
        rgba = np.ones((pixels.shape[0], 4), dtype=np.float32)
        if channels >= 3:
            rgba[:, :3] = pixels[:, :3]
        else:
            rgba[:, :3] = pixels[:, :1]
        if channels in (2, 4):
            rgba[:, 3] = pixels[:, -1]
        pixels = rgba.ravel()

    buffer = gpu.types.Buffer("FLOAT", width * height * 4, pixels)
    texture = gpu.types.GPUTexture((width, height), format="RGBA16F", data=buffer)
    return texture, width, height


def set_image(path, name="", width=0.0, height=0.0, version=0, source="figma"):
    """Load ``path`` and swap it in. The old texture stays visible until the
    new one is uploaded, so updates never show a blank frame."""
    texture, pixel_w, pixel_h = load_texture(path)
    state.texture = texture
    state.pixel_width, state.pixel_height = pixel_w, pixel_h
    state.width = float(width) if width else float(pixel_w)
    state.height = float(height) if height else float(pixel_h)
    state.frame_name = name or os.path.splitext(os.path.basename(path))[0]
    state.version = version
    state.source = source
    if source == "file":
        state.file_path = path
    tag_redraw()


def clear_image():
    state.texture = None
    state.version = 0
    state.frame_name = ""
    state.width = state.height = 0.0
    state.pixel_width = state.pixel_height = 0
    state.source = ""
    tag_redraw()


def tag_redraw():
    wm = bpy.context.window_manager
    if wm is None:
        return
    for window in wm.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------

def _draw_rects(rects, color):
    if not rects:
        return
    coords, indices = [], []
    for x, y, w, h in rects:
        i = len(coords)
        coords += [(x, y), (x + w, y), (x, y + h), (x + w, y + h)]
        indices += [(i + a, i + b, i + c) for a, b, c in _QUAD_INDICES]
    shader = _shader("UNIFORM_COLOR")
    batch = batch_for_shader(shader, "TRIS", {"pos": coords}, indices=indices)
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)


def _draw_texture(texture, rect, opacity):
    x, y, w, h = rect
    shader, custom = _image_shader()
    batch = batch_for_shader(
        shader, "TRIS",
        {
            "pos": ((x, y), (x + w, y), (x, y + h), (x + w, y + h)),
            "texCoord": ((0, 0), (1, 0), (0, 1), (1, 1)),
        },
        indices=_QUAD_INDICES,
    )
    shader.bind()
    shader.uniform_sampler("image", texture)
    if custom:
        shader.uniform_float("opacity", opacity)
    else:
        shader.uniform_float("color", (1.0, 1.0, 1.0, opacity))
    batch.draw(shader)


def _region_overlaps(area, region):
    rects = []
    for other in area.regions:
        if other.type in _OVERLAP_REGIONS and other != region:
            rects.append((other.x - region.x, other.y - region.y, other.width, other.height))
    return rects


def camera_frame_rect(context):
    """The active camera's frame (the render border) in region pixels, when
    looking through the camera; otherwise None.

    Only the rectangle is taken from the camera. The UI itself is still
    drawn flat in screen space, so the camera cannot distort it.
    """
    region, rv3d, scene = context.region, context.region_data, context.scene
    if rv3d is None or rv3d.view_perspective != "CAMERA" or scene is None:
        return None
    camera = scene.camera
    if camera is None or camera.type != "CAMERA":
        return None
    matrix = camera.matrix_world
    corners = [matrix @ v for v in camera.data.view_frame(scene=scene)]
    return layout.bounding_rect(
        [location_3d_to_region_2d(region, rv3d, corner) for corner in corners])


def compute_layout(context, settings):
    """Preview rect for the current region, or None if nothing to draw."""
    region = context.region
    if region is None or not state.has_image:
        return None
    rw, rh = region.width, region.height
    content_w, content_h = state.content_size()
    if settings.fit_camera_frame:
        frame = camera_frame_rect(context)
        if frame is not None:
            return layout.place(frame, content_w, content_h, settings.display_mode)
    if settings.avoid_side_panels and context.area is not None:
        bounds = layout.visible_bounds(rw, rh, _region_overlaps(context.area, region))
    else:
        bounds = (0, 0, rw, rh)
    return layout.place(bounds, content_w, content_h, settings.display_mode)


def draw_overlay():
    context = bpy.context
    scene = context.scene
    settings = getattr(scene, "figma_preview", None) if scene else None
    if settings is None or not settings.visible or not state.has_image:
        return
    rect = compute_layout(context, settings)
    if rect is None:
        return
    region = context.region

    gpu.state.blend_set("ALPHA")
    try:
        if settings.dim_outside and settings.dim_opacity > 0:
            _draw_rects(layout.outside(region.width, region.height, rect),
                        (0.0, 0.0, 0.0, settings.dim_opacity))
        if settings.opacity > 0:
            _draw_texture(state.texture, rect, settings.opacity)
        guide = tuple(settings.guide_color)
        if settings.show_safe_area:
            safe = layout.inset(rect, settings.safe_area_margin)
            _draw_rects(layout.outline(safe), guide)
        if settings.show_center_lines:
            _draw_rects(layout.center_lines(rect), guide)
        if settings.show_frame_border:
            _draw_rects(layout.outline(rect), guide)
    finally:
        gpu.state.blend_set("NONE")


def register():
    global _handle
    if _handle is None:
        _handle = bpy.types.SpaceView3D.draw_handler_add(draw_overlay, (), "WINDOW", "POST_PIXEL")


def unregister():
    global _handle
    if _handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_handle, "WINDOW")
        _handle = None
    state.texture = None
    _shaders.clear()
