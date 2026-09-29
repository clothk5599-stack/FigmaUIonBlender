"use strict";
(() => {
  // messages.ts
  var EXPORT_SCALE = 1;

  // code.ts
  var AUTO_PUSH_DEBOUNCE_MS = 400;
  figma.showUI(__html__, { width: 280, height: 360, themeColors: true });
  function post(message) {
    figma.ui.postMessage(message);
  }
  function selectedNode() {
    const selection = figma.currentPage.selection;
    if (selection.length === 0) return { node: null, reason: "Select a frame" };
    if (selection.length > 1) return { node: null, reason: "Select a single frame" };
    const node = selection[0];
    if (!("exportAsync" in node)) return { node: null, reason: "This layer can't be exported" };
    if (node.width < 1 || node.height < 1) return { node: null, reason: "Frame has no size" };
    return { node, reason: "" };
  }
  function info(node) {
    return { id: node.id, name: node.name, width: node.width, height: node.height };
  }
  function sendSelection() {
    const { node, reason } = selectedNode();
    post({ type: "selection", frame: node ? info(node) : null, reason });
  }
  var autoPush = false;
  var busy = false;
  var pending = false;
  var debounce;
  async function exportSelection(auto) {
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
        useAbsoluteBounds: true
      });
      post({ type: "exported", frame, bytes, scale: EXPORT_SCALE, auto });
    } catch (err) {
      busy = false;
      post({ type: "export-error", message: String(err), auto });
    }
  }
  function requestAutoPush() {
    if (!autoPush) return;
    if (debounce !== void 0) clearTimeout(debounce);
    debounce = setTimeout(() => {
      debounce = void 0;
      if (busy) {
        pending = true;
      } else {
        exportSelection(true);
      }
    }, AUTO_PUSH_DEBOUNCE_MS);
  }
  function isInside(node, ancestorId) {
    for (let n = node; n; n = n.parent) {
      if (n.id === ancestorId) return true;
    }
    return false;
  }
  function onNodeChange(event) {
    if (!autoPush) return;
    const { node } = selectedNode();
    if (!node) return;
    const touched = event.nodeChanges.some(
      (change) => change.type === "DELETE" || isInside(change.node, node.id)
    );
    if (touched) requestAutoPush();
  }
  var watchedPage = figma.currentPage;
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
  figma.ui.onmessage = (message) => {
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
})();
