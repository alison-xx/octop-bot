import type { ReactNode } from "react";
import { App } from "antd";
import {
  act,
  fireEvent,
  renderHook,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { BotActivitySnapshot } from "@/api/modules/botActivity";
import type { BotWorkspace, WorkspaceBot } from "@/api/modules/octopBot";

const read = vi.fn<() => Promise<BotActivitySnapshot>>();
const markRead = vi.fn(() => Promise.resolve());
const markGroupRead = vi.fn(() => Promise.resolve());

vi.mock("@/api/modules/botActivity", () => ({
  botActivityApi: {
    read: () => read(),
    markGroupRead: (id: string) => markGroupRead(id),
  },
}));
vi.mock("@/api/modules/octopAgents", () => ({
  octopAgentsApi: { markRead: (id: string) => markRead(id) },
}));
vi.mock("@/utils/desktopBridge", () => ({ getDesktopBridge: () => null }));

import { useBotActivity } from "./useBotActivity";

const snapshot = (lastActive: number, groupUnread = 0): BotActivitySnapshot =>
  ({
    bots: [{ agent_id: "a", unread_count: 0, last_active: lastActive }],
    groups: [{ group_id: "g", unread_count: groupUnread, last_message: null }],
  }) as unknown as BotActivitySnapshot;

const wrapper = ({ children }: { children: ReactNode }) => (
  <App>{children}</App>
);

const writer: WorkspaceBot = {
  agent_id: "writer",
  name: "Writer",
  is_main: false,
  is_private: false,
  state: "running",
  preparing: false,
  last_error: null,
  icon_url: "/writer.png",
  avatar: { source: "photo", shape: "orb", color: "blue" },
};
const workspace: Pick<BotWorkspace, "bots" | "groups"> = {
  bots: [
    {
      ...writer,
      agent_id: "a",
      name: "Chief",
      icon_url: "/chief.png",
      is_main: true,
    },
    writer,
  ],
  groups: [
    {
      group_id: "g",
      name: "Studio",
      admin_id: "a",
      member_ids: ["a", "writer"],
      reply_mode: "all_members",
    },
  ],
};

function render(openTarget: string) {
  return renderHook(
    () =>
      useBotActivity({
        enabled: true,
        openTarget,
        workspace,
        onOpen: () => undefined,
      }),
    { wrapper },
  );
}

describe("useBotActivity", () => {
  let focused = true;
  beforeEach(() => {
    focused = true;
    window.localStorage.clear();
    vi.spyOn(document, "hasFocus").mockImplementation(() => focused);
    read.mockReset();
    markRead.mockClear();
    markGroupRead.mockClear();
  });
  afterEach(() => vi.restoreAllMocks());

  it("shows each sender's sidebar portrait and falls back to their character or the group", async () => {
    read.mockResolvedValueOnce(snapshot(100));
    const { result } = render("bot:other");
    await waitFor(() => expect(result.current.recent["bot:a"]).toBe(100));
    const incoming = snapshot(200, 1);
    incoming.groups[0].last_message = {
      message_id: "1",
      role: "assistant",
      agent_id: "writer",
      text: "Here it is",
      created_at: 200,
    };
    read.mockResolvedValueOnce(incoming);
    act(() => result.current.refresh());
    const direct = await screen.findByRole("button", { name: /Chief/ });
    expect(direct.querySelector('[data-bot-avatar="a"] img')).toHaveAttribute(
      "src",
      "/chief.png",
    );
    const group = await screen.findByRole("button", {
      name: /Studio.*Writer: Here it is/,
    });
    const portrait = group.querySelector('[data-bot-avatar="writer"] img')!;
    expect(portrait).toHaveAttribute("src", "/writer.png");
    fireEvent.error(portrait);
    expect(
      group.querySelector('[data-bot-avatar="writer"][data-shape="orb"] svg'),
    ).toBeInTheDocument();
    read.mockResolvedValueOnce(snapshot(200, 2));
    act(() => result.current.refresh());
    await waitFor(() =>
      expect(
        group.querySelector('[data-group-avatar] [data-bot-avatar="a"]'),
      ).toBeInTheDocument(),
    );
  });
  it("counts replies in the open chat while the window is in the background", async () => {
    read.mockResolvedValueOnce(snapshot(100));
    const { result } = render("bot:a");
    await waitFor(() => expect(read).toHaveBeenCalledTimes(1));

    focused = false;
    read.mockResolvedValueOnce(snapshot(200));
    act(() => result.current.refresh());
    await waitFor(() => expect(result.current.unread["bot:a"]).toBe(1));

    focused = true;
    read.mockResolvedValueOnce(snapshot(200));
    act(() => window.dispatchEvent(new Event("focus")));
    await waitFor(() => expect(result.current.unread["bot:a"]).toBeUndefined());
  });

  it("does not mark the open group read until the window is focused", async () => {
    focused = false;
    read.mockResolvedValue(snapshot(0, 2));
    const { result } = render("group:g");
    await waitFor(() => expect(result.current.unread["group:g"]).toBe(2));
    expect(markGroupRead).not.toHaveBeenCalled();

    focused = true;
    act(() => window.dispatchEvent(new Event("focus")));
    await waitFor(() => expect(markGroupRead).toHaveBeenCalledWith("g"));
    expect(result.current.unread["group:g"]).toBeUndefined();
  });
});
