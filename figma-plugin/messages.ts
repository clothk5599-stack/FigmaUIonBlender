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

export const BRIDGE_URL = "http://127.0.0.1:8765";
export const EXPORT_SCALE = 1;
