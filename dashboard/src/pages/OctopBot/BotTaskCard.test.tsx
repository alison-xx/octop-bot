import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import BotTaskCard, { BotTaskReport } from "./BotTaskCard";
import type { BotTask, BotTaskEntry } from "./botTasks";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, values?: Record<string, unknown>) =>
      values ? `${key} ${JSON.stringify(values)}` : key,
  }),
}));

const base: BotTask = {
  id: "T1",
  goal: "Q3 价格表",
  tier: "standard",
  status: "running",
  criteria: [
    { text: "三家都有", status: "passed", evidence: "表格 42 行" },
    { text: "有折扣", status: "skipped", evidence: "C 家没有公开" },
  ],
  assumptions: ["取官网标价"],
  budget: { steps: 60, minutes: 30 },
  started_at: Date.now() / 1000 - 90,
  updated_at: Date.now() / 1000,
  finished_at: null,
  summary: "",
  open_issues: [],
};

const entry = (task: Partial<BotTask> = {}, waiting = false): BotTaskEntry => ({
  task: { ...base, ...task },
  firstMessageId: "m1",
  waiting,
  todos: [
    { id: "1", content: "收集价格", status: "completed" },
    { id: "2", content: "汇总", status: "in_progress" },
  ],
});

describe("BotTaskCard", () => {
  it("shows the plan and progress while the Bot works, criteria on demand", () => {
    render(<BotTaskCard entry={entry()} live />);
    expect(screen.getByText("botTask.phase.live")).toBeTruthy();
    expect(screen.getByText("汇总")).toBeTruthy();
    expect(screen.getByRole("progressbar").getAttribute("aria-valuenow")).toBe(
      "1",
    );
    expect(screen.queryByText("表格 42 行")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /botTask.criteria/ }));
    expect(screen.getByText("表格 42 行")).toBeTruthy();
  });

  it("says paused when the Bot is not replying, and folds once finished", () => {
    const { rerender } = render(<BotTaskCard entry={entry()} live={false} />);
    expect(screen.getByText("botTask.phase.paused")).toBeTruthy();
    rerender(
      <BotTaskCard
        entry={entry({ status: "partial", finished_at: base.started_at + 60 })}
        live={false}
      />,
    );
    expect(screen.getByText("botTask.phase.partial")).toBeTruthy();
    expect(screen.queryByText("汇总")).toBeNull();
    expect(screen.queryByRole("progressbar")).toBeNull();
  });
});

describe("BotTaskCard waiting", () => {
  it("marks a task that waits for the user, whether or not the Bot is replying", () => {
    render(<BotTaskCard entry={entry({}, true)} live={false} />);
    expect(screen.getByText("botTask.phase.waiting")).toBeTruthy();
    expect(screen.queryByText("botTask.phase.paused")).toBeNull();
  });
});

describe("BotTaskReport", () => {
  it("shows what the independent reviewer found on a deep task", () => {
    render(
      <BotTaskReport
        task={{
          ...base,
          tier: "deep",
          status: "done",
          reviews: 1,
          review: "**met**: 表格 42 行",
          finished_at: base.started_at + 60,
        }}
      />,
    );
    expect(screen.getByText("botTask.review")).toBeTruthy();
    // Rendered as Markdown, not shown as raw asterisks.
    expect(screen.getByText("met").tagName).toBe("STRONG");
    expect(
      screen.getByRole("button", { name: /botTask.showReview/ }),
    ).toBeTruthy();
  });

  it("never reads as done when a criterion was skipped, and lists what is missing", () => {
    render(
      <BotTaskReport
        task={{
          ...base,
          status: "partial",
          summary: "表格已交付",
          open_issues: ["C 家折扣"],
          finished_at: base.started_at + 480,
        }}
      />,
    );
    expect(screen.getByText(/botTask.reportPartial/)).toBeTruthy();
    expect(screen.queryByText(/botTask.reportDone/)).toBeNull();
    expect(screen.getByText("C 家折扣")).toBeTruthy();
    expect(screen.getByText("取官网标价")).toBeTruthy();
    expect(screen.getByText("C 家没有公开")).toBeTruthy();
    expect(screen.getByText(/botTask.duration/).textContent).toContain(
      "botTask.minutes",
    );
  });

  it("lists the delivered files once each, with their newest version and what was checked", () => {
    render(
      <BotTaskReport
        task={{
          ...base,
          status: "done",
          finished_at: base.started_at + 60,
          deliverables: [
            {
              name: "价格对比.xlsx",
              path: "价格对比.xlsx",
              size: 2048,
              version: 1,
              facts: [],
              at: 1,
            },
            {
              name: "价格对比.xlsx",
              path: "价格对比.xlsx",
              size: 4096,
              version: 2,
              facts: [{ k: "sheets", n: 3 }],
              at: 2,
            },
          ],
        }}
      />,
    );
    expect(screen.getByText("botTask.deliverables")).toBeTruthy();
    expect(screen.getAllByText(/价格对比.xlsx/)).toHaveLength(1);
    expect(screen.getByText("v2")).toBeTruthy();
    expect(screen.getByText(/botTask.checked/).textContent).toContain(
      "botTask.fact.sheets",
    );
  });
});
