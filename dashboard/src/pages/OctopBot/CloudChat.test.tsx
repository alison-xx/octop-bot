import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { botCloudApi, type CloudTask } from "../../api/modules/botCloud";
import CloudChat from "./CloudChat";
import CloudImport from "./CloudImport";

const t = (key: string) => key;
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t, i18n: { language: "zh" } }),
}));
vi.mock("../../hooks/useServerTimezone", () => ({
  useServerTimezone: () => "Asia/Shanghai",
}));
vi.mock("./BotCharacter", () => ({
  BotCharacter: () => null,
  octopCharacter: { color: "rose", shape: "octop" },
}));
vi.mock("../../components/Markdown/LazyMarkdown", () => ({
  default: ({ content }: { content: string }) => <p>{content}</p>,
}));

const task: CloudTask = {
  id: "run1",
  session_id: "session1",
  status: "running",
  model: "m",
  can_answer: false,
  result: null,
  error: null,
  question: null,
};
const base = {
  accountId: "A",
  model: "m",
  canStart: true,
  onAccepted: vi.fn(),
};
describe("the hosted Bot chat", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });
  afterEach(() => vi.restoreAllMocks());
  it("reuses the request id when the first cloud submission has an uncertain result", async () => {
    const submit = vi
      .spyOn(botCloudApi, "turn")
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce(task);
    render(<CloudChat {...base} />);
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "Write a digest" },
    });
    fireEvent.click(screen.getByRole("button", { name: "octopBot.send" }));
    await screen.findByText("offline");
    fireEvent.click(screen.getByRole("button", { name: "octopBot.send" }));
    await waitFor(() =>
      expect(base.onAccepted).toHaveBeenCalledWith("session1"),
    );
    expect(submit.mock.calls[1][0]).toEqual(submit.mock.calls[0][0]);
    expect(submit.mock.calls[0][0]).toMatchObject({
      account_id: "A",
      message: "Write a digest",
      model: "m",
    });
  });
  it("answers an existing task under the displayed account without overwriting its model or bot", async () => {
    const conversation = vi
      .spyOn(botCloudApi, "conversation")
      .mockResolvedValue({
        id: "session1",
        title: "Digest",
        model: "original",
        updated_at: "",
        items: [
          {
            role: "user",
            content: "Prior device's question",
            created_at: null,
            task_id: null,
          },
        ],
        tasks: [
          {
            ...task,
            status: "waiting_user",
            question: "Which day?",
            can_answer: true,
          },
        ],
      });
    const submit = vi.spyOn(botCloudApi, "turn").mockResolvedValue(task);
    render(<CloudChat {...base} sessionId="session1" canStart={false} />);
    await screen.findByText("Prior device's question");
    expect(conversation).toHaveBeenCalledWith("A", "session1");
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "Friday" },
    });
    fireEvent.click(screen.getByRole("button", { name: "octopBot.send" }));
    await waitFor(() => expect(base.onAccepted).toHaveBeenCalled());
    const body = JSON.parse(JSON.stringify(submit.mock.calls[0][0]));
    expect(body).toEqual({
      account_id: "A",
      session_id: "session1",
      input_task_id: "run1",
      request_id: expect.any(String),
      message: "Friday",
    });
  });
  it("keeps the local chat private until the user confirms the reviewed revision", async () => {
    vi.spyOn(botCloudApi, "previewImport").mockResolvedValue({
      title: "Weekly plan",
      revision: "rev",
      items: [{ role: "user", content: "Reviewed text" }],
    });
    const copy = vi
      .spyOn(botCloudApi, "importChat")
      .mockResolvedValue({ session_id: "cloud1" });
    const done = vi.fn();
    render(
      <CloudImport
        accountId="A"
        botId="bot1"
        threadId="local1"
        model="m"
        onDone={done}
        onClose={() => {}}
      />,
    );
    await screen.findByText("Reviewed text");
    expect(copy).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("button", { name: "botCloud.confirmImport" }),
    );
    await waitFor(() => expect(done).toHaveBeenCalledWith("cloud1"));
    expect(copy).toHaveBeenCalledExactlyOnceWith(
      "bot1",
      "local1",
      "A",
      "rev",
      "m",
    );
  });
});
