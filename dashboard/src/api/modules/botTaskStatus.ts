import { request } from "../request";

export interface BotTaskStatus {
  id: string;
  status: "running" | "done" | "partial" | "stopped";
  updated_at: number;
  finished_at: number | null;
  summary: string;
}

export function readBotTaskStatuses(agentId: string, threadId: string) {
  return request<BotTaskStatus[]>(
    `/agents/${encodeURIComponent(agentId)}/threads/${encodeURIComponent(
      threadId,
    )}/task-statuses`,
  );
}
