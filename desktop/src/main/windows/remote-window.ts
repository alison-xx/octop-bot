import { BrowserWindow, session } from "electron";

import { BOT_HOME_PATH, BOT_PRODUCT_NAME } from "../../shared/product";
import { installDashboardGuards } from "./main-window";
import { allowRemotePermission } from "./remote-permissions";
import { DEFAULT_WINDOW_SIZE, minimumWindowSize } from "./size";

/**
 * The Bot web app of a self-hosted server, shown in a normal window. It gets no
 * preload: a page from the network never reaches the desktop bridge (files,
 * local service, updates). Navigation stays on that origin; other links open
 * in the system browser.
 */
export function createRemoteWindow(options: {
  origin: string;
  backgroundColor: string;
  icon?: string;
  onNavigate: (url: string) => void;
  onLoadFailed: (description: string) => void;
}): BrowserWindow {
  const minimum = minimumWindowSize(true);
  session.defaultSession.setPermissionRequestHandler((contents, permission, callback, details) => {
    const mediaTypes = "mediaTypes" in details ? details.mediaTypes : undefined;
    callback(
      !contents.isDestroyed() &&
        allowRemotePermission({ origin: options.origin, requestingUrl: details.requestingUrl, permission, mediaTypes }),
    );
  });
  const win = new BrowserWindow({
    title: BOT_PRODUCT_NAME,
    icon: options.icon,
    width: DEFAULT_WINDOW_SIZE.width,
    height: DEFAULT_WINDOW_SIZE.height,
    minWidth: minimum.width,
    minHeight: minimum.height,
    show: false,
    backgroundColor: options.backgroundColor,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      webSecurity: true,
    },
  });
  win.on("page-title-updated", (event) => event.preventDefault());
  installDashboardGuards(win, { appOrigin: options.origin, onNavigate: options.onNavigate, botOnly: true });
  win.webContents.on("did-fail-load", (_event, code, description, _url, isMainFrame) => {
    // -3 is an aborted load (a redirect or a newer navigation), not a failure.
    if (isMainFrame && code !== -3) options.onLoadFailed(description);
  });
  win.once("ready-to-show", () => win.show());
  void win.loadURL(options.origin + BOT_HOME_PATH);
  return win;
}
