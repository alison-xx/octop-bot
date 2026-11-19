import { describe, expect, it } from "vitest";
import type { ChatMessage, ToolCallData } from "../Chat/hooks/useChat";
import { separateCreations } from "./creationEvents";

function tool(
  data: ToolCallData,
  status: ChatMessage["status"] = "done",
): ChatMessage {
  return {
    id: data.callId || "turn",
    role: "assistant",
    content: "",
    timestamp: 1,
    status,
    toolData: data,
  };
}

describe("confirmed creations in a Chief turn", () => {
  const bot = {
    name: "octop_bot_create",
    arguments: JSON.stringify({ name: "Writer" }),
    output: "A1B2C3",
  };
  const group = {
    name: "octop_bot_create_group",
    output: JSON.stringify({
      group_id: "01THEGROUP",
      name: "Newsroom",
      admin_id: "A1B2C3",
      member_ids: ["A1B2C3"],
    }),
  };
  it("uses actual resource IDs and names once and keeps other tool details", () => {
    const ordinary = tool({ name: "read_file", output: "file" });
    const result = separateCreations(
      [tool(bot), ordinary, tool(group), tool(group)],
      true,
    );
    expect(result.created).toEqual([
      { kind: "bot", id: "A1B2C3", name: "Writer", memberIds: ["A1B2C3"] },
      {
        kind: "group",
        id: "01THEGROUP",
        name: "Newsroom",
        memberIds: ["A1B2C3"],
      },
    ]);
    expect(result.remaining).toEqual([ordinary]);
  });
  it("never turns proposals, partial results, and failures into successful events", () => {
    const messages = [
      tool(bot, "streaming"),
      tool(bot, "error"),
      tool({ ...bot, output: "invalid result" }),
      tool({ ...group, output: "{}" }),
      tool({ ...group, errorCode: "FORBIDDEN" }),
      {
        ...tool(bot),
        role: "assistant" as const,
        toolData: undefined,
        content: "I've created a bot",
      },
    ];
    expect(separateCreations(messages, true)).toEqual({
      remaining: messages,
      created: [],
    });
    expect(separateCreations([tool(bot)], false).created).toEqual([]);
  });
  it("shows confirmed sidebar moves without producing a group chat link", () => {
    const result = (changed: boolean) =>
      tool({
        name: "octop_bot_sections",
        arguments: JSON.stringify({ action: "move", section: "Studio" }),
        output: JSON.stringify({
          action: "move",
          changed,
          revision: 3,
          sections: [],
        }),
      });
    const unchanged = result(false);
    expect(separateCreations([result(true), unchanged], true)).toEqual({
      created: [{ kind: "section", id: "3", name: "Studio", action: "move" }],
      remaining: [unchanged],
    });
  });
});
