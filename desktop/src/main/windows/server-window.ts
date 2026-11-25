import { join } from "node:path";
import { BrowserWindow, ipcMain, net, type IpcMainEvent, type IpcMainInvokeEvent } from "electron";

import { isLoopbackHost, normalizeServerAddress, probeServer, type ServerChoiceStore } from "../server/server-choice";

/**
 * "Connect to a server": a small shell page that checks an address and, when an
 * Octop server answers there, saves it and restarts the app on that server.
 * Only this window's page may call these handlers.
 */
export class ServerPicker {
  private win: BrowserWindow | null = null;
  private readonly store: ServerChoiceStore;
  private readonly restart: () => void;
  private readonly icon: string | undefined;

  /** `allowLoopback`: development runs may point at a test server on this computer. */
  constructor(options: { store: ServerChoiceStore; restart: () => void; icon?: string; allowLoopback: boolean }) {
    this.store = options.store;
    this.restart = options.restart;
    this.icon = options.icon;
    const own = (event: IpcMainEvent | IpcMainInvokeEvent) =>
      this.win !== null && !this.win.isDestroyed() && event.sender === this.win.webContents;
    ipcMain.handle("octop:server:state", (event) => (own(event) ? this.store.load() : null));
    ipcMain.handle("octop:server:connect", async (event, address: unknown) => {
      if (!own(event)) return { ok: false, reason: "invalid" };
      const checked = normalizeServerAddress(typeof address === "string" ? address : "");
      if (!checked.ok) return checked;
      if (!options.allowLoopback && isLoopbackHost(new URL(checked.origin).hostname)) {
        return { ok: false, reason: "loopback" };
      }
      const probed = await probeServer(checked.origin, (url, init) => net.fetch(url, init));
      if (!probed.ok) return probed;
      this.switchTo(checked.origin);
      return { ok: true };
    });
    ipcMain.handle("octop:server:local", (event) => {
      if (own(event)) this.switchTo(null);
    });
    ipcMain.on("octop:server:close", (event) => {
      if (own(event)) this.win?.close();
    });
  }

  /** Use this origin (null = this computer's service) and restart there, unless it is already in use. */
  switchTo(origin: string | null): void {
    const unchanged = this.store.load().current === origin;
    this.store.select(origin);
    this.win?.close();
    if (!unchanged) this.restart();
  }

  open(parent?: BrowserWindow | null): void {
    if (this.win && !this.win.isDestroyed()) {
      this.win.show();
      this.win.focus();
      return;
    }
    const win = new BrowserWindow({
      width: 460,
      height: 400,
      resizable: false,
      minimizable: false,
      maximizable: false,
      fullscreenable: false,
      show: false,
      icon: this.icon,
      parent: parent && !parent.isDestroyed() ? parent : undefined,
      modal: Boolean(parent && !parent.isDestroyed() && process.platform === "darwin"),
      autoHideMenuBar: true,
      webPreferences: {
        preload: join(__dirname, "../preload/server.js"),
        nodeIntegration: false,
        contextIsolation: true,
        sandbox: true,
        webSecurity: true,
      },
    });
    win.setMenuBarVisibility(false);
    win.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
    win.webContents.on("will-navigate", (event) => event.preventDefault());
    win.once("ready-to-show", () => win.show());
    win.on("closed", () => {
      if (this.win === win) this.win = null;
    });
    this.win = win;
    void win.loadFile(join(__dirname, "../renderer/server.html"));
  }
}
