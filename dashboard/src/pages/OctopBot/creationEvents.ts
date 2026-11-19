import type { ChatMessage } from "../Chat/hooks/useChat";

interface CreatedContact {
  kind: "bot" | "group";
  id: string;
  name: string;
  memberIds: string[];
}

export type WorkspaceChange =
  | CreatedContact
  | {
      kind: "section";
      id: string;
      name: string;
      action: "create" | "move" | "dissolve";
    };

function json(text?: string): unknown {
  try {
    return JSON.parse(text || "");
  } catch {
    return null;
  }
}

/** Show a receipt only for a confirmed change to the workspace. */
function workspaceChange(message: ChatMessage): WorkspaceChange | null {
  const tool = message.toolData;
  if (
    message.status !== "done" ||
    !tool?.output ||
    tool.errorCode ||
    message.errorInfo ||
    tool.returnCode
  )
    return null;
  if (tool.name === "octop_bot_sections") {
    const result = json(tool.output);
    const args = json(tool.arguments);
    if (
      !result ||
      typeof result !== "object" ||
      !("changed" in result) ||
      result.changed !== true ||
      !("revision" in result) ||
      typeof result.revision !== "number" ||
      !("action" in result) ||
      (result.action !== "create" &&
        result.action !== "move" &&
        result.action !== "dissolve") ||
      !args ||
      typeof args !== "object"
    )
      return null;
    const name =
      "section" in args && typeof args.section === "string"
        ? args.section.trim()
        : "";
    if (!name && result.action !== "move") return null;
    return {
      kind: "section",
      id: String(result.revision),
      name,
      action: result.action,
    };
  }
  if (tool.name === "octop_bot_create") {
    const args = json(tool.arguments);
    const id = tool.output.trim();
    if (
      !/^[0-9A-HJKMNP-TV-Z]{6}$/.test(id) ||
      !args ||
      typeof args !== "object" ||
      !("name" in args) ||
      typeof args.name !== "string" ||
      !args.name.trim()
    )
      return null;
    return { kind: "bot", id, name: args.name.trim(), memberIds: [id] };
  }
  if (tool.name !== "octop_bot_create_group") return null;
  const result = json(tool.output);
  if (
    !result ||
    typeof result !== "object" ||
    !("group_id" in result) ||
    typeof result.group_id !== "string" ||
    !result.group_id ||
    !("name" in result) ||
    typeof result.name !== "string" ||
    !result.name.trim() ||
    !("member_ids" in result) ||
    !Array.isArray(result.member_ids)
  )
    return null;
  return {
    kind: "group",
    id: result.group_id,
    name: result.name,
    memberIds: result.member_ids.filter(
      (id): id is string => typeof id === "string",
    ),
  };
}

export function separateCreations(messages: ChatMessage[], enabled: boolean) {
  const created: WorkspaceChange[] = [];
  if (!enabled) return { remaining: messages, created };
  const remaining = messages.filter((message) => {
    const event = workspaceChange(message);
    if (!event) return true;
    if (
      !created.some(
        (entry) => entry.kind === event.kind && entry.id === event.id,
      )
    )
      created.push(event);
    return false;
  });
  return { remaining, created };
}
