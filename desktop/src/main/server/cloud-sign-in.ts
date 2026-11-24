import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";

import { LYNXCE_CLOUD_ORIGIN, normalizeServerAddress } from "./server-choice";

/**
 * Signing in with Lynxce on the desktop moves the app to the Octop Bot cloud. The local
 * service hands its Lynxce sign-in to the cloud and gets a cloud access token back; the
 * shell keeps it here across the restart and gives it to the cloud page once, so the user
 * does not sign in twice. The file is the user's own (0600) and deleted when read.
 */

export interface PendingCloudSignIn {
  origin: string;
  accessToken: string;
}

const TOKEN = /^[A-Za-z0-9._~+/=-]{16,8192}$/;

/** The cloud this app moves to: bot.lynxce.cn, or ``OCTOP_BOT_CLOUD_ORIGIN`` when testing. */
export function cloudOrigin(env: NodeJS.ProcessEnv = process.env): string {
  const override = env.OCTOP_BOT_CLOUD_ORIGIN?.trim();
  if (override) {
    const checked = normalizeServerAddress(override);
    if (checked.ok) return checked.origin;
  }
  return LYNXCE_CLOUD_ORIGIN;
}

export function isCloudAccessToken(value: unknown): value is string {
  return typeof value === "string" && TOKEN.test(value);
}

export function pendingCloudSignInPath(userDataDir: string): string {
  return join(userDataDir, "cloud-sign-in.json");
}

export function savePendingCloudSignIn(filePath: string, pending: PendingCloudSignIn): void {
  mkdirSync(dirname(filePath), { recursive: true });
  writeFileSync(filePath, JSON.stringify(pending), { encoding: "utf8", mode: 0o600 });
}

/** The sign-in waiting for ``origin``, removed from disk either way. */
export function takePendingCloudSignIn(filePath: string, origin: string): string | null {
  if (!existsSync(filePath)) return null;
  let pending: Partial<PendingCloudSignIn> = {};
  try {
    pending = JSON.parse(readFileSync(filePath, "utf8")) as Partial<PendingCloudSignIn>;
  } catch {
    pending = {};
  }
  rmSync(filePath, { force: true });
  return pending.origin === origin && isCloudAccessToken(pending.accessToken) ? pending.accessToken : null;
}

/** Page script that stores the token the way the Dashboard does and opens the Bot home. */
export function cloudSignInScript(accessToken: string): string {
  return `localStorage.setItem("auth_token", ${JSON.stringify(accessToken)}); location.replace("/octop-bot");`;
}
