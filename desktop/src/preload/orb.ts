import { contextBridge, ipcRenderer } from "electron";

const orb = {
  pointer(action: "start" | "move" | "end" | "menu", dx = 0, dy = 0) {
    // A sandboxed preload must remain a single bundle.
    ipcRenderer.send("octop:orb:pointer", action, dx, dy);
  },
};

contextBridge.exposeInMainWorld("botOrb", orb);
export type OrbBridge = typeof orb;
