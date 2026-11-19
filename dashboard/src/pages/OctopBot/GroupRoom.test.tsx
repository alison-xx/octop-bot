import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { octopBotApi, type GroupMessage } from "../../api/modules/octopBot";
import GroupRoom from "./GroupRoom";

const sample: GroupMessage = {
  message_id: "message1",
  role: "assistant",
  agent_id: "writer",
  text: "Working draft",
  created_at: 123,
  request_id: "old",
};
const t = (key: string) => key;
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t }) }));
vi.mock("../../hooks/useServerTimezone", () => ({
  useServerTimezone: () => "UTC",
}));
vi.mock("../Chat/components/ExpertAgentAvatar", () => ({
  default: () => null,
}));
vi.mock("../../components/Markdown/LazyMarkdown", () => ({
  default: ({ content }: { content: string }) => <p>{content}</p>,
}));
vi.mock("../../api/modules/octopBot", () => ({
  octopBotApi: {
    messages: vi.fn(),
    goal: vi.fn(),
    drafts: vi.fn(),
    send: vi.fn(),
    upload: vi.fn(),
  },
}));

function group(id = "room") {
  return (
    <MemoryRouter>
      <GroupRoom
        group={{
          group_id: id,
          name: "Editorial",
          admin_id: "chief",
          member_ids: ["chief", "writer"],
          reply_mode: "admin_first",
        }}
        bots={[
          {
            agent_id: "chief",
            name: "Chief",
            is_main: true,
            is_private: false,
          },
          {
            agent_id: "writer",
            name: "Writer",
            is_main: false,
            is_private: false,
          },
        ]}
      />
    </MemoryRouter>
  );
}

