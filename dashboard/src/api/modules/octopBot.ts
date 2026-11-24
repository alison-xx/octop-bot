import { request, requestBlob, requestUpload } from "../request";

export interface WorkspaceBot {
  avatar?: BotAppearance;
  agent_id: string;
  state: string;
  preparing: boolean;
  last_error: string | null;
  name: string;
  description?: string | null;
  icon_url?: string | null;
  icon_name?: string | null;
  color?: string | null;
  is_main: boolean;
  kind?: string;
  is_private: boolean;
  can_join_group?: boolean;
}
export interface BotAppearance {
  shape: string;
  color: string;
  source: "character" | "photo";
}
export interface AvatarPhoto {
  id: string;
  name: string;
  mime: string;
  bytes: number;
  created_at: number;
  image: string;
}
interface ImportedPhoto {
  id: string;
  name: string;
}
export const botAppearanceApi = {
  set: (id: string, shape: string, color: string) =>
    request<BotAppearance>(
      "/octop-bot/bots/" + encodeURIComponent(id) + "/appearance",
      body("PUT", { shape, color }),
    ),
  reset: (id: string) =>
    request<BotAppearance>(
      "/octop-bot/bots/" + encodeURIComponent(id) + "/appearance",
      { method: "DELETE" },
    ),
  photos: (offset = 0) =>
    request<{ items: AvatarPhoto[]; total: number; next: number | null }>(
      "/octop-bot/avatar-library?limit=48&offset=" + offset,
    ),
  import: (files: File[]) => {
    const form = new FormData();
    for (const file of files) form.append("files", file);
    return requestUpload<{
      imported: ImportedPhoto[];
      duplicates: ImportedPhoto[];
      failed: { name: string; message: string }[];
    }>("/octop-bot/avatar-library/import", form);
  },
  remove: (id: string) =>
    request<void>("/octop-bot/avatar-library/" + encodeURIComponent(id), {
      method: "DELETE",
    }),
  photo: (agentId: string, photo_id: string) =>
    request<{ icon_url: string }>(
      "/octop-bot/bots/" + encodeURIComponent(agentId) + "/avatar-photo",
      body("PUT", { photo_id }),
    ),
};

export interface BotGroup {
  group_id: string;
  name: string;
  admin_id: string;
  member_ids: string[];
  reply_mode: "admin_first" | "all_members";
}

export type SectionColor = "blue" | "orange" | "green" | "purple" | "pink";
export interface BotSection {
  name: string;
  items: string[];
  collapsed?: boolean;
  color?: SectionColor | null;
}
export interface BotLayout {
  revision: number;
  sections: BotSection[];
  pinned: string[];
}

export interface BotWorkspace extends BotLayout {
  chief_id: string;
  bots: WorkspaceBot[];
  groups: BotGroup[];
}

export interface GroupMessage {
  is_wrap_up?: boolean;
  stage_number?: number | null;
  attachment_paths?: string[];
  message_id: string;
  role: "user" | "assistant" | "error";
  agent_id: string | null;
  text: string;
  created_at: number;
  request_id: string;
  thread_id?: string | null;
}

export interface ChatReference {
  part: number;
  message_seq?: number;
  message_id?: string | null;
  agent_id: string;
  thread_id: string;
  title: string;
  excerpt: string;
}
export interface SideMessage {
  role: "user" | "assistant";
  text: string;
}
export interface GroupFile {
  name: string;
  path: string;
  is_dir: boolean;
}
export interface RetainedFolder {
  agent_id: string;
  name: string;
  path: string;
}
export interface GroupDraft {
  agent_id: string;
  request_id: string;
  text: string;
}

export interface GroupGoal {
  title: string;
  criteria: string;
  status: "draft" | "active" | "done";
  stages: {
    title: string;
    assignee_id: string | null;
    status: "pending" | "active" | "done";
    evidence: string;
  }[];
}

const root = "/octop-bot";
const groupPath = (id: string) => root + "/groups/" + encodeURIComponent(id);
function body(method: string, value: unknown): RequestInit {
  return { method, body: JSON.stringify(value) };
}

