import { request } from "../request";

/** A card one of my Bots is waiting on (a question, an approval or a takeover). */
export interface BotInboxItem {
  pending_id: string;
  agent_id: string;
  thread_id: string;
  kind: "question" | "approval" | "takeover" | "tool";
  text: string;
  created_at: number;
  /** Raised by a scheduled run rather than a chat. */
  scheduled: boolean;
}

export const botInboxApi = {
  list: () => request<{ items: BotInboxItem[] }>("/octop-bot/inbox"),
};
