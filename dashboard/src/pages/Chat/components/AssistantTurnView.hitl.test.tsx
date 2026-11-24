import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import type { ChatMessage } from "../hooks/useChat";
import { COLLAPSE_THINKING_TEAM_KEY } from "../hooks/useCollapseThinking";
import AssistantTurnView from "./AssistantTurnView";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    i18n: { exists: () => false },
    t: (key: string, opts?: string | { defaultValue?: string }) => {
      if (typeof opts === "string") return opts;
      return opts?.defaultValue ?? key;
    },
    i18n: { exists: () => false },
  }),
}));

vi.mock("react-router-dom", async (original) => ({
  ...(await original<typeof import("react-router-dom")>()),
  useNavigate: () => vi.fn(),
}));

vi.mock("../../../hooks/useServerTimezone", () => ({
  useServerTimezone: () => "UTC",
}));

vi.mock("../../../hooks/useCurrentUser", () => ({
  useCurrentUser: () => ({ username: "ada", display_name: "Ada" }),
}));

vi.mock("../../../context/VoiceOutputContext", () => ({
  useVoiceOutputContext: () => ({ speakingId: null, speak: vi.fn() }),
}));

vi.mock("../../../context/AgentContext", () => ({
  useAgent: () => ({
    activeAgentId: "host",
    activeAgent: {
      agent_id: "host",
      name: "主持团队",
      kind: "team",
      icon_name: "bot",
    },
    agents: [
      {
        agent_id: "host",
        name: "主持团队",
        kind: "team",
        icon_name: "bot",
      },
    ],
  }),
}));

function message(
  extra: Partial<ChatMessage> & Pick<ChatMessage, "id">,
): ChatMessage {
  return {
    role: "assistant",
    content: "",
    status: "done",
    timestamp: 1,
    ...extra,
  };
}

describe("AssistantTurnView approval", () => {
  it("links successful Chief creation results before the answer in the dedicated client", () => {
    vi.stubGlobal("octopDesktop", { botOnly: true });
    try {
      render(
        <MemoryRouter>
          <AssistantTurnView
            messages={[
              message({
                id: "made-bot",
                toolData: {
                  name: "octop_bot_create",
                  arguments: '{"name":"Writer"}',
                  output: "A1B2C3",
                },
              }),
              message({
                id: "made-group",
                toolData: {
                  name: "octop_bot_create_group",
                  output:
                    '{"name":"Newsroom","group_id":"01THEGROUP","member_ids":["A1B2C3"]}',
                },
              }),
              message({ id: "answer", content: "Your team is ready." }),
            ]}
          />
        </MemoryRouter>,
      );
      const created = screen.getByRole("link", { name: "Newsroom" });
      expect(created).toHaveAttribute("href", "/octop-bot/groups/01THEGROUP");
      expect(screen.getByRole("link", { name: "Writer" })).toHaveAttribute(
        "href",
        "/octop-bot/bots/A1B2C3",
      );
      expect(
        created.compareDocumentPosition(
          screen.getByText("Your team is ready."),
        ) & Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
    } finally {
      vi.unstubAllGlobals();
    }
  });
  it("keeps the answer that arrived before the approval card", () => {
    render(
      <AssistantTurnView
        messages={[
          message({ id: "text", content: "磁盘还剩 8G" }),
          message({
            id: "tool",
            toolData: { name: "execute", arguments: "{}" },
          }),
          message({
            id: "card",
            hitlData: {
              action_requests: [{ name: "execute", args: { command: "df" } }],
              status: "pending",
            },
          }),
        ]}
      />,
    );

    expect(screen.getByText("磁盘还剩 8G")).toBeInTheDocument();
    expect(screen.getByText("Confirm this action")).toBeInTheDocument();
  });

  it("keeps host wrap-up below the divider and leaves the decision collapsed", () => {
    render(
      <AssistantTurnView
        messages={[
          message({
            id: "wrap",
            content: "今天就到这里",
            teamWrapup: true,
            speakerAgentId: "host",
            decision: {
              model: "laya",
              empty: false,
              parts: [
                { kind: "result", kept: [{ name: "结果充分", score: 0.91 }] },
              ],
            },
          }),
        ]}
      />,
    );

    const badge = screen.getByText("主持人总结");
    const answer = screen.getByText("今天就到这里");
    expect(
      badge.compareDocumentPosition(answer) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(screen.getByText(/决策模型/)).toBeInTheDocument();
    expect(screen.queryByText(/结果充分/)).not.toBeInTheDocument();
  });

  it("does not flash a lone decision row before tools arrive", () => {
    localStorage.setItem(COLLAPSE_THINKING_TEAM_KEY, "true");
    const decision = {
      model: "laya",
      empty: true,
      parts: [],
    };
    const { rerender } = render(
      <AssistantTurnView
        isTurnInProgress
        messages={[
          message({
            id: "pending",
            status: "streaming",
            decision,
          }),
        ]}
      />,
    );
    expect(screen.queryByText(/决策模型/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();

    rerender(
      <AssistantTurnView
        isTurnInProgress
        messages={[
          message({
            id: "pending",
            status: "done",
            decision,
          }),
          message({
            id: "tool",
            status: "streaming",
            toolData: { name: "execute", arguments: "{}" },
          }),
        ]}
      />,
    );
    const summary = screen.getByRole("button", { name: /正在调用工具/ });
    expect(screen.queryByText(/决策模型/)).not.toBeInTheDocument();
    fireEvent.click(summary);
    expect(screen.getByText(/决策模型/)).toBeInTheDocument();
  });
});
