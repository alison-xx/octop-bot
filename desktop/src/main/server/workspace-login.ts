import { app, BrowserWindow, session } from "electron";
import { randomUUID } from "node:crypto";
import { cloudOrigin } from "./cloud-sign-in";
import { isLoopbackHost, LYNXCE_CLOUD_ORIGIN } from "./server-choice";

const routes = new Map([
  ["password", "login"],
  ["sendCode", "code"],
  ["code", "code-login"],
  ["bind", "web-login/bind"],
]);

async function request(path: string, body?: Record<string, string>) {
  const origin = cloudOrigin();
  if (
    origin !== LYNXCE_CLOUD_ORIGIN &&
    (app.isPackaged || !isLoopbackHost(new URL(origin).hostname))
  )
    throw new Error("Invalid workspace sign-in origin");
  const response = await fetch(origin + "/api/auth/lynxce/" + path, {
    method: body ? "POST" : "GET",
    headers: { "Content-Type": "application/json" },
    body: body && JSON.stringify(body),
    redirect: "error",
    signal: AbortSignal.timeout(45000),
  });
  const data = await response.json();
  return { status: response.status, data };
}

export async function workspaceLogin(
  parent: BrowserWindow,
  action: string,
  body: Record<string, string>,
) {
  const route = routes.get(action);
  if (route) return request(route, body);
  if (action !== "wechat" && action !== "workbuddy")
    throw new Error("Unknown login method");
  const config = await request("web-login/config?provider=" + action);
  if (config.status !== 200) return config;
  const { enabled, url, state, callbackState } = config.data;
  if (!enabled || !state || typeof url !== "string")
    throw new Error("Login provider unavailable");
  const start = new URL(url);
  if (
    !/^https:\/\/web\.lynxce\.cn\/oauth\/site\?request=ocr1\.[\w.-]+$/.test(
      url,
    ) ||
    !/^[\w-]{43}$/.test(state) ||
    !callbackState ||
    state === callbackState ||
    url.includes(state)
  )
    throw new Error("Invalid login provider");
  const callback = new URL("/login", cloudOrigin());
  const partition = session.fromPartition("octop-cloud-login-" + randomUUID());
  partition.setPermissionRequestHandler((_wc, _permission, answer) =>
    answer(false),
  );
  const win = new BrowserWindow({
    parent,
    modal: true,
    width: 520,
    height: 720,
    webPreferences: {
      session: partition,
      sandbox: true,
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  win.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  const code = await new Promise<string | null>((resolve, reject) => {
    const fail = () => {
      reject(new Error("Cloud authorization failed"));
      if (!win.isDestroyed()) win.close();
    };
    const timeout = setTimeout(fail, 600000);
    function landing(raw: string) {
      const u = new URL(raw);
      if (u.origin !== callback.origin || u.pathname !== callback.pathname)
        return false;
      const params = new URLSearchParams(u.hash.slice(1));
      if (
        params.get("provider") !== action ||
        params.get("state") !== callbackState
      ) {
        fail();
      } else if (params.get("code") || params.get("error")) {
        resolve(params.get("code"));
        win.close();
      } else fail();
      return true;
    }
    const intercept = (event: Electron.Event, raw: string) => {
      if (landing(raw) || new URL(raw).protocol !== "https:")
        event.preventDefault();
    };
    win.webContents.on(
      "did-fail-load",
      (_event, code, _description, _url, main) => {
        if (main && code !== -3) fail();
      },
    );
    win.webContents.on("will-redirect", intercept);
    win.webContents.on("will-navigate", intercept);
    win.webContents.on("did-navigate-in-page", (_event, raw, main) => {
      if (main) landing(raw);
    });
    win.once("closed", () => {
      clearTimeout(timeout);
      resolve(null);
      void partition.clearStorageData();
    });
    void win.loadURL(start.href).catch((error: { code?: string }) => {
      if (error.code !== "ERR_ABORTED") fail();
    });
  });
  if (!code) return { status: 200, data: { cancelled: true } };
  return request("web-login/exchange", {
    provider: action,
    state,
    code,
    ...(body.locale ? { locale: body.locale } : {}),
  });
}
