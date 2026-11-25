import { createHash } from "node:crypto";
import { hostname } from "node:os";
import { join } from "node:path";
import { app, dialog, type BrowserWindow } from "electron";
import { DeviceCredentialStore } from "../session/device-credential";
import { safeStorageCipher } from "../session/safe-storage-cipher";
import { LYNXCE_CLOUD_ORIGIN } from "../server/server-choice";
import {
  parseRequest,
  performApproved,
  approvedUpload,
  describeUpload,
  type DesktopRequest,
  type Transfer,
} from "./operations";

interface Pairing {
  ticket: string;
  owner: number;
}
interface Link {
  close(): void;
}
interface LocalCall {
  request: DesktopRequest;
  confirmed: boolean;
  controller: AbortController;
  file?: Awaited<ReturnType<typeof describeUpload>>;
}
let current: Link | undefined;

export function disconnectLocalDevice(): void {
  current?.close();
  current = undefined;
}

function official(win: BrowserWindow): boolean {
  if (win.isDestroyed()) return false;
  try {
    return new URL(win.webContents.getURL()).origin === LYNXCE_CLOUD_ORIGIN;
  } catch {
    return false;
  }
}

// The signed-in page authenticates a same-origin request. Its account credential
// stays in the cloud window. No preload, privileged renderer IPC or local listener.
async function accountCall(
  win: BrowserWindow,
  body?: { device_id: string; label: string },
): Promise<unknown> {
  if (!official(win)) return null;
  return win.webContents.executeJavaScript(`(async () => {
    if (location.origin !== ${JSON.stringify(LYNXCE_CLOUD_ORIGIN)}) return null;
    const token = localStorage.getItem("auth_token");
    if (!token) return null;
    const response = await fetch(${JSON.stringify(
      body ? "/api/octop-bot/local-devices/ticket" : "/api/auth/me",
    )}, {
      method: ${JSON.stringify(body ? "POST" : "GET")}, redirect: "error",
      headers: { Authorization: "Bearer " + token, "Content-Type": "application/json" },
      body: ${body ? JSON.stringify(JSON.stringify(body)) : "undefined"}
    });
    if (response.status >= 500) throw new Error("Cloud connection unavailable.");
    if (!response.ok) return null;
    const reply = await response.json();
    return ${body ? "{ticket: reply.ticket, owner: reply.owner}" : "reply.id"};
  })()`);
}

