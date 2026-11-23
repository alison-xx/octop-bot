import { request } from "../request";

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
}

export interface ScreenTicket {
  ws_path: string;
  expires_in: number;
  /** Screen session for typing and the clipboard while the screen is open. */
  session: string;
}

const endpoint = (id: string) =>
  `/octop-bot/computers/${encodeURIComponent(id)}`;

// The screen session is the credential: the phone apps' screen page has no sign-in.
const sessionEndpoint = (session: string) =>
  `/octop-bot/screen-sessions/${encodeURIComponent(session)}`;

export const botCloudComputerApi = {
  serverInfo: () => request<BotServerInfo>("/octop-bot/server-info"),
  status: (id: string) => request<CloudComputerStatus>(endpoint(id)),
  pause: (id: string) =>
    request<CloudComputerStatus>(endpoint(id) + "/pause", { method: "POST" }),
  takeover: (id: string, active: boolean) =>
    request<CloudComputerStatus>(endpoint(id) + "/takeover", {
      method: "POST",
      body: JSON.stringify({ active }),
    }),
  openScreen: (id: string) =>
    request<ScreenTicket>(endpoint(id) + "/screen", { method: "POST" }),
  /** Types text (any language) at the taken-over desktop's cursor. */
  typeText: (session: string, text: string) =>
    request<void>(sessionEndpoint(session) + "/type", {
      method: "POST",
      body: JSON.stringify({ text }),
    }),
  readClipboard: (session: string) =>
    request<{ text: string }>(sessionEndpoint(session) + "/clipboard"),
};
