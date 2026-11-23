import { contextBridge, ipcRenderer } from "electron";

/** The "Connect to a server" window. It can only ask the main process to check and switch. */
const server = {
  state(): Promise<{ current: string | null; recent: string[] }> {
    return ipcRenderer.invoke("octop:server:state");
  },
  connect(address: string): Promise<{ ok: true } | { ok: false; reason: string }> {
    return ipcRenderer.invoke("octop:server:connect", address);
  },
  useLocal(): Promise<void> {
    return ipcRenderer.invoke("octop:server:local");
  },
  close(): void {
    ipcRenderer.send("octop:server:close");
  },
};

contextBridge.exposeInMainWorld("octopServer", server);
export type ServerBridge = typeof server;
