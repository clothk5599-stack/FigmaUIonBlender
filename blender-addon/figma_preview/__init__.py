bl_info = {
    "name": "Figma UI Preview",
    "author": "FigmaUIonBlender",
    "version": (0, 4, 0),
    "blender": (4, 0, 0),
    "location": "3D Viewport > Sidebar (N) > Design Preview",
    "description": "Show a Figma frame as a pixel-aligned screen-space overlay "
                   "in the 3D viewport, pushed straight from the Figma plugin",
    "category": "3D View",
}

from . import operators, overlay, panel, properties, sync  # noqa: E402

_modules = (properties, operators, panel, overlay, sync)


def register():
    for module in _modules:
        module.register()


def unregister():
    for module in reversed(_modules):
        module.unregister()
