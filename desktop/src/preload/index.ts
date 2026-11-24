import { contextBridge, ipcRenderer, type IpcRendererEvent } from "electron";
import { BOT_CLIENT_FLAG } from "../shared/product";
import {
  IPC_CHANNELS,
  type BotNotification,
  type BotShortcut,
  type BotUpdateStatus,
  type ClientSettings,
  type IssuedSession,
  type PlatformInfo,
  type UpdateCheckResult,
  type WindowChromeTheme,
  type WorkbuddyLoginResult,
  type WsRelayEndpoint,
} from "../shared/ipc-contract";

/**
 * Minimal, typed bridge exposed to the sandboxed renderer as ``window.octopDesktop``.
 * No raw ipcRenderer, no file system, no shell execution, no arbitrary URLs.
 */

function subscribe<T>(channel: string, cb: (payload: T) => void): () => void {
  const listener = (_event: IpcRendererEvent, payload: T) => cb(payload);
  ipcRenderer.on(channel, listener);
  return () => ipcRenderer.removeListener(channel, listener);
}

/**
 * Read once and memoise: the relay binds before the window loads, so the value
 * cannot change during a launch, and URL builders call this from render paths
 * where awaiting is not an option.
 */
let wsEndpointCache: WsRelayEndpoint | null | undefined;

const botOnly = process.argv.includes(BOT_CLIENT_FLAG);
let settingsRequestPending = false;
let openBotSettings: (() => void) | null = null;
let pendingShortcut: BotShortcut | null = null;
let botShortcut: ((action: BotShortcut) => void) | null = null;
let notificationOpen: ((target: string) => void) | null = null;
let pendingNotificationTarget: string | null = null;
if (botOnly) {
  ipcRenderer.on(IPC_CHANNELS.botShortcut, (_event, action: BotShortcut) => {
    if (botShortcut) botShortcut(action);
    else pendingShortcut = action;
  });
  ipcRenderer.on(IPC_CHANNELS.botNotificationOpen, (_event, target: string) => {
    if (notificationOpen) notificationOpen(target);
    else pendingNotificationTarget = target;
  });
  ipcRenderer.on(IPC_CHANNELS.openBotSettings, () => {
    if (openBotSettings) openBotSettings();
    else settingsRequestPending = true;
  });
}

