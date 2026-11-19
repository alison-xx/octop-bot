import { request } from "../request";

export type LynxceStatus = {
  connected: boolean;
  selected_model: string | null;
};
export type LynxceAttempt = { attempt_id: string; authorization_url: string };
export type LynxceModel = { id: string; name: string };
const base = "/octop-bot/lynxce";
const attemptPath = (id: string) => base + "/login/" + encodeURIComponent(id);

export const lynxceBotApi = {
  status: () => request<LynxceStatus>(base + "/status"),
  login: () => request<LynxceAttempt>(base + "/login", { method: "POST" }),
  poll: (id: string, signal?: AbortSignal) =>
    request<{
      state: "pending" | "connected" | "failed";
      detail: string | null;
    }>(attemptPath(id), { signal }),
  cancel: (id: string) => request<void>(attemptPath(id), { method: "DELETE" }),
  models: () => request<{ models: LynxceModel[] }>(base + "/models"),
  select: (model_id: string) =>
    request<LynxceStatus>(base + "/model", {
      method: "PUT",
      body: JSON.stringify({ model_id }),
    }),
  clearModel: () => request<void>(base + "/model", { method: "DELETE" }),
  logout: () => request<void>(base + "/session", { method: "DELETE" }),
};
