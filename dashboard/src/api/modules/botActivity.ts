import { request } from "../request";

export interface BotActivityItem {
  agent_id: string;
  /** Unread proactive or room pushes across my threads with this bot. */
  unread_count: number;
  /** Latest turn time in my own chats with this bot. */
  last_active: number | null;
}

export interface GroupActivityMessage {
  message_id: string;
  role: "user" | "assistant" | "error";
  agent_id: string | null;
  text: string;
  created_at: number;
}

export interface GroupActivityItem {
  group_id: string;
  unread_count: number;
  last_message: GroupActivityMessage | null;
}

export interface BotActivitySnapshot {
  bots: BotActivityItem[];
  groups: GroupActivityItem[];
}

export const botActivityApi = {
  read: () => request<BotActivitySnapshot>("/octop-bot/activity"),
  markGroupRead: (groupId: string) =>
    request<void>(
      "/octop-bot/groups/" + encodeURIComponent(groupId) + "/read",
      { method: "POST" },
    ),
};
