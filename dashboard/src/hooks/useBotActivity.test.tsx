import type { ReactNode } from "react";
import { App } from "antd";
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { BotActivitySnapshot } from "@/api/modules/botActivity";

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

function render(openTarget: string) {
  return renderHook(
    () =>
      useBotActivity({
        enabled: true,
        openTarget,
        nameOf: () => "Bot",
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
