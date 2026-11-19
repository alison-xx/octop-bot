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
