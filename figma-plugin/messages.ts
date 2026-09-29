// Messages between the plugin sandbox (code.ts) and the UI iframe (ui.ts).

export interface FrameInfo {
  id: string;
  name: string;
  width: number;
  height: number;
}

export type MainToUI =
  | { type: "selection"; frame: FrameInfo | null; reason: string }
  | { type: "exporting"; frame: FrameInfo; auto: boolean }
  | {
      type: "exported";
      frame: FrameInfo;
      bytes: Uint8Array;
      scale: number;
      auto: boolean;
    }
  | { type: "export-error"; message: string; auto: boolean };

export type UIToMain =
  | { type: "push" }
  | { type: "set-auto"; enabled: boolean }
  | { type: "push-finished" };

// The Blender add-on (or the optional bridge) listens here. Must be
// "localhost": Figma rejects IP addresses in manifest.json's devAllowedDomains.
export const BRIDGE_URL = "http://localhost:8765";
export const EXPORT_SCALE = 1;
