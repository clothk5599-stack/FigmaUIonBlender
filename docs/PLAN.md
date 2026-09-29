# Figma → Blender Live UI Preview

## Project Goal

Build a lightweight workflow where:

- **Figma owns the UI design**
- **Blender owns the 3D scene**
- A **Figma plugin** exports the selected frame
- A small **local bridge server** transfers the UI image + metadata
- A **Blender add-on** displays the Figma UI as a true **screen-space overlay** in the 3D viewport
- The UI remains pixel-aligned, camera-independent, and free from perspective distortion
- UI updates can be pushed from Figma and appear in Blender with minimal delay

The UI must behave like a real product UI layer, not like a textured plane in 3D space.

---

# Target Experience

## In Figma

1. Select a frame.
2. Open the plugin.
3. See the selected frame name and size.
4. Click **Push to Blender**.
5. The plugin exports the frame as a PNG with transparency.
6. The plugin sends the PNG + metadata to localhost.

Example plugin UI:

```text
BLENDER PREVIEW

Selected
MasterLayout

2048 × 460

[ Push to Blender ]

[ ] Auto Push
```

---

## In Blender

The 3D viewport shows:

```text
┌──────────────────────────────────────────────┐
│                                              │
│   FIGMA UI — fixed in screen space           │
│                                              │
│   WELCOME                            21°      │
│   YOUR JOURNEY AWAITS                        │
│                         🚙                   │
│                                              │
│               3D scene below                 │
│                                              │
└──────────────────────────────────────────────┘
```

Expected behavior:

- Orbiting or moving the Blender camera changes only the 3D scene.
- Changing focal length changes only the 3D scene.
- Changing perspective does not distort the UI.
- The UI remains fixed to the viewport.
- The Figma frame aspect ratio becomes the design preview aspect ratio.
- Pushing a new Figma frame updates the Blender overlay automatically.

---

# High-Level Architecture

```text
┌──────────────┐
│ Figma Plugin │
└──────┬───────┘
       │
       │ PNG + metadata
       ▼
┌────────────────────┐
│ Local Bridge       │
│ localhost:8765     │
└────────┬───────────┘
         │
         │ latest image / update version
         ▼
┌────────────────────┐
│ Blender Add-on     │
│                    │
│ Screen-space       │
│ viewport overlay   │
└────────────────────┘
```

Use the bridge rather than making Figma communicate directly with Blender.

Benefits:

- easier debugging
- easier restart/reconnect behavior
- simpler Figma plugin
- simpler Blender networking
- future support for multiple clients or browser previews

---

# Repository Structure

```text
figma-blender-preview/
│
├── figma-plugin/
│   ├── manifest.json
│   ├── code.ts
│   ├── ui.html
│   ├── ui.ts
│   └── package.json
│
├── bridge/
│   ├── server.py
│   ├── requirements.txt
│   └── data/
│       ├── latest.png
│       └── metadata.json
│
├── blender-addon/
│   └── figma_preview/
│       ├── __init__.py
│       ├── overlay.py
│       ├── network.py
│       ├── state.py
│       ├── panel.py
│       └── operators.py
│
└── README.md
```

---

# Component 1 — Figma Plugin

## Responsibilities

The Figma plugin should:

1. Read the currently selected node.
2. Verify that it can be exported.
3. Get:
   - frame name
   - width
   - height
4. Export the selected frame as PNG.
5. Preserve transparency.
6. Send the PNG + metadata to the bridge server.
7. Show connection / success / error state.

---

## Export

Use Figma `exportAsync()`.

Conceptually:

```ts
const node = figma.currentPage.selection[0];

const bytes = await node.exportAsync({
  format: "PNG",
  constraint: {
    type: "SCALE",
    value: 1,
  },
});
```

For V1, export at **1×** so the exported pixel dimensions correspond directly to the Figma frame dimensions.

---

## Metadata

Example metadata:

```json
{
  "name": "MasterLayout",
  "width": 2048,
  "height": 460,
  "scale": 1,
  "updatedAt": 1780000000
}
```

---

## Push Endpoint

Send to:

```text
POST http://127.0.0.1:8765/ui
```

Payload should contain:

- PNG image bytes
- frame name
- width
- height
- optional timestamp

Multipart form-data is fine for V1.

---

## Figma Plugin V1 UI

```text
BLENDER PREVIEW
────────────────────

Connection
● Connected

Selected Frame
MasterLayout

Resolution
2048 × 460

[ Push to Blender ]

[ ] Auto Push
```