export const octopBotApi = {
  workspace: () => request<BotWorkspace>(root + "/workspace"),
  saveLayout: (layout: BotLayout) =>
    request<BotLayout>(root + "/layout", body("PUT", layout)),
  createGroup: (group: Omit<BotGroup, "group_id">) =>
    request<BotGroup>(root + "/groups", body("POST", group)),
  updateGroup: (id: string, group: Omit<BotGroup, "group_id">) =>
    request<BotGroup>(groupPath(id), body("PATCH", group)),
  deleteGroup: (id: string) =>
    request<void>(groupPath(id), { method: "DELETE" }),
  messages: (id: string, after?: string) =>
    request<GroupMessage[]>(
      groupPath(id) +
        "/messages" +
        (after ? "?after_id=" + encodeURIComponent(after) : ""),
    ),
  send: (
    id: string,
    text: string,
    mention_ids: string[],
    request_id: string,
    attachment_paths: string[] = [],
  ) =>
    request<GroupMessage[]>(
      groupPath(id) + "/messages",
      body("POST", { text, mention_ids, request_id, attachment_paths }),
    ),
  goal: (id: string) => request<GroupGoal | null>(groupPath(id) + "/goal"),
  drafts: (id: string) => request<GroupDraft[]>(groupPath(id) + "/drafts"),
  saveGoal: (id: string, goal: GroupGoal) =>
    request<GroupGoal>(groupPath(id) + "/goal", body("PUT", goal)),
  side: (
    agentId: string,
    thread_id: string,
    question: string,
    snapshot_seq: number | undefined,
    turns: SideMessage[],
  ) =>
    request<{ answer: string; snapshot_seq: number }>(
      root + "/bots/" + encodeURIComponent(agentId) + "/side",
      body("POST", { thread_id, question, snapshot_seq, turns }),
    ),
  search: (query: string) =>
    request<{ matches: ChatReference[]; indexing: boolean }>(
      root + "/history/search?with_status=true&q=" + encodeURIComponent(query),
    ),
  reference: (ref: ChatReference) =>
    request<{ text: string }>(
      root + "/bots/" + encodeURIComponent(ref.agent_id) + "/reference",
      body("POST", {
        thread_id: ref.thread_id,
        message_seq: ref.message_seq,
        message_id: ref.message_id,
      }),
    ),
  memory: (groupId?: string) =>
    request<{ text: string }>(
      (groupId ? groupPath(groupId) : root) + "/memory",
    ),
  saveMemory: (text: string, groupId?: string) =>
    request<{ text: string }>(
      (groupId ? groupPath(groupId) : root) + "/memory",
      body("PUT", { text }),
    ),
  privacy: (agentId: string, value: boolean) =>
    request<WorkspaceBot>(
      root + "/bots/" + encodeURIComponent(agentId) + "/privacy",
      body("PUT", { private: value }),
    ),
  files: (id: string, path: string) =>
    request<GroupFile[]>(
      groupPath(id) + "/files?path=" + encodeURIComponent(path),
    ),
  download: (id: string, path: string) =>
    requestBlob(groupPath(id) + "/file?path=" + encodeURIComponent(path)),
  upload: (id: string, file: File) => {
    const data = new FormData();
    data.append("file", file);
    return requestUpload<GroupFile>(groupPath(id) + "/files", data);
  },
  retainedFolders: () => request<RetainedFolder[]>(root + "/retained-folders"),
  releaseFolder: (id: string) =>
    request<void>(root + "/retained-folders/" + encodeURIComponent(id), {
      method: "DELETE",
    }),
};

export interface BotImSession {
  channel_id: string;
  session_key: string;
  channel_name: string;
  platform: string;
  subject: string;
  chat_type: string;
  linked: boolean;
  linked_elsewhere: boolean;
}

export const botGroupIm = {
  list: (id: string) => request<BotImSession[]>(groupPath(id) + "/im-sessions"),
  update: (id: string, session: BotImSession, linked: boolean) =>
    request<BotImSession[]>(groupPath(id) + "/im-sessions", {
      method: "PUT",
      body: JSON.stringify({
        channel_id: session.channel_id,
        session_key: session.session_key,
        linked,
      }),
    }),
};
