import { act, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import BotWorkingLine from "./BotWorkingLine";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, args?: Record<string, unknown>) =>
      [key, ...Object.values(args ?? {})].join(" "),
  }),
}));
vi.mock("../Chat/hooks/toolDisplayNames", () => ({
  useToolDisplayNames: () => (name: string) => name,
}));
vi.mock("../Chat/ChatRouteContext", () => ({ useEmbeddedChat: () => null }));

it("ticks while waiting, then reports actual tool activity and a pending user question", () => {
  vi.useFakeTimers();
  try {
    const startedAt = Date.now();
    const view = render(<BotWorkingLine messages={[]} startedAt={startedAt} />);
    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(screen.getByRole("timer")).toHaveTextContent(
      "octopBot.workingElapsed 2",
    );
    const message = {
      id: "m",
      role: "assistant" as const,
      status: "streaming" as const,
      content: "",
      toolData: { name: "search", arguments: "" },
    };
    view.rerender(
      <BotWorkingLine messages={[message]} startedAt={startedAt} />,
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      "chat.processRunningTool search",
    );
    view.rerender(
      <BotWorkingLine
        messages={[
          {
            ...message,
            toolData: { name: "ask_user_question", arguments: "" },
          },
        ]}
        startedAt={startedAt}
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      "octopBot.waitingForInput",
    );
  } finally {
    vi.useRealTimers();
  }
});
