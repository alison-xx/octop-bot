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
}

const endpoint = (id: string) =>
  `/octop-bot/computers/${encodeURIComponent(id)}`;

export const botCloudComputerApi = {
  serverInfo: () => request<BotServerInfo>("/octop-bot/server-info"),
  status: (id: string) => request<CloudComputerStatus>(endpoint(id)),
  pause: (id: string) =>
    request<CloudComputerStatus>(endpoint(id) + "/pause", { method: "POST" }),
};
