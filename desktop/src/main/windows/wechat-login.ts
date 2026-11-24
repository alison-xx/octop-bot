import { randomUUID } from "node:crypto";
import { BrowserWindow, session } from "electron";
import type { WechatLoginResult } from "../../shared/ipc-contract";

export function validWechatUrls(qrUrl: string, redirectUri: string): boolean {
  try {
    const qr = new URL(qrUrl);
    const redirect = new URL(redirectUri);
    return qr.protocol === "https:" && qr.hostname === "open.weixin.qq.com" && !qr.username && !qr.password && redirect.protocol === "https:" && !!redirect.hostname && !redirect.username && !redirect.password;
  } catch {
    return false;
  }
}

export function readWechatLanding(url: string, redirectUri: string): WechatLoginResult | null {
  try {
    const parsed = new URL(url);
    const redirect = new URL(redirectUri);
    if (redirect.protocol !== "https:" || parsed.origin !== redirect.origin || parsed.pathname !== redirect.pathname) return null;
    const code = parsed.searchParams.get("code");
    const state = parsed.searchParams.get("state");
    if (code && state) return { ok: true, code, state };
    return { ok: false, reason: parsed.searchParams.get("error") === "access_denied" ? "denied" : "failed" };
  } catch {
    return null;
  }
}

let pending: { win: BrowserWindow; result: Promise<WechatLoginResult> } | null = null;
export function openWechatLogin(parent: BrowserWindow | null, zh: boolean, qrUrl: string, redirectUri: string): Promise<WechatLoginResult> {
  if (typeof qrUrl !== "string" || typeof redirectUri !== "string" || !validWechatUrls(qrUrl, redirectUri)) return Promise.resolve({ ok: false, reason: "failed" });
  if (pending && !pending.win.isDestroyed()) {
    pending.win.focus();
    return pending.result;
  }
  const partition = session.fromPartition(`wechat-login-${randomUUID()}`);
  const win = new BrowserWindow({ parent: parent ?? undefined, width: 480, height: 720, title: zh ? "微信登录" : "Sign in with WeChat", autoHideMenuBar: true, minimizable: false, fullscreenable: false, webPreferences: { session: partition, contextIsolation: true, sandbox: true, nodeIntegration: false } });
  const result = new Promise<WechatLoginResult>((resolve) => {
    let settled = false;
    const finish = (outcome: WechatLoginResult) => {
      if (settled) return;
      settled = true;
      resolve(outcome);
      if (!win.isDestroyed()) win.close();
    };
    const intercept = (event: { preventDefault(): void }, url: string) => {
      const outcome = readWechatLanding(url, redirectUri);
      if (outcome) { event.preventDefault(); finish(outcome); }
    };
    const redirect = new URL(redirectUri);
    partition.webRequest.onBeforeRequest({ urls: [`${redirect.origin}/*`] }, (details, callback) => {
      const outcome = readWechatLanding(details.url, redirectUri);
      callback({ cancel: outcome !== null });
      if (outcome) finish(outcome);
    });
    win.webContents.on("will-redirect", intercept);
    win.webContents.on("will-navigate", intercept);
    win.webContents.setWindowOpenHandler(({ url }) => {
      const outcome = readWechatLanding(url, redirectUri);
      if (outcome) finish(outcome);
      // Only WeChat's own pages may replace the QR page inside this window.
      else if (/^https:\/\/([a-z0-9-]+\.)*qq\.com\//i.test(url)) void win.loadURL(url);
      return { action: "deny" };
    });
    win.webContents.on("page-title-updated", (event) => event.preventDefault());
    win.once("closed", () => { finish({ ok: false, reason: "cancelled" }); void partition.clearStorageData(); pending = null; });
    win.loadURL(qrUrl).catch((err: unknown) => { if ((err as { code?: string }).code !== "ERR_ABORTED") finish({ ok: false, reason: "failed" }); });
  });
  pending = { win, result };
  return result;
}
