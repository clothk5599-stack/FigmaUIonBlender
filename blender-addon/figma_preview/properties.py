"""Saved settings: per-scene display options and add-on preferences."""

import bpy
from bpy.props import (BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty,
                       IntProperty, StringProperty)

from . import overlay


def _redraw(self, context):
    overlay.tag_redraw()


def _restart(self, context):
    from . import sync

    if sync.is_running():
        sync.connect()


class FigmaPreviewSettings(bpy.types.PropertyGroup):
    visible: BoolProperty(name="Visible", default=True, update=_redraw,
                          description="Show the Figma UI over the 3D viewport")
    opacity: FloatProperty(name="Opacity", default=1.0, min=0.0, max=1.0,
                           subtype="FACTOR", update=_redraw)
    display_mode: EnumProperty(
        name="Display",
        items=(
            ("FIT", "Fit", "Scale the frame to fit the viewport, keeping its aspect ratio"),
            ("ONE_TO_ONE", "1:1", "One Figma pixel per screen pixel"),
        ),
        default="FIT", update=_redraw,
    )
    avoid_side_panels: BoolProperty(
        name="Avoid Side Panels", default=True, update=_redraw,
        description="Fit the preview between the toolbar, sidebar and headers "
                    "when they overlap the viewport")
    dim_outside: BoolProperty(name="Dim Outside Frame", default=True, update=_redraw)
    dim_opacity: FloatProperty(name="Dim Amount", default=0.6, min=0.0, max=1.0,
                               subtype="FACTOR", update=_redraw)
    show_frame_border: BoolProperty(name="Frame Border", default=False, update=_redraw)
    show_safe_area: BoolProperty(name="Safe Area", default=False, update=_redraw)
    safe_area_margin: FloatProperty(name="Margin", default=0.05, min=0.0, max=0.45,
                                    subtype="FACTOR", update=_redraw,
                                    description="Safe-area inset as a fraction of the frame size")
    show_center_lines: BoolProperty(name="Center Lines", default=False, update=_redraw)
    guide_color: FloatVectorProperty(name="Guide Color", subtype="COLOR_GAMMA", size=4,
                                     min=0.0, max=1.0, default=(0.2, 0.8, 1.0, 0.8),
                                     update=_redraw)


class FigmaPreviewPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    receive_mode: EnumProperty(
        name="Receive Mode",
        items=(
            ("BUILTIN", "Direct from Figma",
             "Blender listens for the Figma plugin itself. Nothing else to run"),
            ("BRIDGE", "External Bridge",
             "Poll a separately running bridge/server.py"),
        ),
        default="BUILTIN", update=_restart,
    )
    port: IntProperty(name="Port", default=8765, min=1024, max=65535, update=_restart,
                      description="Local port the Figma plugin sends to (127.0.0.1 only)")
    bridge_url: StringProperty(name="Bridge URL", default="http://127.0.0.1:8765",
                               update=_restart)
    poll_interval: FloatProperty(name="Poll Interval", default=0.25, min=0.05, max=10.0,
                                 unit="TIME_ABSOLUTE", update=_restart,
                                 description="Seconds between bridge status checks")
    auto_connect: BoolProperty(name="Start on Startup", default=True,
                               description="Start receiving when Blender starts")

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "receive_mode", expand=True)
        if self.receive_mode == "BUILTIN":
            layout.prop(self, "port")
        else:
            layout.prop(self, "bridge_url")
            layout.prop(self, "poll_interval")
        layout.prop(self, "auto_connect")


def get_prefs(context=None):
    context = context or bpy.context
    addon = context.preferences.addons.get(__package__)
    return addon.preferences if addon else None


classes = (FigmaPreviewSettings, FigmaPreviewPreferences)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.figma_preview = bpy.props.PointerProperty(type=FigmaPreviewSettings)


def unregister():
    del bpy.types.Scene.figma_preview
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