V1 does **not** need true live auto-sync. Manual push is enough initially.

---

# Component 2 — Local Bridge

## Technology

Use:

- Python
- FastAPI
- Uvicorn

Suggested dependencies:

```text
fastapi
uvicorn
python-multipart
```

---

## Responsibilities

The bridge server should:

1. Receive the Figma PNG.
2. Receive frame metadata.
3. Overwrite the previous UI image.
4. Save metadata.
5. Increment a version number.
6. Let Blender check whether a newer version exists.

Do **not** save every historical image.

Only keep:

```text
data/latest.png
data/metadata.json
```

This prevents storage accumulation.

---

## API Endpoints

### `POST /ui`

Receives:

- image
- frame name
- width
- height

On success:

- overwrite `latest.png`
- update `metadata.json`
- increment `version`

Example response:

```json
{
  "ok": true,
  "version": 42,
  "width": 2048,
  "height": 460
}
```

---

### `GET /status`

Example response:

```json
{
  "available": true,
  "version": 42,
  "frame": "MasterLayout",
  "width": 2048,
  "height": 460
}
```

---

### `GET /latest.png`

Returns the latest exported UI image.

---

### Optional: `GET /metadata`

Returns the latest metadata directly.

---

# Component 3 — Blender Add-on

## Main Rule

**Do not import the Figma image as a plane in 3D space.**

The image must be drawn as a **2D screen-space viewport overlay**.

Use Blender's viewport draw handler and GPU APIs.

Conceptually:

```python
bpy.types.SpaceView3D.draw_handler_add(...)
```

The overlay should be drawn after the 3D scene so it visually sits on top.

---

# Blender Overlay Behavior

The Figma frame is the source of truth for the design aspect ratio.

Example:

```text
width  = 2048
height = 460
aspect = 2048 / 460
```

The add-on should create a design preview region inside the Blender viewport that preserves this ratio.

Example:

```text
Blender viewport

┌──────────────────────────────────────────────┐
│                                              │
│         dimmed area outside preview          │
│                                              │
│ ┌──────────────────────────────────────────┐ │
│ │                                          │ │
│ │         exact Figma aspect ratio         │ │
│ │                                          │ │
│ │        3D scene + UI overlay             │ │
│ │                                          │ │
│ └──────────────────────────────────────────┘ │
│                                              │
└──────────────────────────────────────────────┘
```

Use letterboxing or pillarboxing as required.

Never stretch the UI to arbitrary viewport dimensions.

---

# Camera Independence

The Blender camera should affect only the world.

```text
3D scene
   ↓
Blender camera projection

UI
   ↓
2D screen-space coordinates
```

Therefore:

```text
Change focal length

Car → changes
UI  → unchanged
```

This is a core acceptance criterion.

---

# Blender Add-on State

Suggested state structure:

```python
ui_state = {
    "connected": False,
    "version": 0,
    "frame_name": "",
    "width": 0,
    "height": 0,
    "opacity": 1.0,
    "visible": True,
    "dim_outside": True,
    "show_safe_area": False,
    "show_center_lines": False,
}
```

---

# Blender Sidebar Panel

Create a panel in:

```text
3D Viewport → N Panel → Design Preview
```

Suggested UI:

```text
FIGMA UI
────────────────────

Status
● Connected

Frame
MasterLayout

Resolution
2048 × 460

UI
[x] Visible

Opacity
──────────● 100%

Display
(*) Fit
( ) 1:1

[x] Dim outside frame
[ ] Safe area
[ ] Center lines

[ Reload ]
```

---

# Update Strategy — V1

Use polling first.

The Blender add-on checks:

```text
GET http://127.0.0.1:8765/status
```

approximately every:

```text
250 ms
```

Pseudo-flow:

```text
Blender version = 41
Bridge version  = 42

42 > 41
   ↓
download latest.png
   ↓
load new texture
   ↓
update width / height
   ↓
redraw viewport
```

This is simple, robust, and good enough for V1.

Do not build WebSockets until the basic workflow is proven.

---

# Seamless Texture Updates

Avoid visible flicker during UI replacement.

Bad behavior:

```text
remove old UI
↓
load new UI
↓
show new UI
```

Desired behavior:

```text
Texture A is visible
↓
load Texture B in background
↓
Texture B is ready
↓
swap A → B
```

Keep the old texture visible until the new one is ready.

---

# Resolution Changes

