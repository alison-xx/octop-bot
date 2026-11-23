import { randomUUID } from "node:crypto";
import { BrowserWindow, session } from "electron";

import type { WorkbuddyLoginResult } from "../../shared/ipc-contract";

/**
 * WorkBuddy sign-in through Lynxce, which is registered with WorkBuddy's open
 * platform. Lynxce finishes the OAuth exchange and redirects to its web site's
 * landing page with a one-time hand-off code. This window stops that redirect
 * before the web page can spend the code and gives the code to the Bot page,
 * which exchanges it through the local server for a Lynxce session.
 */
// The "agent" site is Lynxce's Buddy app that is configured in production
// (2026-11-23: /api/oauth/workbuddy/config?site=web-assistant reports disabled).
export const WORKBUDDY_START_URL =
  "https://api.lynxce.cn/api/oauth/workbuddy/start?site=agent&returnTo=%2F";

const LANDING_HOSTS = ["web.lynxce.cn", "agent.lynxce.cn"];
const LANDING_URLS = LANDING_HOSTS.map((host) => `https://${host}/oauth/workbuddy*`);
const HANDOFF = /^wb-handoff\.[A-Za-z0-9_-]{16,1024}\.[A-Za-z0-9_-]{43}$/;

/** The outcome carried by Lynxce's landing URL, or null for any other address. */
export function readWorkbuddyLanding(url: string): WorkbuddyLoginResult | null {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return null;
  }
  if (
    parsed.protocol !== "https:" ||
    !LANDING_HOSTS.includes(parsed.hostname) ||
    parsed.pathname.replace(/\/+$/, "") !== "/oauth/workbuddy"
  ) {
    return null;
  }
  const code = parsed.searchParams.get("code") ?? "";
  if (HANDOFF.test(code)) return { ok: true, code };
  return { ok: false, reason: parsed.searchParams.get("error") === "authorize_denied" ? "denied" : "failed" };
}

let pending: { win: BrowserWindow; result: Promise<WorkbuddyLoginResult> } | null = null;

/** One sign-in window at a time; a second request focuses it and shares its result. */
export function openWorkbuddyLogin(parent: BrowserWindow | null, zh: boolean): Promise<WorkbuddyLoginResult> {
  if (pending && !pending.win.isDestroyed()) {
    pending.win.focus();
    return pending.result;
  }
  // In-memory partition: WorkBuddy and Lynxce cookies end with the window.
  const partition = session.fromPartition(`workbuddy-login-${randomUUID()}`);
  const win = new BrowserWindow({
    parent: parent ?? undefined,
    width: 480,
    height: 720,
    title: zh ? "用 WorkBuddy 账号登录" : "Sign in with WorkBuddy",
    autoHideMenuBar: true,
    minimizable: false,
    fullscreenable: false,
    webPreferences: {
      session: partition,
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
    },
  });
  const result = new Promise<WorkbuddyLoginResult>((resolve) => {
    let settled = false;
    const finish = (outcome: WorkbuddyLoginResult) => {
      if (settled) return;
      settled = true;
      resolve(outcome);
      if (!win.isDestroyed()) win.close();
    };
    const intercept = (event: { preventDefault(): void }, url: string) => {
      const outcome = readWorkbuddyLanding(url);
      if (!outcome) return;
      event.preventDefault();
      finish(outcome);
    };
    partition.webRequest.onBeforeRequest({ urls: LANDING_URLS }, (details, callback) => {
      const outcome = readWorkbuddyLanding(details.url);
      callback({ cancel: outcome !== null });
      if (outcome) finish(outcome);
    });
    win.webContents.on("will-redirect", intercept);
    win.webContents.on("will-navigate", intercept);
    // Keep sign-in pop-ups (QR or app hand-offs) in this window instead of new ones.
    win.webContents.setWindowOpenHandler(({ url }) => {
      if (url.startsWith("https://")) void win.loadURL(url);
      return { action: "deny" };
    });
    win.webContents.on("page-title-updated", (event) => event.preventDefault());
    win.once("closed", () => {
      finish({ ok: false, reason: "cancelled" });
      void partition.clearStorageData();
      pending = null;
    });
    win.loadURL(WORKBUDDY_START_URL).catch((err: unknown) => {
      // A sign-in page that moves on before its first load finishes is not a failure.
      if ((err as { code?: string }).code !== "ERR_ABORTED") finish({ ok: false, reason: "failed" });
    });
  });
  pending = { win, result };
  return result;
}