const bridge = {
  botOnly,
  showBotOrb() { if (botOnly) ipcRenderer.send(IPC_CHANNELS.showBotOrb); },
  onBotShortcut(callback: (action: BotShortcut) => void): () => void {
    botShortcut = callback;
    if (pendingShortcut) {
      const action = pendingShortcut;
      pendingShortcut = null;
      callback(action);
    }
    return () => { if (botShortcut === callback) botShortcut = null; };
  },
  /** OS notification plus dock bounce / taskbar flash for a new reply. */
  notify(note: BotNotification): void {
    if (botOnly) ipcRenderer.send(IPC_CHANNELS.botNotify, note);
  },
  /** Unread total on the app icon (macOS, Linux) and in the tray tooltip. */
  setUnreadBadge(count: number): void {
    if (botOnly) ipcRenderer.send(IPC_CHANNELS.botUnreadBadge, count);
  },
  /** ``bot:<id>`` / ``group:<id>`` of a clicked notification, including one clicked before the page subscribed. */
  onNotificationOpen(callback: (target: string) => void): () => void {
    notificationOpen = callback;
    if (pendingNotificationTarget) {
      const target = pendingNotificationTarget;
      pendingNotificationTarget = null;
      callback(target);
    }
    return () => {
      if (notificationOpen === callback) notificationOpen = null;
    };
  },
  /** Open the WorkBuddy sign-in window; resolves with Lynxce's one-time hand-off code. */
  workbuddyLogin(): Promise<WorkbuddyLoginResult> {
    if (!botOnly) return Promise.resolve({ ok: false, reason: "failed" });
    return ipcRenderer.invoke(IPC_CHANNELS.botWorkbuddyLogin);
  },
  /** Restart on the Octop Bot cloud, signed in with ``accessToken`` (from the local move). */
  useLynxceCloud(accessToken: string): Promise<boolean> {
    if (!botOnly) return Promise.resolve(false);
    return ipcRenderer.invoke(IPC_CHANNELS.botUseCloud, accessToken);
  },
  onOpenBotSettings(callback: () => void): () => void {
    openBotSettings = callback;
    if (settingsRequestPending) {
      settingsRequestPending = false;
      callback();
    }
    return () => {
      if (openBotSettings === callback) openBotSettings = null;
    };
  },
  getPlatformInfo(): Promise<PlatformInfo> {
    return ipcRenderer.invoke(IPC_CHANNELS.getPlatformInfo);
  },
  openDirectoryPicker(): Promise<string | null> {
    return ipcRenderer.invoke(IPC_CHANNELS.openDirectoryPicker);
  },
  openFilePicker(): Promise<string | null> {
    return ipcRenderer.invoke(IPC_CHANNELS.openFilePicker);
  },
  onBackendReady(callback: (ready: { ok: boolean }) => void): () => void {
    return subscribe(IPC_CHANNELS.onBackendReady, callback);
  },
  /**
   * Report the page theme so the *native* window controls (traffic lights,
   * Windows caption buttons) match it. Linux draws its own square buttons and
   * drives them through ``windowControls``.
   */
  setWindowChrome(theme: WindowChromeTheme): void {
    ipcRenderer.send(IPC_CHANNELS.windowChromeTheme, theme);
  },
  /**
   * Linux caption buttons. The shell ignores these on macOS and Windows, where
   * the buttons stay native.
   */
  windowControls: {
    minimize(): void {
      ipcRenderer.send(IPC_CHANNELS.windowMinimize);
    },
    toggleMaximize(): void {
      ipcRenderer.send(IPC_CHANNELS.windowToggleMaximize);
    },
    close(): void {
      ipcRenderer.send(IPC_CHANNELS.windowClose);
    },
    isMaximized(): Promise<boolean> {
      return ipcRenderer.invoke(IPC_CHANNELS.windowIsMaximized);
    },
    onMaximizedChange(callback: (maximized: boolean) => void): () => void {
      return subscribe(IPC_CHANNELS.windowMaximized, callback);
    },
  },
  /**
   * Windows draws no native menu bar under the transparent caption, so the
   * page draws the titles and the submenus, then asks the shell to run a command.
   */
  windowsMenu: {
    model(): Promise<{
      titles: string[];
      menus: Array<Array<{ kind: "separator" } | { kind: "command"; id: string; label: string; accelerator: string | null }>>;
    } | null> {
      return ipcRenderer.invoke(IPC_CHANNELS.windowsMenuModel);
    },
    invoke(id: string): Promise<void> {
      return ipcRenderer.invoke(IPC_CHANNELS.windowsMenuInvoke, id);
    },
  },
  /**
   * Full screen hides the macOS traffic lights, so the page stops reserving
   * room for them. Fires only on change; the app never starts full screen.
   */
  onWindowFullscreenChange(callback: (fullscreen: boolean) => void): () => void {
    return subscribe(IPC_CHANNELS.windowChromeFullscreen, callback);
  },
  clientSettings: {
    get(): Promise<ClientSettings> {
      return ipcRenderer.invoke(IPC_CHANNELS.clientSettingsGet);
    },
    set(patch: Partial<ClientSettings>): Promise<ClientSettings> {
      return ipcRenderer.invoke(IPC_CHANNELS.clientSettingsSet, patch);
    },
  },
  /**
   * Where to dial WebSockets (§5.2). ``null`` when the shell has no relay, in
   * which case the Dashboard keeps deriving the address from the page origin.
   */
  wsEndpoint(): WsRelayEndpoint | null {
    if (wsEndpointCache === undefined) {
      wsEndpointCache = (ipcRenderer.sendSync(IPC_CHANNELS.wsEndpoint) as WsRelayEndpoint | null) ?? null;
    }
    return wsEndpointCache;
  },
  checkForUpdates(): Promise<UpdateCheckResult> {
    return ipcRenderer.invoke(IPC_CHANNELS.checkForUpdates);
  },
  installUpdate(): Promise<void> {
    return ipcRenderer.invoke(IPC_CHANNELS.installUpdate);
  },
  /**
   * Octop Bot background updates. The page reads the state and asks for a
   * check or the install; it can never name a package (the shell selects it).
   */
  botUpdates: botOnly
    ? {
        state(): Promise<BotUpdateStatus> {
          return ipcRenderer.invoke(IPC_CHANNELS.botUpdateState);
        },
        check(): Promise<BotUpdateStatus> {
          return ipcRenderer.invoke(IPC_CHANNELS.botUpdateCheck);
        },
        apply(): Promise<void> {
          return ipcRenderer.invoke(IPC_CHANNELS.botUpdateApply);
        },
        onChange(callback: (status: BotUpdateStatus) => void): () => void {
          return subscribe(IPC_CHANNELS.botUpdateChanged, callback);
        },
      }
    : undefined,
  /**
   * Device session (§7 accounts). The renderer can ask for a JWT, but the
   * credential behind it never crosses this bridge.
   */
  session: {
    register(accessToken: string): Promise<boolean> {
      return ipcRenderer.invoke(IPC_CHANNELS.sessionRegister, accessToken);
    },
    renew(): Promise<IssuedSession | null> {
      return ipcRenderer.invoke(IPC_CHANNELS.sessionRenew);
    },
    revoke(accessToken: string): Promise<boolean> {
      return ipcRenderer.invoke(IPC_CHANNELS.sessionRevoke, accessToken);
    },
  },
} as const;

export type OctopDesktopBridge = typeof bridge;

contextBridge.exposeInMainWorld("octopDesktop", bridge);

// The failure page's Retry lives in this same window (the splash is not a
// second BrowserWindow). Restart stays off `octopDesktop`. The channel string
// matches `EARLY_IPC.restart`; importing that module would split this preload.
contextBridge.exposeInMainWorld("octopShell", {
  restart(): void {
    ipcRenderer.send("octop:early-restart");
  },
});
