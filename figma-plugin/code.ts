// Plugin sandbox: reads the selection and exports it as PNG. Network requests
// happen in the UI iframe (ui.ts), which receives the exported bytes.

import { EXPORT_SCALE, FrameInfo, MainToUI, UIToMain } from "./messages";

const AUTO_PUSH_DEBOUNCE_MS = 400;

figma.showUI(__html__, { width: 280, height: 360, themeColors: true });

function post(message: MainToUI) {
  figma.ui.postMessage(message);
}

function selectedNode(): { node: SceneNode | null; reason: string } {
  const selection = figma.currentPage.selection;
  if (selection.length === 0) return { node: null, reason: "Select a frame" };
  if (selection.length > 1) return { node: null, reason: "Select a single frame" };
  const node = selection[0];
  if (!("exportAsync" in node)) return { node: null, reason: "This layer can't be exported" };
  if (node.width < 1 || node.height < 1) return { node: null, reason: "Frame has no size" };
  return { node, reason: "" };
}

function info(node: SceneNode): FrameInfo {
  return { id: node.id, name: node.name, width: node.width, height: node.height };
}

function sendSelection() {
  const { node, reason } = selectedNode();
  post({ type: "selection", frame: node ? info(node) : null, reason });
}

// --- Export ------------------------------------------------------------------

let autoPush = false;
let busy = false; // export or upload in flight
let pending = false; // another auto push requested while busy
let debounce: ReturnType<typeof setTimeout> | undefined;

async function exportSelection(auto: boolean) {
  const { node, reason } = selectedNode();
  if (!node) {
    if (!auto) post({ type: "export-error", message: reason, auto });
    return;
  }
  const frame = info(node);
  busy = true;
  post({ type: "exporting", frame, auto });
  try {
    const bytes = await node.exportAsync({
      format: "PNG",
      constraint: { type: "SCALE", value: EXPORT_SCALE },
      // Export the node's own bounds so image size = frame size × scale,
      // even when effects or children extend outside it.
      useAbsoluteBounds: true,
    });
    post({ type: "exported", frame, bytes, scale: EXPORT_SCALE, auto });
    // busy stays set until the UI reports the upload finished.
  } catch (err) {
    busy = false;
    post({ type: "export-error", message: String(err), auto });
  }
}

function requestAutoPush() {
  if (!autoPush) return;
  if (debounce !== undefined) clearTimeout(debounce);
  debounce = setTimeout(() => {
    debounce = undefined;
    if (busy) {
      pending = true;
    } else {
      exportSelection(true);
    }
  }, AUTO_PUSH_DEBOUNCE_MS);
}

// --- Change tracking for Auto Push ------------------------------------------

function isInside(node: BaseNode | null, ancestorId: string): boolean {
  for (let n = node; n; n = n.parent) {
    if (n.id === ancestorId) return true;
  }
  return false;
}

function onNodeChange(event: NodeChangeEvent) {
  if (!autoPush) return;
  const { node } = selectedNode();
  if (!node) return;
  const touched = event.nodeChanges.some(
    (change) => change.type === "DELETE" || isInside(change.node as BaseNode, node.id),
  );
  if (touched) requestAutoPush();
}

let watchedPage: PageNode = figma.currentPage;
watchedPage.on("nodechange", onNodeChange);

figma.on("currentpagechange", () => {
  watchedPage.off("nodechange", onNodeChange);
  watchedPage = figma.currentPage;
  watchedPage.on("nodechange", onNodeChange);
  sendSelection();
});

figma.on("selectionchange", () => {
  sendSelection();
  requestAutoPush();
});

figma.ui.onmessage = (message: UIToMain) => {
  switch (message.type) {
    case "push":
      if (!busy) exportSelection(false);
      break;
    case "set-auto":
      autoPush = message.enabled;
      if (autoPush) requestAutoPush();
      break;
    case "push-finished":
      busy = false;
      if (pending) {
        pending = false;
        requestAutoPush();
      }
      break;
  }
};

sendSelection();
