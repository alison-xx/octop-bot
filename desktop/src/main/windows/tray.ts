import { join } from "node:path";

/**
 * Notification-area icon. The dashboard close button hides the window; this
 * icon opens it again. macOS uses the Dock for the same job. Windows uses the
 * notification area. Linux (UOS included) uses the panel tray at the bottom
 * right.
 *
 * Matches `appId` in `electron-builder.config.ts`. Windows groups the tray
 * icon and the taskbar button under this id.
 */
export const WINDOWS_APP_USER_MODEL_ID = "com.tencent.octop";

export function shouldInstallSystemTray(platform: string): boolean {
  return platform === "win32" || platform === "linux";
}

export interface TrayIconCandidates {
  platform: string;
  isPackaged: boolean;
  resourcesDir: string;
  execPath: string;
  botOnly?: boolean;
}

/**
 * Dev and packaged builds both keep a loose icon next to the app (the package
 * copies it into resources). Windows uses `icon.ico`; the executable is only
 * a Shell-icon fallback when that ico is missing. Linux uses `icon.png` —
 * the panel tray does not read an ico.
 */
export function trayIconCandidates(input: TrayIconCandidates): string[] {
  if (input.platform === "linux") {
    const standard = join(input.resourcesDir, "icon.png");
    return input.botOnly ? [join(input.resourcesDir, "bot-icon.png"), standard] : [standard];
  }
  if (input.platform !== "win32") return [];
  const bundled = join(input.resourcesDir, "icon.ico");
  const candidates = input.botOnly
    ? [join(input.resourcesDir, "bot-tray.ico"), join(input.resourcesDir, "bot-icon.ico"), join(input.resourcesDir, "bot-icon.png")]
    : [bundled];
  return input.isPackaged ? [...candidates, input.execPath] : candidates;
}

/** First real image file among the candidates. Skips the executable fallback. */
export function trayIconImagePath(
  candidates: readonly string[],
  exists: (path: string) => boolean,
): string | null {
  for (const candidate of candidates) {
    if (candidate.toLowerCase().endsWith(".exe")) continue;
    if (exists(candidate)) return candidate;
  }
  return null;
}

/** Packaged executable, for `app.getFileIcon` when the ico file is absent. */
export function trayExecutableFallback(candidates: readonly string[]): string | null {
  return candidates.find((candidate) => candidate.toLowerCase().endsWith(".exe")) ?? null;
}

export interface TrayMenuLabels {
  show: string;
  quit: string;
}

export function trayMenuLabels(locale: string, botOnly = false): TrayMenuLabels {
  if (locale.toLowerCase().startsWith("zh")) {
    if (botOnly) return { show: "打开 Octop Bot", quit: "退出 Octop Bot" };
    return { show: "显示窗口", quit: "退出" };
  }
  return botOnly ? { show: "Open Octop Bot", quit: "Quit Octop Bot" } : { show: "Show window", quit: "Quit" };
}
