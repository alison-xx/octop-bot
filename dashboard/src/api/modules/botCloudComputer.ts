import { request } from "../request";
import { parseApiError } from "../../utils/apiError";

/** What `/api/octop-bot/server-info` says about this server. */
export interface BotServerInfo {
  product: "octop-bot";
  version: string;
  edition: "desktop" | "web" | "cloud" | "server";
  setup_required: boolean;
  sign_in: ("lynxce" | "password")[];
  capabilities: {
    wallet: boolean;
    cloud_computer: boolean;
    /** Off for cloud accounts: the image and video providers are the operator's. */
    media_generation: boolean;
    file_store: "local" | "object";
  };
}

/** A Bot's cloud computer on Octop Bot cloud. */
export interface CloudComputerStatus {
  state: "none" | "running" | "paused";
  spec: string;
  running_since: number | null;
  paid_until: number | null;
  takeover: boolean;
  /** The Bot is working on the computer right now. */
  busy?: boolean;
  /** Its latest action: click, type, key, scroll, screenshot, command, … */
  activity?: string | null;
  activity_at?: number | null;
  reclaim_notified?: boolean;
  idle_days?: number;
  reclaim_state?: "reminded" | "pending_reclaim" | null;
  reclaim_at?: number | null;
  disk_gb?: number;
  disk_daily_credits?: number;
  disk_billing?: boolean;
  disk_paid_through?: string | null;
  disk_overdue_days?: number;
}

/** Front window title and a small thumbnail of a running computer. */
export interface CloudComputerGlance {
  window: string | null;
  /** Base64 JPEG, 320 px wide. */
  thumbnail: string | null;
}

export type ScreenSession =
  | string
  | { header: string; expiresAt: number; renewable: boolean }
  | { viewOnly: true };

export function viewOnlyScreen(
  session?: ScreenSession,
): session is { viewOnly: true } {
  return typeof session === "object" && "viewOnly" in session;
}

export interface ScreenTicket {
  ws_path: string;
  expires_in: number;
  /** Screen session for typing and the clipboard while the screen is open. */
  session: string;
  session_transport?: "header" | "path" | null;
  session_expires_in?: number | null;
  session_renewable?: boolean;
}

const endpoint = (id: string) =>
  `/octop-bot/computers/${encodeURIComponent(id)}`;

function screenAction<T>(
  session: ScreenSession,
  action: "clipboard" | "type",
  options?: RequestInit,
): Promise<T> {
  const base = "/octop-bot/screen-sessions";
  if (viewOnlyScreen(session)) throw new Error("Screen is view-only");
  if (typeof session === "object")
    return request<T>(base + "/" + action, {
      ...options,
      headers: { "X-Octop-Screen-Session": session.header },
    });
  // Mobile screen links issued by the original cloud service use the path protocol.
  return request<T>(
    base + "/" + encodeURIComponent(session) + "/" + action,
    options,
  );
}

export const reverifyComputerEvent = "octop-bot-reverify-computer";

async function computerRequest<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  try {
    return await request<T>(path, options);
  } catch (error) {
    if (parseApiError(error)?.code !== "BOT_CLOUD_REVERIFY_REQUIRED")
      throw error;
    const verified = await new Promise<boolean>((resolve) => {
      const event = new CustomEvent(reverifyComputerEvent, {
        detail: resolve,
        cancelable: true,
      });
      // An open Bot view owns the dialog. Without one, return the original error.
      if (window.dispatchEvent(event)) resolve(false);
    });
    if (!verified) throw error;
    return request<T>(path, options);
  }
}

export const botCloudComputerApi = {
  serverInfo: () => request<BotServerInfo>("/octop-bot/server-info"),
  status: (id: string) => computerRequest<CloudComputerStatus>(endpoint(id)),
  pause: (id: string) =>
    computerRequest<CloudComputerStatus>(endpoint(id) + "/pause", {
      method: "POST",
    }),
  takeover: (id: string, active: boolean) =>
    computerRequest<CloudComputerStatus>(endpoint(id) + "/takeover", {
      method: "POST",
      body: JSON.stringify({ active }),
    }),
  /** Never starts the computer; 404 while it is off. */
  glance: (id: string) =>
    computerRequest<CloudComputerGlance>(endpoint(id) + "/glance"),
  openScreen: async (id: string) => {
    const ticket = await computerRequest<ScreenTicket>(
      endpoint(id) + "/screen",
      {
        method: "POST",
        headers: { "X-Octop-Screen-Transport": "header" },
      },
    );
    const session: ScreenSession =
      ticket.session_transport === "header"
        ? {
            header: ticket.session,
            renewable: ticket.session_renewable !== false,
            expiresAt: Date.now() + 1000 * (ticket.session_expires_in ?? 0),
          }
        : ticket.session_transport === null
        ? { viewOnly: true }
        : ticket.session;
    return { ...ticket, session };
  },
  renewScreen: (
    id: string,
    session: Exclude<ScreenSession, { viewOnly: true }>,
  ) =>
    request<void>(endpoint(id) + "/screen/renew", {
      method: "POST",
      ...(typeof session === "string"
        ? { body: JSON.stringify({ session }) }
        : { headers: { "X-Octop-Screen-Session": session.header } }),
    }),
  /** Types text (any language) at the taken-over desktop's cursor. */
  typeText: (session: ScreenSession, text: string) =>
    screenAction<void>(session, "type", {
      method: "POST",
      body: JSON.stringify({ text }),
    }),
  readClipboard: (session: ScreenSession) =>
    screenAction<{ text: string }>(session, "clipboard"),
};

const computerAccount = "/octop-bot/computer-account";
const jsonBody = (method: string, value: unknown) => ({
  method,
  body: JSON.stringify(value),
});
export type ComputerTarget = "local" | "cloud";
export const desktopComputerApi = {
  set: (id: string, target: ComputerTarget) =>
    request<{ target: ComputerTarget }>(
      "/octop-bot/bots/" + encodeURIComponent(id) + "/computer-target",
      jsonBody("PUT", { target }),
    ),
  sendCode: (target: string, locale: string) =>
    request<{ channel: "phone" | "email" }>(
      computerAccount + "/code",
      jsonBody("POST", { target, locale }),
    ),
  codeLogin: (target: string, code: string, password?: string) =>
    request<void>(
      computerAccount + "/code-login",
      jsonBody("POST", { target, code, password }),
    ),
  login: (account: string, password: string) =>
    request<void>(
      computerAccount + "/login",
      jsonBody("POST", { account, password }),
    ),
};
