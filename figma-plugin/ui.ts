// Plugin UI iframe: shows connection + selection state and uploads exported
// frames to Blender (the add-on listens on localhost; or the optional bridge).

import { BRIDGE_URL, FrameInfo, MainToUI, UIToMain } from "./messages";

const STATUS_POLL_MS = 2000;

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const connectionDot = $<HTMLSpanElement>("connection-dot");
const connectionText = $<HTMLSpanElement>("connection-text");
const frameName = $<HTMLDivElement>("frame-name");
const frameSize = $<HTMLDivElement>("frame-size");
const pushButton = $<HTMLButtonElement>("push");
const autoPush = $<HTMLInputElement>("auto-push");
const message = $<HTMLDivElement>("message");

let connected = false;
let frame: FrameInfo | null = null;
let busy = false;

function send(msg: UIToMain) {
  parent.postMessage({ pluginMessage: msg }, "*");
}

function formatSize(n: number) {
  return Number.isInteger(n) ? String(n) : n.toFixed(2).replace(/\.?0+$/, "");
}

function setMessage(text: string, kind: "info" | "ok" | "error" = "info") {
  message.textContent = text;
  message.className = `message ${kind}`;
}

function render() {
  connectionDot.className = `dot ${connected ? "on" : "off"}`;
  connectionText.textContent = connected ? "Connected to Blender" : "Blender not listening";
  pushButton.disabled = !frame || busy;
  pushButton.textContent = busy ? "Pushing…" : "Push to Blender";
}

async function checkBlender() {
  try {
    const response = await fetch(`${BRIDGE_URL}/status`, { cache: "no-store" });
    connected = response.ok;
  } catch {
    connected = false;
  }
  render();
}

async function upload(msg: Extract<MainToUI, { type: "exported" }>) {
  const form = new FormData();
  form.append("image", new Blob([msg.bytes as BlobPart], { type: "image/png" }), "frame.png");
  form.append("name", msg.frame.name);
  form.append("width", String(msg.frame.width));
  form.append("height", String(msg.frame.height));
  form.append("scale", String(msg.scale));
  form.append("updatedAt", String(Date.now() / 1000));
  try {
    const response = await fetch(`${BRIDGE_URL}/ui`, { method: "POST", body: form });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(result.detail ? String(result.detail) : `HTTP ${response.status}`);
    }
    connected = true;
    const time = new Date().toLocaleTimeString();
    setMessage(`${msg.auto ? "Auto-pushed" : "Pushed"} v${result.version} at ${time}`, "ok");
  } catch (err) {
    connected = false;
    setMessage(`Push failed: ${err instanceof Error ? err.message : String(err)}. ` +
      "Is Blender open with the add-on started?", "error");
  } finally {
    busy = false;
    send({ type: "push-finished" });
    render();
  }
}

window.onmessage = (event: MessageEvent) => {
  const msg = event.data.pluginMessage as MainToUI | undefined;
  if (!msg) return;
  switch (msg.type) {
    case "selection":
      frame = msg.frame;
      frameName.textContent = frame ? frame.name : msg.reason;
      frameName.classList.toggle("muted", !frame);
      frameSize.textContent = frame
        ? `${formatSize(frame.width)} × ${formatSize(frame.height)}`
        : "—";
      break;
    case "exporting":
      busy = true;
      setMessage(`Exporting ${msg.frame.name}…`);
      break;
    case "exported":
      upload(msg);
      break;
    case "export-error":
      busy = false;
      setMessage(msg.message, "error");
      break;
  }
  render();
};

pushButton.onclick = () => send({ type: "push" });
autoPush.onchange = () => send({ type: "set-auto", enabled: autoPush.checked });

checkBlender();
setInterval(checkBlender, STATUS_POLL_MS);
render();