function room(id = "room") {
  return render(group(id));
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

describe("Octop Bot group timeline", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(octopBotApi.messages).mockResolvedValue([sample]);
    vi.mocked(octopBotApi.goal).mockResolvedValue(null);
    vi.mocked(octopBotApi.drafts).mockResolvedValue([]);
  });
  it("sends a group upload without a text caption", async () => {
    const path = "inbound/upload1/report.txt";
    vi.mocked(octopBotApi.upload).mockResolvedValue({
      name: "report.txt",
      path,
      is_dir: false,
    });
    vi.mocked(octopBotApi.send).mockResolvedValue([]);
    const view = room();
    await screen.findByText("Working draft");
    const file = new File(["Hello"], "report.txt", { type: "text/plain" });
    fireEvent.change(view.container.querySelector('input[type="file"]')!, {
      target: { files: [file] },
    });
    await screen.findByText("report.txt");
    fireEvent.click(screen.getByRole("button", { name: "octopBot.send" }));
    await waitFor(() =>
      expect(octopBotApi.send).toHaveBeenCalledWith(
        "room",
        "",
        [],
        expect.any(String),
        [path],
      ),
    );
    await waitFor(() => expect(screen.queryByText("report.txt")).toBeNull());
  });
  it("keeps the browser request ID when retrying a failed send and addresses the selected member", async () => {
    vi.mocked(octopBotApi.send)
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValue([sample]);
    room();
    await screen.findByText("Working draft");
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "@Writer hello" },
    });
    const send = screen.getByRole("button", { name: "octopBot.send" });
    fireEvent.click(send);
    await screen.findByText("offline");
    fireEvent.click(
      screen.getByRole("button", { name: "botGroupChat.retrySend" }),
    );
    await waitFor(() => expect(octopBotApi.send).toHaveBeenCalledTimes(2));
    const [first, second] = vi.mocked(octopBotApi.send).mock.calls;
    expect(first.slice(0, 3)).toEqual(["room", "@Writer hello", ["writer"]]);
    expect(second[3]).toBe(first[3]);
    await waitFor(() => expect(screen.getByRole("textbox")).toHaveValue(""));
    expect(screen.getAllByText("Working draft")).toHaveLength(1);
  });
  it("keeps text and an in-flight attachment with their group while switching", async () => {
    const pending = deferred<{ name: string; path: string; is_dir: boolean }>();
    vi.mocked(octopBotApi.upload).mockReturnValue(pending.promise);
    const view = room("draft-a");
    const input = () => screen.getByRole("textbox");
    fireEvent.change(input(), { target: { value: "Draft A" } });
    fireEvent.change(view.container.querySelector("input[type=file]")!, {
      target: { files: [new File(["data"], "plan.txt")] },
    });
    expect(
      screen.getByRole("button", { name: "octopBot.send" }),
    ).toBeDisabled();
    view.rerender(group("draft-b"));
    expect(input()).toHaveValue("");
    fireEvent.change(input(), { target: { value: "Draft B" } });
    await act(async () =>
      pending.resolve({
        name: "plan.txt",
        path: "inbound/a/plan.txt",
        is_dir: false,
      }),
    );
    expect(screen.queryByText("plan.txt")).toBeNull();
    view.rerender(group("draft-a"));
    expect(input()).toHaveValue("Draft A");
    expect(screen.getByText("plan.txt")).toBeVisible();
    view.rerender(group("draft-b"));
    expect(input()).toHaveValue("Draft B");
    await screen.findByText("Working draft");
  });

  it("keeps successful uploads on either side of a failed file", async () => {
    vi.mocked(octopBotApi.upload)
      .mockResolvedValueOnce({
        name: "one.txt",
        path: "inbound/one.txt",
        is_dir: false,
      })
      .mockRejectedValueOnce(new Error("upload failed"))
      .mockResolvedValueOnce({
        name: "three.txt",
        path: "inbound/three.txt",
        is_dir: false,
      });
    const view = room("partial");
    fireEvent.change(view.container.querySelector("input[type=file]")!, {
      target: {
        files: ["one.txt", "two.txt", "three.txt"].map(
          (name) => new File(["text"], name),
        ),
      },
    });
    await screen.findByText("three.txt");
    expect(screen.getByText("one.txt")).toBeVisible();
    expect(screen.getByText("botGroupChat.uploadFailed")).toBeVisible();
    expect(screen.getByRole("button", { name: "octopBot.send" })).toBeEnabled();
  });
  it("retries the original payload after switching, while preserving the next draft", async () => {
    const first = deferred<GroupMessage[]>();
    vi.mocked(octopBotApi.send)
      .mockReturnValueOnce(first.promise)
      .mockResolvedValueOnce([]);
    const view = room("pending-a");
    const input = () => screen.getByRole("textbox");
    const send = () => screen.getByRole("button", { name: "octopBot.send" });
    fireEvent.change(input(), { target: { value: "@Writer first" } });
    fireEvent.click(send());
    fireEvent.change(input(), { target: { value: "Next draft" } });
    expect(send()).toBeDisabled();
    view.rerender(group("pending-b"));
    await act(async () => first.resolve([]));
    view.rerender(group("pending-a"));
    expect(input()).toHaveValue("Next draft");
    vi.mocked(octopBotApi.send)
      .mockReset()
      .mockRejectedValueOnce(new Error("connection lost"))
      .mockResolvedValueOnce([]);
    fireEvent.click(send());
    await screen.findByText("connection lost");
    fireEvent.change(input(), {
      target: { value: "Keep this while retrying" },
    });
    view.rerender(group("pending-b"));
    expect(screen.queryByText("connection lost")).toBeNull();
    view.rerender(group("pending-a"));
    fireEvent.click(
      screen.getByRole("button", { name: "botGroupChat.retrySend" }),
    );
    await waitFor(() => expect(octopBotApi.send).toHaveBeenCalledTimes(2));
    expect(vi.mocked(octopBotApi.send).mock.calls[1]).toEqual(
      vi.mocked(octopBotApi.send).mock.calls[0],
    );
    expect(input()).toHaveValue("Keep this while retrying");
  });
  it("replays a completed member error to that member using the original files", async () => {
    const original: GroupMessage = {
      ...sample,
      role: "user",
      agent_id: null,
      text: "Review this",
      attachment_paths: ["inbound/asset.csv"],
    };
    const failure: GroupMessage = {
      ...sample,
      message_id: "failed-row",
      role: "error",
      text: "Member offline",
    };
    vi.mocked(octopBotApi.messages).mockResolvedValue([original, failure]);
    vi.mocked(octopBotApi.send).mockResolvedValue([]);
    room("member-retry");
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "Separate draft" },
    });
    fireEvent.click(
      await screen.findByRole("button", { name: "botGroupChat.retryMember" }),
    );
    await waitFor(() =>
      expect(octopBotApi.send).toHaveBeenCalledWith(
        "member-retry",
        "Review this",
        ["writer"],
        "retry-failed-row",
        ["inbound/asset.csv"],
      ),
    );
    expect(screen.getByRole("textbox")).toHaveValue("Separate draft");
  });
  it("preserves the reader's position and counts newly polled messages", async () => {
    vi.useFakeTimers();
    try {
      vi.mocked(octopBotApi.messages)
        .mockResolvedValueOnce([sample])
        .mockResolvedValueOnce([
          { ...sample, message_id: "second", text: "New update" },
        ]);
      const view = room("scroll");
      await act(async () => {});
      const timeline = view.container.querySelector("article")!.parentElement!;
      Object.defineProperties(timeline, {
        scrollHeight: { value: 900, configurable: true },
        clientHeight: { value: 300, configurable: true },
        scrollTop: { value: 160, writable: true, configurable: true },
      });
      fireEvent.scroll(timeline);
      expect(
        screen.getByRole("button", { name: "botGroupChat.latest" }),
      ).toBeVisible();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2500);
      });
      expect(timeline.scrollTop).toBe(160);
      fireEvent.click(
        screen.getByRole("button", { name: "botGroupChat.newMessages" }),
      );
      expect(timeline.scrollTop).toBe(900);
      expect(
        screen.queryByRole("button", { name: "botGroupChat.newMessages" }),
      ).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });
});
