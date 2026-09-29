"""Runtime (non-saved) state shared by the overlay, panel and poller."""


class UIState:
    def __init__(self):
        self.connected = False
        self.connecting = False
        self.last_error = ""
        # Version of the image currently shown (0 = none from the bridge).
        self.version = 0
        self.frame_name = ""
        # Frame size in Figma design units (defines the preview aspect ratio).
        self.width = 0.0
        self.height = 0.0
        # Size of the texture in pixels (width * scale on export).
        self.pixel_width = 0
        self.pixel_height = 0
        self.source = ""  # "figma" (pushed) or "file" (loaded from disk)
        self.file_path = ""
        # gpu.types.GPUTexture. Replaced in one assignment so the previous
        # texture stays on screen until the next one is fully uploaded.
        self.texture = None

    @property
    def has_image(self):
        return self.texture is not None

    def content_size(self):
        """Size used for layout: design units, falling back to pixels."""
        if self.width > 0 and self.height > 0:
            return self.width, self.height
        return float(self.pixel_width), float(self.pixel_height)


state = UIState()
