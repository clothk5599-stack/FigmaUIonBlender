import os

import bpy
from bpy.props import StringProperty
from bpy_extras.io_utils import ImportHelper

from . import overlay, sync
from .state import state


class FIGMAPREVIEW_OT_connect(bpy.types.Operator):
    bl_idname = "figma_preview.connect"
    bl_label = "Start"
    bl_description = "Start receiving frames pushed from the Figma plugin"

    def execute(self, context):
        sync.connect()
        return {"FINISHED"}


class FIGMAPREVIEW_OT_disconnect(bpy.types.Operator):
    bl_idname = "figma_preview.disconnect"
    bl_label = "Stop"
    bl_description = "Stop receiving frames (the current UI image stays visible)"

    def execute(self, context):
        sync.disconnect()
        return {"FINISHED"}


class FIGMAPREVIEW_OT_reload(bpy.types.Operator):
    bl_idname = "figma_preview.reload"
    bl_label = "Reload"
    bl_description = "Reload the last Figma push, or the PNG from disk for a loaded file"

    def execute(self, context):
        if state.source == "file" and state.file_path:
            try:
                overlay.set_image(state.file_path, source="file")
            except Exception as exc:
                self.report({"ERROR"}, f"Could not reload image: {exc}")
                return {"CANCELLED"}
        elif sync.is_running():
            sync.reload()
        else:
            sync.connect()
        return {"FINISHED"}


class FIGMAPREVIEW_OT_load_file(bpy.types.Operator, ImportHelper):
    bl_idname = "figma_preview.load_file"
    bl_label = "Load PNG"
    bl_description = "Show a PNG from disk as the UI overlay (the next Figma push replaces it)"

    filename_ext = ".png"
    filter_glob: StringProperty(default="*.png", options={"HIDDEN"})

    def execute(self, context):
        if not os.path.isfile(self.filepath):
            self.report({"ERROR"}, "Choose a PNG file")
            return {"CANCELLED"}
        try:
            overlay.set_image(self.filepath, source="file")
        except Exception as exc:
            self.report({"ERROR"}, f"Could not load image: {exc}")
            return {"CANCELLED"}
        return {"FINISHED"}


class FIGMAPREVIEW_OT_clear(bpy.types.Operator):
    bl_idname = "figma_preview.clear"
    bl_label = "Clear"
    bl_description = "Remove the UI overlay image"

    def execute(self, context):
        overlay.clear_image()
        return {"FINISHED"}


class FIGMAPREVIEW_OT_match_render(bpy.types.Operator):
    bl_idname = "figma_preview.match_render_resolution"
    bl_label = "Match Render Resolution"
    bl_description = ("Set the scene render resolution to the Figma frame size so the "
                      "camera frame has the same aspect ratio as the UI")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return state.has_image

    def execute(self, context):
        width, height = state.content_size()
        render = context.scene.render
        render.resolution_x = max(4, round(width))
        render.resolution_y = max(4, round(height))
        render.resolution_percentage = 100
        render.pixel_aspect_x = render.pixel_aspect_y = 1.0
        return {"FINISHED"}


classes = (
    FIGMAPREVIEW_OT_connect,
    FIGMAPREVIEW_OT_disconnect,
    FIGMAPREVIEW_OT_reload,
    FIGMAPREVIEW_OT_load_file,
    FIGMAPREVIEW_OT_clear,
    FIGMAPREVIEW_OT_match_render,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
