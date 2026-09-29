import bpy

from . import sync
from .network import poller
from .receiver import receiver
from .state import state


def _fmt(value):
    return f"{value:g}"


class FIGMAPREVIEW_PT_main(bpy.types.Panel):
    bl_label = "Figma UI"
    bl_idname = "FIGMAPREVIEW_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Design Preview"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.figma_preview

        # Status
        col = layout.column(align=True)
        builtin = sync.mode() == "BUILTIN"
        if receiver.running:
            col.label(text="Listening for Figma", icon="LINKED")
            col.label(text=receiver.address)
        elif poller.running and state.connected:
            col.label(text="Connected to bridge", icon="LINKED")
        elif poller.running:
            col.label(text="Waiting for bridge…" if state.connecting else "Bridge offline",
                      icon="TIME" if state.connecting else "ERROR")
        else:
            col.label(text="Stopped", icon="UNLINKED")
        if state.last_error and not state.connected:
            col.label(text=state.last_error[:60], icon="ERROR")

        row = layout.row(align=True)
        if sync.is_running():
            row.operator("figma_preview.disconnect", icon="CANCEL",
                         text="Stop" if builtin else "Disconnect")
        else:
            row.operator("figma_preview.connect", icon="PLAY",
                         text="Start" if builtin else "Connect")
        row.operator("figma_preview.reload", icon="FILE_REFRESH")

        # Frame info
        box = layout.box()
        if state.has_image:
            box.label(text=state.frame_name or "Untitled", icon="IMAGE_DATA")
            width, height = state.content_size()
            box.label(text=f"{_fmt(width)} × {_fmt(height)}")
            if (state.pixel_width, state.pixel_height) != (round(width), round(height)):
                box.label(text=f"Image {state.pixel_width} × {state.pixel_height} px")
            if state.source == "figma":
                box.label(text=f"Version {state.version}")
            else:
                box.label(text="Loaded from file")
        else:
            box.label(text="No UI yet — push a frame from Figma", icon="INFO")

        # UI
        col = layout.column()
        col.prop(settings, "visible")
        sub = col.column()
        sub.active = settings.visible
        sub.prop(settings, "opacity", slider=True)
        sub.row().prop(settings, "display_mode", expand=True)
        layout.operator("figma_preview.view_selected_camera", icon="VIEW_CAMERA")


class FIGMAPREVIEW_PT_guides(bpy.types.Panel):
    bl_label = "Display"
    bl_parent_id = "FIGMAPREVIEW_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Design Preview"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.figma_preview
        col = layout.column()
        row = col.row(align=True)
        row.prop(settings, "dim_outside")
        sub = row.row(align=True)
        sub.active = settings.dim_outside
        sub.prop(settings, "dim_opacity", text="")
        row = col.row(align=True)
        row.prop(settings, "show_safe_area")
        sub = row.row(align=True)
        sub.active = settings.show_safe_area
        sub.prop(settings, "safe_area_margin", text="")
        col.prop(settings, "show_center_lines")
        col.prop(settings, "show_frame_border")
        col.prop(settings, "guide_color")
        col.prop(settings, "camera_follows_ui")
        col.prop(settings, "fit_camera_frame")
        col.prop(settings, "avoid_side_panels")


class FIGMAPREVIEW_PT_tools(bpy.types.Panel):
    bl_label = "Tools"
    bl_parent_id = "FIGMAPREVIEW_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Design Preview"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        col = self.layout.column(align=True)
        col.operator("figma_preview.match_render_resolution", icon="CAMERA_DATA")
        col.operator("figma_preview.load_file", icon="FILEBROWSER")
        col.operator("figma_preview.clear", icon="X")


classes = (FIGMAPREVIEW_PT_main, FIGMAPREVIEW_PT_guides, FIGMAPREVIEW_PT_tools)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
