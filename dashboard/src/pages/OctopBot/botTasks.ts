import type { BotTaskStatus } from "../../api/modules/botTaskStatus";
import type { ChatMessage } from "../Chat/hooks/useChat";
import { isResumableHitl } from "../Chat/utils/pendingHitl";
import {
  collectWriteTodosFromMessages,
  type TodoListItem,
} from "../../utils/parseWriteTodos";

/** The Bot's task tools; each returns the whole task as JSON. */
export const TASK_TOOLS = [
  "task_plan",
  "task_check",
  "task_finish",
  "task_extend_budget",
] as const;
export type TaskToolName = (typeof TASK_TOOLS)[number];

export type TaskStatus = "running" | "done" | "partial" | "stopped";
export type CheckStatus = "pending" | "passed" | "failed" | "skipped";

export interface BotTaskCriterion {
  text: string;
  status: CheckStatus;
  evidence: string;
}

/** What the server checked on a delivered file, worded by the client. */
export interface BotDeliverableFact {
  k:
    | "pages"
    | "rows"
    | "sheets"
    | "slides"
    | "chars"
    | "lines"
    | "files"
    | "pixels"
    | "filenameOnly"
    | "nonempty"
    | "validJson"
    | "opened";
  n: number;
  w?: number;
  h?: number;
}

export interface BotDeliverable {
  name: string;
  path: string;
  size: number;
  version: number;
  preview?: string | null;
  facts?: BotDeliverableFact[];
  at: number;
}

export interface BotTask {
  id: string;
  goal: string;
  tier: "standard" | "deep";
  status: TaskStatus;
  criteria: BotTaskCriterion[];
  assumptions: string[];
  steps?: {
    content: string;
    status: TodoListItem["status"];
    checkpoint?: string | null;
  }[];
  budget: { minutes: number; steps?: number };
  started_at: number;
  updated_at: number;
  finished_at: number | null;
  summary: string;
  open_issues: string[];
  /** Independent reviews of a deep task, and what the last one found. */
  reviews?: number;
  review?: string;
  review_status?: "passed" | "issues" | "unverified" | null;
  /** Files handed to the user during the task, after they passed the checks. */
  deliverables?: BotDeliverable[];
  delivery_failures?: Record<string, "open" | "validation">;
}

export interface BotTaskEntry {
  /** The newest state of the task anywhere in the conversation. */
  task: BotTask;
  /** Where the card sits: the message that started the task. */
  firstMessageId: string;
  /** The plan (write_todos) kept while this task ran. */
  todos: TodoListItem[];
  /** A question, approval or takeover in this task still waits for the user. */
  waiting: boolean;
}

export interface BotTaskIndex {
  byId: Map<string, BotTaskEntry>;
  /** Task id of every task tool message. */
  byMessage: Map<string, string>;
  /** The task started last: the only one the Bot can be working on now. */
  latest?: string;
}

export function isTaskTool(name: string | undefined): name is TaskToolName {
  return (TASK_TOOLS as readonly string[]).includes(name ?? "");
}

/** The task in a task tool's result, or null (a refusal, or still streaming). */
export function parseTaskOutput(output: unknown): BotTask | null {
  if (typeof output !== "string" || !output.trimStart().startsWith("{"))
    return null;
  try {
    const task = (JSON.parse(output) as { task?: BotTask }).task;
    return task && typeof task.id === "string" && Array.isArray(task.criteria)
      ? task
      : null;
  } catch {
    return null;
  }
}

/**
 * One entry per task in the conversation: its latest state (a check made in a later turn
 * updates the card where the task started) and the plan kept while it ran.
 */
export function indexBotTasks(
  messages: readonly ChatMessage[],
  statuses: readonly BotTaskStatus[] = [],
): BotTaskIndex {
  const byId = new Map<string, BotTaskEntry>();
  const byMessage = new Map<string, string>();
  const starts: { id: string; index: number }[] = [];
  messages.forEach((message, index) => {
    const tool = message.toolData;
    if (!isTaskTool(tool?.name)) return;
    const task = parseTaskOutput(tool?.output);
    if (!task) return;
    byMessage.set(message.id, task.id);
    const known = byId.get(task.id);
    if (known) {
      known.task = task;
    } else {
      byId.set(task.id, {
        task,
        firstMessageId: message.id,
        todos: [],
        waiting: false,
      });
      starts.push({ id: task.id, index });
    }
  });
  starts.forEach((start, i) => {
    const end = starts[i + 1]?.index ?? messages.length;
    const entry = byId.get(start.id);
    if (!entry) return;
    const span = messages.slice(start.index, end);
    entry.todos = collectWriteTodosFromMessages(span);
    entry.waiting = span.some(
      (m) =>
        m.hitlData !== undefined &&
        (m.hitlData.status ?? "pending") === "pending" &&
        isResumableHitl(m.hitlData),
    );
  });
  for (const status of statuses) {
    const entry = byId.get(status.id);
    if (entry && status.updated_at >= entry.task.updated_at) {
      entry.task = { ...entry.task, ...status };
    }
  }
  return { byId, byMessage, latest: starts[starts.length - 1]?.id };
}

/** Seconds the task has run (until it finished). */
export function taskSeconds(task: BotTask, now = Date.now() / 1000): number {
  return Math.max(0, Math.round((task.finished_at ?? now) - task.started_at));
}
