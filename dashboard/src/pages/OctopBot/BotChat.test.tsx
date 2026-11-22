import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { octopBotApi } from "../../api/modules/octopBot";
import { octopThreadsApi } from "../../api/modules/octopThreads";
import BotChat from "./BotChat";

// A stable t, like i18next's, so effects keyed on it do not refetch per render.
const t = (key: string) => key;
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t }) }));
vi.mock("../../context/AgentContext", () => ({
  useAgent: () => ({ agents: [], refresh: vi.fn() }),
}));
vi.mock("../../hooks/useCurrentUser", () => ({
  useCurrentUser: () => ({ role: "admin", username: "owner" }),
}));
vi.mock("../../utils/desktopBridge", async (original) => ({
  ...(await original<typeof import("../../utils/desktopBridge")>()),
  isBotClient: () => false,
}));
vi.mock("../Chat", () => ({ default: () => null }));
vi.mock("../Experts/components/EditAgentDrawer", () => ({
  default: () => null,
}));
vi.mock("./BotCharacter", () => ({ BotCharacter: () => null }));
vi.mock("./BotDetailsPanel", () => ({ default: () => null }));
vi.mock("./AppearancePicker", () => ({ default: () => null }));
vi.mock("../../components/Markdown/LazyMarkdown", () => ({
  default: ({ content }: { content: string }) => <p>{content}</p>,
}));
vi.mock("../../api/modules/octopThreads", () => ({
  octopThreadsApi: { list: vi.fn() },
}));
vi.mock("../../api/modules/octopBot", () => ({
  octopBotApi: { side: vi.fn() },
}));

const bot = {
  agent_id: "writer",
  name: "Writer",
  is_main: false,
  is_private: false,
};
function chat(threadId?: string) {
  return render(
    <MemoryRouter>
      <BotChat
        bot={bot}
        roster={[bot]}
        threadId={threadId}
        title="Writer"
        inGroup={false}
        onChanged={() => {}}
        onDelete={() => {}}
      />
    </MemoryRouter>,
  );
}

describe("BotChat panels", () => {
  const getComputedStyle = window.getComputedStyle;
  beforeAll(() => {
    vi.spyOn(window, "getComputedStyle").mockImplementation((element) =>
      getComputedStyle(element),
    );
  });
  beforeEach(() => {
    vi.mocked(octopThreadsApi.list).mockReset();
    vi.mocked(octopBotApi.side).mockReset();
  });

  it("offers a retry when the conversation history fails and clears the error on success", async () => {
    vi.mocked(octopThreadsApi.list)
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValue([{ thread_id: "t1", title: "Earlier chat" } as never]);
    chat();
    fireEvent.click(screen.getByRole("button", { name: "octopBot.history" }));
    await screen.findByText("offline");
    fireEvent.click(
      await screen.findByRole("button", { name: "octopBot.retry" }),
    );
    await screen.findByText("Earlier chat");
    expect(screen.queryByText("offline")).toBeNull();
  });

  it("retries a failed side question in place and sends with Ctrl+Enter", async () => {
    vi.mocked(octopBotApi.side)
      .mockRejectedValueOnce(new Error("timeout"))
      .mockResolvedValue({ answer: "Here it is", snapshot_seq: 3 });
    chat("thread-1");
    fireEvent.click(screen.getByRole("button", { name: "octopBot.side" }));
    const box = await screen.findByRole("textbox", {
      name: "octopBot.sidePrompt",
    });
    fireEvent.change(box, { target: { value: "Summarize" } });
    // Plain Enter is a newline, not a send.
    fireEvent.keyDown(box, { key: "Enter" });
    expect(octopBotApi.side).not.toHaveBeenCalled();
    fireEvent.keyDown(box, { key: "Enter", ctrlKey: true });
    await screen.findByText("timeout");
    fireEvent.click(screen.getByRole("button", { name: "octopBot.retry" }));
    await screen.findByText("Here it is");
    expect(screen.queryByText("timeout")).toBeNull();
    expect(screen.getAllByText("Summarize")).toHaveLength(1);
    expect(octopBotApi.side).toHaveBeenCalledTimes(2);
  });

  it("ignores Ctrl+Enter while an IME composition is active", async () => {
    chat("thread-1");
    fireEvent.click(screen.getByRole("button", { name: "octopBot.side" }));
    const box = await screen.findByRole("textbox", {
      name: "octopBot.sidePrompt",
    });
    fireEvent.change(box, { target: { value: "总结" } });
    fireEvent.keyDown(box, { key: "Enter", ctrlKey: true, keyCode: 229 });
    await waitFor(() => expect(box).toHaveValue("总结"));
    expect(octopBotApi.side).not.toHaveBeenCalled();
  });
});
