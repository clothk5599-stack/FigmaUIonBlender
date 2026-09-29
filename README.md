# Figma → Blender Live UI Preview

Design the UI in **Figma**, build the 3D scene in **Blender**, and see both
together in the Blender viewport. The UI appears as a true screen-space overlay.
It stays pixel-aligned and aspect-correct, and nothing you do with the camera
(orbiting, moving, focal length, perspective/ortho) can move or distort it.

```text
Figma plugin ──PNG + metadata──▶ Blender add-on (listens on localhost:8765) ──▶ screen-space overlay
```

There's nothing else to run: the add-on receives the image itself. (A Figma
plugin can only send images out over a local web request, so Blender listens
for it on your machine only.)

| Folder | What it is |
| --- | --- |
| `figma-plugin/` | Figma plugin: exports the selected frame at 1× as a transparent PNG and sends it to Blender |
| `blender-addon/figma_preview/` | Blender add-on: receives the image and draws it in a `POST_PIXEL` viewport handler |
| `bridge/` | Optional: a separate FastAPI relay that Blender polls instead (see [Optional: external bridge](#optional-external-bridge)) |
| `tools/` | `push_test.py`: pushes generated test frames without Figma |

## Quick start

### 1. Install the Blender add-on (Blender 4.0+)

```bash
cd blender-addon
zip -r ../figma_preview.zip figma_preview -x '*__pycache__*'
```

In Blender, go to **Edit → Preferences → Add-ons**, choose **Install…**
(4.2+: the ▾ menu → **Install from Disk…**), pick `figma_preview.zip`, and
enable **Figma UI Preview**. For development, you can instead symlink
`blender-addon/figma_preview` into your Blender `scripts/addons` folder.

Open the viewport sidebar (**N**) and select the **Design Preview** tab. It
should say **Listening for Figma** (`http://localhost:8765`). The add-on
starts listening when Blender starts; turn that off, or change the port, in
the add-on preferences. If you change the port, also update `BRIDGE_URL` in
`figma-plugin/messages.ts` and `devAllowedDomains` in
`figma-plugin/manifest.json`, then rebuild the plugin.

### 2. Build and load the Figma plugin

```bash
cd figma-plugin
npm install
npm run build               # → dist/code.js, dist/ui.html  (npm run watch while developing)
```

In the Figma **desktop app**, go to **Plugins → Development → Import plugin from
manifest…** and choose `figma-plugin/manifest.json`.

### 3. Use it

1. Keep Blender open. In Figma, select a frame and run **Blender Preview**.
2. The plugin shows **Connected to Blender**, the frame name, and its size. Click **Push to Blender**.
3. The Blender viewport updates immediately.

Turn on **Auto Push** to re-export automatically about 0.4 s after you edit
the selected frame or select a different one.

## Blender panel

**3D Viewport → Sidebar → Design Preview → Figma UI**

- **Status / Start / Stop / Reload**: whether Blender is listening for Figma. **Reload** re-applies the last push.
- **Frame info**: name, size in Figma units, and version.
- **Visible**, **Opacity**
- **Display**: **Fit** scales the frame to the largest size that fits the
  viewport without stretching (letterbox or pillarbox). **1:1** draws one
  Figma pixel per screen pixel.
- **Display ▸**: **Dim Outside Frame** (with an amount), **Safe Area** (with an
  inset margin), **Center Lines**, **Frame Border**, and guide color.
  **Avoid Side Panels** fits the preview between the toolbar, sidebar, and
  headers when Region Overlap is on.
- **Tools ▸**:
  - **Match Render Resolution** sets the scene render size to the frame size, so the camera frame has the same aspect ratio.
  - **Load PNG** shows a PNG from disk (for example, one you exported from Figma by hand). The next push from Figma replaces it.
  - **Clear** removes the image.

## How it works

- **Screen space, not 3D.** The add-on draws with
  `SpaceView3D.draw_handler_add(..., "WINDOW", "POST_PIXEL")`. The image is a
  2D quad in region pixel coordinates, drawn after the scene. It never goes
  through the view or camera projection, so the camera can only change the 3D
  scene. This is the same in camera view (Numpad 0): the UI stays fixed to
  the viewport.
- **Aspect ratio comes from Figma.** The preview rectangle is computed from the
  pushed frame's width and height (`layout.py`) and rounded to whole pixels.
  When you push a frame with a different size, the preview rectangle updates
  on its own.
- **Colors are exact.** The PNG is decoded with Blender's image loader. The
  pixel values are uploaded to the GPU unconverted, and then the temporary
  image datablock is removed. A small shader reads Blender's `srgbTarget`
  uniform, the same one Blender's own UI shaders use, so the pixels look the
  same as in Figma whether or not the viewport framebuffer is sRGB. If that
  shader can't compile, the add-on falls back to the built-in `IMAGE_COLOR`
  shader.
- **Receiving without blocking Blender.** The receiver (`receiver.py`, Python
  standard library only) runs on a background thread, bound to loopback
  (`127.0.0.1` and `::1`) so only programs on your machine can reach it. The
  plugin connects to `localhost`, because Figma doesn't accept IP addresses in
  the manifest's `devAllowedDomains`. It never touches `bpy`: it writes
  each pushed PNG to a temp file and queues it.
- **No flicker.** A timer on the main thread builds the new texture and swaps
  it in with a single assignment. The old texture stays on screen until the new
  one is ready. If an image fails to load, the previous UI stays visible.
- **No accumulation.** Blender keeps only the latest image in memory, deletes
  each temp file after upload, and removes the decode datablock.

## API

The add-on's receiver and the optional bridge serve the same API, so the
Figma plugin and `push_test.py` work with either.

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/ui` | Multipart form: `image` (PNG), `name`, `width`, `height`, `scale` (default 1), `updatedAt`. Returns `{"ok": true, "version": 42, "width": 2048, "height": 460, ...}` |
| `GET` | `/status` | `{"available": true, "version": 42, "frame": "MasterLayout", "width": 2048, "height": 460, ...}` |
| `GET` | `/latest.png` | Latest image. `X-UI-Version`, `X-UI-Name`, `X-UI-Width`, `X-UI-Height`, and `X-UI-Scale` headers describe exactly these bytes |
| `GET` | `/metadata` | Contents of `metadata.json` |

If `width`/`height` are missing, the PNG size ÷ `scale` is used. Anything that
isn't a PNG is rejected.

```bash
curl -F image=@frame.png -F name=MasterLayout -F width=2048 -F height=460 http://127.0.0.1:8765/ui
curl http://127.0.0.1:8765/status
```

## Testing without Figma

```bash
python tools/push_test.py                    # 2048×460 test frame
python tools/push_test.py --size 1920x720    # different aspect ratio → preview reshapes
python tools/push_test.py --loop 1           # new variant every second → hot-reload check
python tools/push_test.py --save test.png    # PNG only (use with "Load PNG" in Blender)
```

These send to Blender directly (or to the bridge, whichever is listening on
port 8765). The test frame has a 2 px white border, corner blocks, and a center cross. You
can use them to check alignment and aspect ratio. The number of small squares
under the top bar shows the variant.

### Automated tests

```bash
python -m pip install -r bridge/requirements-dev.txt
python -m pytest bridge/tests blender-addon/tests
```

`blender-addon/tests/test_receiver.py` covers the built-in receiver and needs
no Blender. `blender-addon/tests/test_addon_bpy.py` runs only when the `bpy`
module is installed (`pip install bpy==4.2.*` on Python 3.11). It covers registration,
PNG decoding, the poller, and the texture-swap logic. Blender can't draw with
the GPU in background mode, so you need to check the overlay drawing itself in
a running Blender. Use the checklist below.

For the Figma plugin, run `npm run typecheck` in `figma-plugin/`.

### Manual acceptance checklist (Blender)

1. Push a frame and check that it appears over the viewport with transparency.
2. Orbit, pan, and zoom the view, move and rotate the camera, and change its
   focal length. The UI must not move or change.
3. Resize the viewport and open or close the sidebar. The UI keeps its aspect
   ratio and scales proportionally.
4. Run `push_test.py --loop 1`. The UI updates about every second with no blank frame in between.
5. Push `--size 1920x720` after `2048x460`. The preview rectangle changes shape.
6. Toggle **Visible** and drag **Opacity**.
7. In **1:1** mode, check that the 2 px border is exactly 2 screen pixels wide.

## Troubleshooting

- **Plugin says "Blender not listening"**: open Blender, check that the
  **Design Preview** panel says **Listening for Figma** (click **Start** if
  not), and check that `http://localhost:8765/status` opens in a browser.
- **Panel says "Port 8765 is in use"**: another program is using the port,
  often `bridge/server.py` or a second Blender window. Stop it, or pick another
  port (see Quick start step 1).
- **Colors look washed out or too dark in Blender**: the system console shows
  whether the custom image shader fell back to `IMAGE_COLOR`. Please report
  your Blender version and GPU backend.

## Optional: external bridge

`bridge/` is a separate relay server. It can be useful for debugging, or if
you want the last pushed frame kept on disk (`bridge/data/`) across Blender
restarts. To use it:

```bash
cd bridge
python -m pip install -r requirements.txt
python server.py            # serves http://127.0.0.1:8765
```

Then in the add-on preferences set **Receive Mode** to **External Bridge**. The
add-on then polls the bridge every 250 ms instead of listening itself. Only
one of the two can use port 8765 at a time.

## Out of scope (V1)

This version doesn't include WebSockets or WebRTC, node-by-node Figma import,
editable layers in Blender, cloud hosting, multi-user sessions, historical
versions, or timeline sync. See the plan for V2 ideas: multiple frames,
scene presets per frame, A/B compare, and push notifications.
