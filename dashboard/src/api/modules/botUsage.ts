import { request } from "../request";

export type UsageWindow = "today" | "last_7d" | "last_30d" | "all";

export interface BotUsageSummary {
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  model_calls: number;
  turns: number;
  buckets: { key: string; label: string; total_tokens: number }[];
}

export function getBotUsage(agentId: string, window: UsageWindow) {
  const query = new URLSearchParams({
    agent_id: agentId,
    window,
    granularity: "by_model",
  });
  return request<BotUsageSummary>(`/usage/summary?${query}`);
}

/** The signed-in account's usage across all its Bots over the last 30 days. */
export function getAccountUsage(granularity: "by_agent" | "by_model") {
  const query = new URLSearchParams({ window: "last_30d", granularity });
  return request<BotUsageSummary>(`/usage/summary?${query}`);
}
