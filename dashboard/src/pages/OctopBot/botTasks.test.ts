import { describe, expect, it } from "vitest";
import type { ChatMessage } from "../Chat/hooks/useChat";
import { indexBotTasks, parseTaskOutput, taskSeconds } from "./botTasks";

const task = (overrides: Record<string, unknown> = {}) => ({
  id: "T1",
  goal: "Q3 价格表",
  tier: "standard",
  status: "running",
  criteria: [{ text: "三家都有", status: "pending", evidence: "" }],
  assumptions: [],
  budget: { steps: 60, minutes: 30 },
  started_at: 100,
  updated_at: 100,
  finished_at: null,
  summary: "",
  open_issues: [],
  ...overrides,
});

const tool = (
  id: string,
  name: string,
  output?: unknown,
  args?: unknown,
): ChatMessage =>
  ({
    id,
    role: "assistant",
    content: "",
    timestamp: 0,
    toolData: {
      name,
      arguments: args === undefined ? undefined : JSON.stringify(args),
      output:
        output === undefined
          ? undefined
          : typeof output === "string"
          ? output
          : JSON.stringify({ task: output }),
    },
  }) as unknown as ChatMessage;

describe("botTasks", () => {
  it("reads a task from a tool result and ignores refusals", () => {
    expect(parseTaskOutput(JSON.stringify({ task: task() }))?.id).toBe("T1");
    expect(parseTaskOutput("Refused: criteria 1 have no verdict")).toBeNull();
    expect(parseTaskOutput(undefined)).toBeNull();
    expect(parseTaskOutput("{broken")).toBeNull();
  });

  it("keeps each task at its newest state, anchored where it started", () => {
    const messages = [
      tool("m1", "task_plan", task()),
      tool("m2", "write_todos", undefined, {
        todos: [
          { content: "收集价格", status: "completed" },
          { content: "汇总", status: "in_progress" },
        ],
      }),
      tool("m3", "task_check", "Refused: give the evidence"),
      tool(
        "m4",
        "task_check",
        task({
          criteria: [{ text: "三家都有", status: "passed", evidence: "42 行" }],
        }),
      ),
      tool("m5", "task_plan", task({ id: "T2", goal: "下一个" })),
      {
        id: "m6",
        role: "assistant",
        content: "",
        timestamp: 0,
        hitlData: {
          status: "pending",
          pending_id: "ab12",
          action_requests: [],
        },
      } as unknown as ChatMessage,
    ];
    const index = indexBotTasks(messages);
    const first = index.byId.get("T1");
    expect(first?.firstMessageId).toBe("m1");
    expect(first?.task.criteria[0].status).toBe("passed");
    expect(first?.todos.map((t) => t.content)).toEqual(["收集价格", "汇总"]);
    expect(index.byId.get("T2")?.todos).toEqual([]);
    expect(index.byMessage.get("m4")).toBe("T1");
    expect(index.byMessage.has("m3")).toBe(false);
    expect(index.latest).toBe("T2");
    // The question after T2 started waits for the user; T1's span has none.
    expect(index.byId.get("T2")?.waiting).toBe(true);
    expect(first?.waiting).toBe(false);
  });

  it("counts time until the task finished", () => {
    expect(taskSeconds(task() as never, 160)).toBe(60);
    expect(taskSeconds(task({ finished_at: 130 }) as never, 999)).toBe(30);
  });
});
