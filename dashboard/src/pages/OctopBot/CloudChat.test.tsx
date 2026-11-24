import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { botCloudApi, type CloudTask } from "../../api/modules/botCloud";
import { lynxceWalletApi } from "../../api/modules/lynxceWallet";
import { octopBotApi } from "../../api/modules/octopBot";
import CloudChat from "./CloudChat";
import CloudImport from "./CloudImport";
import CloudWorkspace from "./CloudWorkspace";

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
  it("shows the signed-in cloud wallet on arrival and clears it on logout", async () => {
    vi.spyOn(botCloudApi, "account").mockResolvedValue({
      connected: true,
      account_id: "acct-cloud",
      display_name: "Cloud user",
    });
    vi.spyOn(botCloudApi, "logout").mockResolvedValue(undefined);
    vi.spyOn(botCloudApi, "capabilities").mockResolvedValue({
      enabled: true,
      reason: null,
      models: ["m"],
      default_model: "m",
    });
    vi.spyOn(botCloudApi, "sessions").mockResolvedValue({
      items: [],
      next_cursor: null,
    });
    vi.spyOn(octopBotApi, "workspace").mockResolvedValue({
      chief_id: "",
      bots: [],
      groups: [],
      pinned: [],
      sections: [],
      revision: 0,
    });
    const balance = vi.spyOn(lynxceWalletApi, "balance").mockResolvedValue({
      source: "cloud",
      account_id: "acct-cloud",
      connection_id: null,
      credits: 77,
      status: "available",
      recharge_mode: "ticket",
    });
    render(
      <MemoryRouter>
        <CloudWorkspace />
      </MemoryRouter>,
    );
    expect(await screen.findByText("77")).toBeInTheDocument();
    expect(balance).toHaveBeenCalledExactlyOnceWith(
      "cloud",
      expect.any(AbortSignal),
    );
    fireEvent.click(screen.getByRole("button", { name: "botCloud.signOut" }));
    await screen.findByRole("textbox", { name: "lynxceSignIn.target" });
    expect(screen.queryByText("77")).toBeNull();
    expect(screen.queryByText("botWallet.recharge")).toBeNull();
  });
  it("signs up in the cloud sign-in form itself and keeps the typed account", async () => {
    const status = vi.spyOn(botCloudApi, "account").mockResolvedValue({
      connected: false,
      account_id: null,
      display_name: null,
    });
    const login = vi.spyOn(botCloudApi, "login");
    render(
      <MemoryRouter>
        <CloudWorkspace />
      </MemoryRouter>,
    );
    // A code sign-in creates the account, so there is no separate sign-up page to visit.
    const input = await screen.findByRole("textbox", {
      name: "lynxceSignIn.target",
    });
    expect(screen.getByText("lynxceSignIn.newAccountHint")).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "botClient.lynxce.register" }),
    ).toBeNull();
    fireEvent.change(input, { target: { value: "example@account.test" } });
    // The system browser returning focus refreshes cloud status.
    fireEvent.focus(window);
    await waitFor(() => expect(status).toHaveBeenCalledTimes(2));
    expect(input).toHaveValue("example@account.test");
    expect(login).not.toHaveBeenCalled();
  });
  it("signs in to the cloud with a code sent to the phone", async () => {
    vi.spyOn(botCloudApi, "account").mockResolvedValue({
      connected: false,
      account_id: null,
      display_name: null,
    });
    const send = vi
      .spyOn(botCloudApi, "sendCode")
      .mockResolvedValue({ channel: "phone" });
    const login = vi.spyOn(botCloudApi, "codeLogin").mockResolvedValue({
      connected: true,
      account_id: "cloud",
      display_name: "Cloud",
    });
    render(
      <MemoryRouter>
        <CloudWorkspace />
      </MemoryRouter>,
    );
    fireEvent.change(
      await screen.findByRole("textbox", { name: "lynxceSignIn.target" }),
      { target: { value: "13800000000" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "lynxceSignIn.send" }));
    await waitFor(() => expect(send).toHaveBeenCalledWith("13800000000", "zh"));
    fireEvent.change(
      screen.getByRole("textbox", { name: "lynxceSignIn.code" }),
      {
        target: { value: "123456" },
      },
    );
    await waitFor(() =>
      expect(login).toHaveBeenCalledWith("13800000000", "123456", undefined),
    );
  });
  it("signs in with the WorkBuddy hand-off code from the desktop window", async () => {
    vi.spyOn(botCloudApi, "account").mockResolvedValue({
      connected: false,
      account_id: null,
      display_name: null,
    });
    const exchange = vi.spyOn(botCloudApi, "loginWorkbuddy").mockResolvedValue({
      connected: true,
      account_id: "acct-wb",
      display_name: "WorkBuddy user",
    });
    vi.spyOn(botCloudApi, "capabilities").mockResolvedValue({
      enabled: true,
      reason: null,
      models: ["m"],
      default_model: "m",
    });
    vi.spyOn(botCloudApi, "sessions").mockResolvedValue({
      items: [],
      next_cursor: null,
    });
    vi.spyOn(octopBotApi, "workspace").mockResolvedValue({
      chief_id: "",
      bots: [],
      groups: [],
      pinned: [],
      sections: [],
      revision: 0,
    });
    vi.spyOn(lynxceWalletApi, "balance").mockResolvedValue({
      source: "cloud",
      account_id: "acct-wb",
      connection_id: null,
      credits: 5,
      status: "available",
      recharge_mode: "ticket",
    });
    const workbuddyLogin = vi
      .fn()
      .mockResolvedValueOnce({ ok: false, reason: "denied" })
      .mockResolvedValueOnce({ ok: true, code: "handoff-code" });
    window.octopDesktop = {
      workbuddyLogin,
    } as unknown as typeof window.octopDesktop;
    try {
      render(
        <MemoryRouter>
          <CloudWorkspace />
        </MemoryRouter>,
      );
      const button = await screen.findByRole("button", {
        name: "botCloud.workbuddySignIn",
      });
      fireEvent.click(button);
      expect(
        await screen.findByText("botCloud.workbuddyDenied"),
      ).toBeInTheDocument();
      expect(exchange).not.toHaveBeenCalled();
      fireEvent.click(button);
      expect(await screen.findByText("WorkBuddy user")).toBeInTheDocument();
      expect(exchange).toHaveBeenCalledExactlyOnceWith("handoff-code");
    } finally {
      delete window.octopDesktop;
    }
  });
  beforeEach(() => {
    vi.clearAllMocks();
  });
  afterEach(() => {
    for (const api of [botCloudApi, lynxceWalletApi, octopBotApi]) {
      for (const method of Object.values(api)) {
        if (vi.isMockFunction(method)) method.mockRestore();
      }
    }
  });
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