export async function connectLocalDevice(
  win: BrowserWindow,
  zh: boolean,
): Promise<void> {
  if (!official(win)) return;
  const selected = await dialog.showOpenDialog(win, {
    title: zh
      ? "选择要提供给此灵策账号的本机文件夹"
      : "Choose a folder for this cloud account",
    properties: ["openDirectory"],
  });
  if (selected.canceled || !selected.filePaths[0] || !official(win)) return;
  const root = selected.filePaths[0];
  const store = new DeviceCredentialStore(
    join(app.getPath("userData"), "local-connection"),
    safeStorageCipher(),
  );
  const deviceId = createHash("sha256")
    .update((await store.getOrCreate()).secret)
    .digest("hex")
    .slice(0, 32);
  const identity = {
    device_id: deviceId,
    label: hostname().slice(0, 80) || "Desktop",
  };
  const initial = (await accountCall(win, identity)) as Pairing | null;
  if (!initial?.ticket || !Number.isSafeInteger(initial.owner)) {
    throw new Error(
      zh
        ? "请登录支持本机连接的灵策云后重试。"
        : "Sign in to a cloud server that supports desktop connections.",
    );
  }
  disconnectLocalDevice();
  const owner = initial.owner;
  let stopped = false;
  let socket: WebSocket | undefined;
  let connectionAbort: AbortController | undefined;
  let retry: ReturnType<typeof setTimeout> | undefined;
  const onNavigate = () => {
    if (!official(win)) close();
  };
  const close = () => {
    stopped = true;
    connectionAbort?.abort();
    clearTimeout(retry);
    socket?.close();
    if (!win.isDestroyed())
      win.webContents.removeListener("did-navigate", onNavigate);
    win.removeListener("closed", close);
  };
  win.once("closed", close);
  win.webContents.on("did-navigate", onNavigate);
  current = { close };

  let reconnectDelay = 1000;
  const reconnect = () => {
    if (stopped || !official(win)) return;
    retry = setTimeout(async () => {
      try {
        const pair = (await accountCall(win, identity)) as Pairing | null;
        if (!pair?.ticket || pair.owner !== owner) return close();
        dial(pair.ticket);
      } catch {
        reconnectDelay = Math.min(30000, reconnectDelay * 2);
        reconnect();
      }
    }, reconnectDelay);
  };
  const dial = (ticket: string) => {
    if (stopped || !official(win)) return;
    const ws = new WebSocket(
      LYNXCE_CLOUD_ORIGIN.replace("https:", "wss:") +
        "/api/octop-bot/local-devices/ws",
    );
    socket = ws;
    const abort = new AbortController();
    connectionAbort = abort;
    let pending: LocalCall | undefined;
    const valid = () =>
      !stopped &&
      !abort.signal.aborted &&
      official(win) &&
      ws.readyState === WebSocket.OPEN;
    ws.onopen = () => {
      if (valid()) ws.send(ticket);
    };
    ws.onmessage = async (event) => {
      if (
        typeof event.data !== "string" ||
        event.data.length > 1_500_000 ||
        !valid()
      )
        return;
      try {
        const message = JSON.parse(event.data);
        if (message.kind === "connected") {
          reconnectDelay = 1000;
          return;
        }
        if (message.kind === "cancel" && pending?.request.id === message.id) {
          pending?.controller.abort();
          pending = undefined;
          return;
        }
        if (
          message.kind === "execute" &&
          pending?.request.id === message.id &&
          pending?.confirmed
        ) {
          const call = pending;
          const request = call.request;
          call.confirmed = false;
          if ((await accountCall(win)) !== owner || !valid()) return close();
          let result: string;
          let transfer: Transfer | undefined;
          try {
            const signal = AbortSignal.any([
              abort.signal,
              call.controller.signal,
            ]);
            if (request.action === "send_to_cloud" && call.file) {
              transfer = await approvedUpload(
                root,
                request.path,
                call.file,
                signal,
              );
              result = "Sent selected file.";
            } else {
              result = await performApproved(
                root,
                request,
                signal,
                message.transfer,
              );
            }
          } catch (err) {
            result =
              err instanceof Error
                ? err.message.slice(0, 4096)
                : "Operation failed.";
          }
          if (pending === call) {
            pending = undefined;
            if (valid())
              ws.send(
                JSON.stringify({
                  kind: "result",
                  id: request.id,
                  result,
                  transfer,
                }),
              );
          }
          return;
        }
        if (message.kind !== "request") return;
        const request = parseRequest(message);
        if (!request || pending) return close();
        const call: LocalCall = {
          request,
          confirmed: false,
          controller: new AbortController(),
        };
        pending = call;
        if ((await accountCall(win)) !== owner || !valid()) return close();
        if (pending !== call) return;
        if (request.action === "send_to_cloud") {
          try {
            call.file = await describeUpload(root, request.path);
          } catch {
            if (pending === call && valid()) {
              pending = undefined;
              ws.send(
                JSON.stringify({
                  kind: "result",
                  id: request.id,
                  result: "Select a regular local file of at most 1 MiB.",
                }),
              );
            }
            return;
          }
          if (!valid() || pending !== call) return;
        }
        const details = [
          zh
            ? "结果会回到此 Bot 的云端对话。"
            : "Results return to this Bot’s cloud chat.",
          (zh ? "授权文件夹 " : "Authorized folder ") + JSON.stringify(root),
          (zh ? "操作和相对路径 " : "Action and relative path ") +
            request.action +
            "  " +
            JSON.stringify(request.path),
          (zh ? "请求原因 " : "Request reason ") + request.reason,
          request.action === "run"
            ? zh
              ? "命令使用你的系统权限，可访问所选文件夹以外的位置。"
              : "The command runs as you and can access files outside this folder."
            : "",
          request.action === "send_to_cloud"
            ? `${
                zh ? "本机 → Bot 工作区" : "Local → Bot workspace"
              }  ${JSON.stringify(request.destination)}  (${call.file?.size} B)`
            : "",
          request.action === "fetch_from_cloud"
            ? `${
                zh ? "Bot 工作区 → 本机" : "Bot workspace → local"
              }  ${JSON.stringify(request.cloud_path)}  (${request.size} B)`
            : "",
          request.command
            ? (zh ? "完整命令\n" : "Full command\n") + request.command
            : request.text,
        ]
          .filter(Boolean)
          .join("\n\n");
        const answer = await dialog.showMessageBox(win, {
          type: "question",
          title: zh ? "本机操作确认" : "Local device approval",
          message:
            (zh ? "请求本机操作的 Bot：" : "Requesting Bot: ") + request.bot,
          detail: details,
          buttons: zh ? ["拒绝", "允许这一次"] : ["Deny", "Allow once"],
          defaultId: 0,
          cancelId: 0,
          noLink: true,
          signal: AbortSignal.any([abort.signal, call.controller.signal]),
        });
        if (!valid() || pending !== call) return;
        if (answer.response === 1) {
          call.confirmed = true;
          ws.send(JSON.stringify({ kind: "ready", id: request.id }));
        } else {
          pending = undefined;
          ws.send(
            JSON.stringify({
              kind: "result",
              id: request.id,
              result: "Declined by the local user. Stop.",
            }),
          );
        }
      } catch {
        close();
      }
    };
    ws.onerror = () => ws.close();
    ws.onclose = () => {
      abort.abort();
      pending = undefined;
      if (stopped || !official(win)) return;
      reconnectDelay = Math.min(30000, reconnectDelay * 2);
      reconnect();
    };
  };
  dial(initial.ticket);
}
