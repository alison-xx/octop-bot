/**
 * macOS privacy grants the Bot's computer needs. The sidecar runs as a child of
 * this app, so a grant to Octop Bot covers the screen stream and app control too.
 * Nothing here runs until the person asks for it from the Bot's computer card.
 */
export type MacPermission = "screen_recording" | "accessibility";

const SETTINGS_PANE: Record<MacPermission, string> = {
  screen_recording:
    "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
  accessibility:
    "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
};

export interface MacPermissionDeps {
  platform: NodeJS.Platform;
  /** Electron ``systemPreferences.getMediaAccessStatus("screen")``. */
  screenStatus(): string;
  /** Electron ``systemPreferences.isTrustedAccessibilityClient(prompt)``. */
  accessibilityTrusted(prompt: boolean): boolean;
  /** A one-off screen source query, which lists the app under Screen Recording. */
  touchScreenCapture(): Promise<unknown>;
  openSettings(url: string): Promise<void>;
}

export function isMacPermission(value: unknown): value is MacPermission {
  return value === "screen_recording" || value === "accessibility";
}

/**
 * Ask for one grant: macOS shows its own prompt the first time and lists the
 * app in System Settings; the matching settings pane opens whenever the grant
 * is still missing. Resolves true when it is already granted.
 */
export async function requestMacPermission(
  kind: MacPermission,
  deps: MacPermissionDeps,
): Promise<boolean> {
  if (deps.platform !== "darwin") return true;
  if (kind === "accessibility") {
    if (deps.accessibilityTrusted(true)) return true;
  } else {
    if (deps.screenStatus() === "granted") return true;
    await deps.touchScreenCapture().catch(() => undefined);
  }
  await deps.openSettings(SETTINGS_PANE[kind]);
  return false;
}
