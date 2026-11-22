import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
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
    room("partial");
    const input = screen.getByRole("textbox");
    const transfer = {
      dataTransfer: {
        types: ["Files"],
        files: ["one.txt", "two.txt", "three.txt"].map(
          (name) => new File(["text"], name),
        ),
      },
    };
    expect(fireEvent.dragOver(input, transfer)).toBe(false);
    expect(screen.getByText("botGroupChat.dropFiles")).toBeVisible();
    expect(fireEvent.drop(input, transfer)).toBe(false);
    expect(screen.queryByText("botGroupChat.dropFiles")).toBeNull();
    await screen.findByText("three.txt");
    expect(screen.getByText("one.txt")).toBeVisible();
    expect(screen.getByText("botGroupChat.uploadFailed")).toBeVisible();
    expect(screen.getByRole("button", { name: "octopBot.send" })).toBeEnabled();
  });
  it("reports folder and over-limit drops without intercepting text drags", async () => {
    room("drop-limits");
    await screen.findByText("Working draft");
    const input = screen.getByRole("textbox");
    const file = new File(["text"], "note.txt");
    expect(
      fireEvent.dragOver(input, {
        dataTransfer: { types: ["text/plain"], files: [] },
      }),
    ).toBe(true);
    expect(screen.queryByText("botGroupChat.dropFiles")).toBeNull();
    fireEvent.drop(input, {
      dataTransfer: {
        types: ["Files"],
        files: [],
        items: [{ webkitGetAsEntry: () => ({ isDirectory: true }) }],
      },
    });
    expect(screen.getByText("botGroupChat.folderDrop")).toBeVisible();
    fireEvent.drop(input, {
      dataTransfer: { types: ["Files"], files: Array(17).fill(file) },
    });
    expect(screen.getByText("octopBot.attachmentLimit")).toBeVisible();
    expect(octopBotApi.upload).not.toHaveBeenCalled();
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
  it("shows a retry instead of the empty-room welcome when history fails to load", async () => {
    vi.mocked(octopBotApi.messages)
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValue([sample]);
    room("broken");
    await screen.findByText("offline");
    expect(screen.queryByText("octopBot.groupWelcome")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "octopBot.retry" }));
    await screen.findByText("Working draft");
    expect(screen.queryByText("offline")).toBeNull();
  });
  it("returns focus to the composer after sending with the button", async () => {
    vi.mocked(octopBotApi.send).mockResolvedValue([]);
    room("focus");
    await screen.findByText("Working draft");
    const box = screen.getByRole("textbox");
    fireEvent.change(box, { target: { value: "hello" } });
    fireEvent.click(screen.getByRole("button", { name: "octopBot.send" }));
    expect(box).toHaveFocus();
    await waitFor(() => expect(octopBotApi.send).toHaveBeenCalled());
  });
  it("addresses members whose names contain spaces", async () => {
    vi.mocked(octopBotApi.send).mockResolvedValue([]);
    render(
      <MemoryRouter>
        <GroupRoom
          group={{
            group_id: "spaces",
            name: "Editorial",
            admin_id: "chief",
            member_ids: ["chief", "writer"],
            reply_mode: "admin_first",
          }}
          bots={[
            {
              agent_id: "chief",
              name: "Editor",
              is_main: true,
              is_private: false,
            },
            {
              agent_id: "writer",
              name: "Content Writer",
              is_main: false,
              is_private: false,
            },
          ]}
        />
      </MemoryRouter>,
    );
    await screen.findByText("Working draft");
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "@Editor @Content Writer draft it" },
    });
    fireEvent.click(screen.getByRole("button", { name: "octopBot.send" }));
    await waitFor(() =>
      expect(vi.mocked(octopBotApi.send).mock.calls[0][2]).toEqual([
        "chief",
        "writer",
      ]),
    );
  });
  describe("polling", () => {
    let visibility: DocumentVisibilityState;
    beforeEach(() => {
      visibility = "visible";
      Object.defineProperty(document, "visibilityState", {
        configurable: true,
        get: () => visibility,
      });
      vi.useFakeTimers();
    });
    afterEach(() => {
      vi.useRealTimers();
      // Fall back to jsdom's own getter on the prototype.
      delete (document as { visibilityState?: unknown }).visibilityState;
    });
    const advance = (ms: number) =>
      act(async () => {
        await vi.advanceTimersByTimeAsync(ms);
      });
    const setVisibility = async (next: DocumentVisibilityState) => {
      visibility = next;
      await act(async () => {
        document.dispatchEvent(new Event("visibilitychange"));
      });
    };

    it("pauses while the tab is hidden and refreshes as soon as it is visible", async () => {
      room("hidden");
      await act(async () => {});
      expect(octopBotApi.messages).toHaveBeenCalledTimes(1);
      await setVisibility("hidden");
      await advance(60_000);
      expect(octopBotApi.messages).toHaveBeenCalledTimes(1);
      await setVisibility("visible");
      expect(octopBotApi.messages).toHaveBeenCalledTimes(2);
      await advance(2500);
      expect(octopBotApi.messages).toHaveBeenCalledTimes(3);
    });

    it("does not start a timer when mounted in a hidden tab", async () => {
      visibility = "hidden";
      room("background");
      await act(async () => {});
      await advance(60_000);
      expect(octopBotApi.messages).toHaveBeenCalledTimes(1);
      await setVisibility("visible");
      expect(octopBotApi.messages).toHaveBeenCalledTimes(2);
    });

    it("backs off once the room is quiet and speeds up while a member is replying", async () => {
      vi.mocked(octopBotApi.messages)
        .mockResolvedValueOnce([sample])
        .mockResolvedValue([]);
      room("quiet");
      await act(async () => {});
      // Four quiet polls keep the fast cadence, then the idle interval applies.
      await advance(4 * 2500);
      expect(octopBotApi.messages).toHaveBeenCalledTimes(5);
      await advance(2500);
      expect(octopBotApi.messages).toHaveBeenCalledTimes(5);
      vi.mocked(octopBotApi.drafts).mockResolvedValue([
        { agent_id: "writer", request_id: "r1", text: "Typing" },
      ]);
      await advance(7500);
      expect(octopBotApi.messages).toHaveBeenCalledTimes(6);
      await advance(2500);
      expect(octopBotApi.messages).toHaveBeenCalledTimes(7);
      await advance(2500);
      expect(octopBotApi.messages).toHaveBeenCalledTimes(8);
    });

    it("polls immediately when a send starts in an idle room", async () => {
      vi.mocked(octopBotApi.messages)
        .mockResolvedValueOnce([sample])
        .mockResolvedValue([]);
      const pending = deferred<never[]>();
      vi.mocked(octopBotApi.send).mockReturnValue(pending.promise);
      room("idle-send");
      await act(async () => {});
      await advance(5 * 2500);
      const before = vi.mocked(octopBotApi.messages).mock.calls.length;
      fireEvent.change(screen.getByRole("textbox"), {
        target: { value: "hello" },
      });
      await act(async () => {
        fireEvent.click(screen.getByRole("button", { name: "octopBot.send" }));
      });
      expect(octopBotApi.messages).toHaveBeenCalledTimes(before + 1);
      await advance(2500);
      expect(octopBotApi.messages).toHaveBeenCalledTimes(before + 2);
      await act(async () => pending.resolve([]));
    });
  });
});