The Blender add-on should react automatically to different Figma frame sizes.

Example 1:

```text
2048 × 460
aspect = 4.452
```

Example 2:

```text
1920 × 720
aspect = 2.667
```

If a different frame is pushed, Blender must update the design preview region automatically.

No manual aspect-ratio entry should be required.

---

# V1 Build Order

## Phase 1 — Blender Overlay Only

Goal:

- load a hardcoded PNG
- draw it as a screen-space overlay
- preserve image aspect ratio
- keep it fixed while camera settings change

Acceptance test:

- orbit camera → UI unchanged
- move camera → UI unchanged
- change focal length → UI unchanged
- resize Blender viewport → UI scales proportionally

---

## Phase 2 — Dynamic Metadata

Add:

- width / height loading from JSON
- automatic preview aspect ratio
- frame name
- overlay opacity
- visibility toggle

---

## Phase 3 — Local Bridge

Build:

```text
POST /ui
GET /status
GET /latest.png
```

Verify with curl or a test script before connecting Figma.

---

## Phase 4 — Blender Auto Refresh

Add:

- 250 ms polling
- version checking
- image download
- hot texture swap
- metadata refresh

---

## Phase 5 — Figma Plugin

Add:

- selected frame detection
- frame size display
- PNG export
- POST to localhost
- success / error state

---

## Phase 6 — Design Helpers

Add:

- UI opacity
- UI show / hide
- dim outside preview
- center line
- safe area
- optional grid

---

# V1 Acceptance Criteria

The first version is complete when all of the following work:

- [ ] Blender can display a transparent PNG over the 3D viewport.
- [ ] The UI is true screen-space content, not a 3D plane.
- [ ] Blender camera position does not move the UI.
- [ ] Blender camera rotation does not move the UI.
- [ ] Blender focal length / FOV does not distort the UI.
- [ ] Viewport resizing preserves the Figma frame aspect ratio.
- [ ] The Figma plugin can export the selected frame.
- [ ] The plugin can push PNG + dimensions to localhost.
- [ ] The bridge stores only the latest image.
- [ ] Blender automatically detects a new version.
- [ ] Blender hot-reloads the new UI without a visible blank frame.
- [ ] Pushing a frame with a different size updates the preview aspect ratio.
- [ ] UI visibility and opacity controls work.

---

# Explicitly Out of Scope for V1

Do not build these yet:

- full Blender-to-browser streaming
- Three.js recreation of the Blender scene
- Figma node-by-node import
- editable Figma layers inside Blender
- WebRTC
- WebSockets
- cloud hosting
- collaboration
- historical versions
- multi-user sessions
- animation timeline syncing
- browser remote control of Blender

The first version should remain a focused local design-preview workflow.

---

# V2 Ideas

Once V1 is stable, consider:

## Figma

- automatic push after design changes
- multiple named frames
- export scale selector
- frame presets
- send prototype states

## Blender

- multiple UI presets
- A/B UI compare mode
- screenshot export
- recording
- scene presets linked to Figma frames
- optional final-render compositing

## Bridge

- WebSocket push notifications
- multiple Blender clients
- session IDs
- browser preview client

---

# Possible Future Workflow

```text
Figma Frame
    ↓
Push to Blender
    ↓
Blender UI updates
    ↓
Matching Blender scene preset loads
    ↓
Designer adjusts:
- camera
- car placement
- lighting
- environment
    ↓
Evaluate complete 3D + UI composition
```

Potential mapping:

```text
HOME     → Blender scene preset A
NAV      → Blender scene preset B
MEDIA    → Blender scene preset C
WELCOME  → Blender scene preset D
```

---

# Recommended First Workspace Task

Start with this exact task:

> Build a Blender add-on that displays a transparent PNG as a pixel-accurate screen-space overlay in the 3D viewport, preserves the PNG's aspect ratio, remains independent of Blender camera projection, and can hot-reload the image without visible flicker.

Do not start with the Figma plugin.

Prove the Blender overlay first.

Once that works, build the local bridge and then connect Figma.

---

# Definition of Success

The finished workflow should feel like this:

```text
FIGMA
select frame
↓
Push to Blender
↓

BLENDER
UI instantly updates
↓
car / environment remain fully editable
↓
UI stays fixed and pixel-correct
↓
change camera / focal length / animation freely
↓
evaluate the final visual composition directly in Blender
```

The system should remain simple enough that a designer can run it locally without managing a complex graphics pipeline.
