import { request } from "../request";

const root = "/octop-bot/cloud";
const json = (method: string, value: unknown) => ({
  method,
  body: JSON.stringify(value),
});
export interface CloudAccount {
  connected: boolean;
  account_id: string | null;
  display_name: string | null;
  avatar_url?: string | null;
}
export interface CloudCapabilities {
  enabled: boolean;
  reason: string | null;
  models: string[];
  default_model: string | null;
}
export interface CloudSession {
  id: string;
  title: string;
  model: string | null;
  updated_at: string;
  message_count: number;
}
export interface CloudTask {
  id: string;
  session_id: string;
  status: string;
  model: string;
  result: string | null;
  error: string | null;
  question: string | null;
  can_answer: boolean;
}
export interface CloudConversation extends Omit<CloudSession, "message_count"> {
  items: {
    role: string;
    content: string;
    created_at: string | null;
    task_id: string | null;
  }[];
  tasks: CloudTask[];
}
export interface CloudRule {
  frequency: "once" | "daily" | "weekdays" | "weekly" | "monthly";
  hour: number;
  minute: number;
  timezone: string;
  weekdays?: number[];
  month_day?: number;
  once_at?: string;
}
export interface CloudSchedule {
  id: string;
  name: string;
  instruction: string;
  bot_name: string | null;
  rule_text: string;
  finished_once: boolean;
  enabled: boolean;
  next_run_at: string | null;
  last_run_at: string | null;
  last_status: string;
  last_error: string;
  last_result_preview: string;
  session_id: string;
  run_count: number;
}
export interface CloudImportPreview {
  title: string;
  revision: string;
  items: { role: "user" | "assistant"; content: string }[];
}
function transferPath(botId: string, threadId: string) {
  return (
    root +
    "/import/" +
    encodeURIComponent(botId) +
    "/" +
    encodeURIComponent(threadId)
  );
}
const accountScope = (account: string) => ({
  headers: { "X-Octop-Cloud-Account": account },
});
export const botCloudApi = {
  previewImport: (botId: string, threadId: string) =>
    request<CloudImportPreview>(transferPath(botId, threadId)),
  importChat: (
    botId: string,
    threadId: string,
    account_id: string,
    revision: string,
    model: string,
  ) =>
    request<{ session_id: string }>(
      transferPath(botId, threadId),
      json("POST", { account_id, revision, model }),
    ),
  account: () => request<CloudAccount>(root + "/account"),
  login: (account: string, password: string) =>
    request<CloudAccount>(
      root + "/account",
      json("POST", { account, password }),
    ),
  logout: (accountId: string) =>
    request<void>(
      root + "/account?expected_account_id=" + encodeURIComponent(accountId),
      { method: "DELETE" },
    ),
  capabilities: (account: string) =>
    request<CloudCapabilities>(root + "/capabilities", accountScope(account)),
  sessions: (account: string, cursor?: string) =>
    request<{ items: CloudSession[]; next_cursor: string | null }>(
      root +
        "/sessions" +
        (cursor ? "?cursor=" + encodeURIComponent(cursor) : ""),
      accountScope(account),
    ),
  conversation: (account: string, id: string) =>
    request<CloudConversation>(
      root + "/sessions/" + encodeURIComponent(id),
      accountScope(account),
    ),
  turn: (input: {
    account_id: string;
    request_id: string;
    session_id?: string;
    bot_id?: string;
    input_task_id?: string;
    model?: string;
    message: string;
  }) => request<CloudTask>(root + "/turns", json("POST", input)),
  cancelTask: (
    account_id: string,
    session_id: string,
    id: string,
    request_id: string,
  ) =>
    request<CloudTask>(
      root + "/tasks/" + encodeURIComponent(id) + "/cancel",
      json("POST", { account_id, session_id, request_id }),
    ),
  schedules: (account: string) =>
    request<{ items: CloudSchedule[] }>(
      root + "/schedules",
      accountScope(account),
    ),
  createSchedule: (input: {
    account_id: string;
    bot_id?: string;
    name: string;
    instruction: string;
    rule: CloudRule;
  }) => request<CloudSchedule>(root + "/schedules", json("POST", input)),
  toggleSchedule: (account_id: string, id: string, enabled: boolean) =>
    request<CloudSchedule>(
      root + "/schedules/" + encodeURIComponent(id) + "/enabled",
      json("PUT", { account_id, enabled }),
    ),
};
