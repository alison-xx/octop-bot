import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiResponseError } from "../../../api/responseError";
import { emitSessionEvent } from "./chatStore";
import {
  pickPreferredSession,
  resetSessionStoreForTests,
  sortSessions,
  toSession,
  useSessions,
  type Session,
} from "./useSessions";

const listMock = vi.fn();
const createMock = vi.fn();
const historyMock = vi.fn();

vi.mock("../../../api/modules/octopThreads", () => ({
  octopThreadsApi: {
    list: (...args: unknown[]) => listMock(...args),
    create: (...args: unknown[]) => createMock(...args),
    history: (...args: unknown[]) => historyMock(...args),
    delete: vi.fn(),
    patch: vi.fn(),
    rename: vi.fn(),
    rebind: vi.fn(),
  },
  normalizeThreadArtifacts: () => [],
}));

function threadRow(threadId: string, agentExtra?: Partial<{ title: string }>) {
  return {
    thread_id: threadId,
    title: agentExtra?.title ?? null,
    last_active: 1,
    created_at: 1,
    channel_type: "dashboard",
    is_active: false,
    has_messages: true,
    pinned: false,
  };
}

describe("toSession / sortSessions ordering", () => {
  it("sorts empty new chats by created_at above older active ones", () => {
    const olderActive = toSession({
      thread_id: "thr_old",
      title: "old",
      last_active: 100,
      created_at: 10,
      has_messages: true,
    });
    const emptyNew = toSession({
      thread_id: "thr_new",
      title: null,
      last_active: 0,
      created_at: 200,
      has_messages: false,
    });
    expect(
      sortSessions([olderActive, emptyNew]).map((s: Session) => s.id),
    ).toEqual(["thr_new", "thr_old"]);
  });

  it("keeps pinned sessions first", () => {
    const pinned = toSession({
      thread_id: "thr_pin",
      title: "pin",
      last_active: 1,
      created_at: 1,
      pinned: true,
    });
    const recent = toSession({
      thread_id: "thr_recent",
      title: "recent",
      last_active: 999,
      created_at: 999,
    });
    expect(sortSessions([recent, pinned]).map((s) => s.id)).toEqual([
      "thr_pin",
      "thr_recent",
    ]);
  });

  it("maps turn_active and awaiting_user onto the session", () => {
    const session = toSession({
      thread_id: "thr_work",
      title: "busy",
      last_active: 1,
      turn_active: true,
      awaiting_user: true,
    });
    expect(session.turnActive).toBe(true);
    expect(session.awaitingUser).toBe(true);
  });
});

describe("pickPreferredSession", () => {
  it("never opens a Bot group work thread as the private chat", () => {
    const group = toSession({
      thread_id: "thr_group",
      title: "群聊 · Room",
      last_active: 200,
      channel_type: "octop_bot_group",
    });
    const own = toSession({
      thread_id: "thr_own",
      title: null,
      last_active: 0,
    });
    expect(pickPreferredSession([group, own])?.id).toBe("thr_own");
    expect(pickPreferredSession([group])).toBeNull();
  });
});

describe("useSessions agent switch", () => {
  beforeEach(() => {
    resetSessionStoreForTests();
    listMock.mockReset();
    historyMock.mockReset();
    createMock.mockReset();
  });

  afterEach(() => {
    resetSessionStoreForTests();
  });

  it("clears previous-agent threads on the first render of a new agent", async () => {
    listMock.mockImplementation(async (agentId: string) => {
      if (agentId === "agent-a") {
        return [threadRow("thr_from_a")];
      }
      // Keep B's fetch pending so we can observe the sync clear.
      return new Promise(() => {});
    });

    const { result, rerender } = renderHook(
      ({ agentId }: { agentId: string | null }) => useSessions(agentId),
      { initialProps: { agentId: "agent-a" } },
    );

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
      expect(result.current.sessions.map((s) => s.id)).toEqual(["thr_from_a"]);
    });

    rerender({ agentId: "agent-b" });

    // Critical: no one-frame leak of agent-a's thr_* into agent-b.
    expect(result.current.sessions).toEqual([]);
    expect(result.current.loading).toBe(true);
    expect(result.current.sessions.some((s) => s.id === "thr_from_a")).toBe(
      false,
    );
  });

  it("ensureThreadInList returns unknown on probe network errors", async () => {
    listMock.mockResolvedValue([]);
    historyMock.mockRejectedValueOnce(new Error("network down"));

    const { result } = renderHook(() => useSessions("agent-new"));

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    let probe: string | undefined;
    await act(async () => {
      probe = await result.current.ensureThreadInList("thr_foreign");
    });
    expect(probe).toBe("unknown");
  });

  it("retains a deep link to a thread beyond the list probe", async () => {
    listMock.mockResolvedValue(
      Array.from({ length: 51 }, (_, i) => threadRow("recent-" + i)),
    );
    historyMock.mockResolvedValue({ thread_id: "older", messages: [] });
    const { result } = renderHook(() => useSessions("agent-new"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(await result.current.ensureThreadInList("older")).toBe("found");
    expect(historyMock).toHaveBeenCalledWith("agent-new", "older", {
      limit: 1,
    });
  });

  it("ensureThreadInList returns missing when probe confirms absence", async () => {
    historyMock.mockRejectedValueOnce(new ApiResponseError(404, null, null));
    listMock.mockResolvedValue([]);

    const { result } = renderHook(() => useSessions("agent-new"));

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    let probe: string | undefined;
    await act(async () => {
      probe = await result.current.ensureThreadInList("thr_foreign");
    });
    expect(probe).toBe("missing");
  });

  it("ensureThreadInList returns found when the thread is already listed", async () => {
    listMock.mockResolvedValue([threadRow("thr_ok")]);

    const { result } = renderHook(() => useSessions("agent-new"));

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
      expect(result.current.sessions.map((s) => s.id)).toEqual(["thr_ok"]);
    });

    let probe: string | undefined;
    await act(async () => {
      probe = await result.current.ensureThreadInList("thr_ok");
    });
    expect(probe).toBe("found");
    expect(listMock).toHaveBeenCalledTimes(1);
  });

  it("keeps another agent's delayed title off the pending chat", async () => {
    listMock.mockResolvedValue([]);
    createMock.mockReturnValue(new Promise(() => {}));

    const { result } = renderHook(() => useSessions("agent-b"));
    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });
    act(() => {
      result.current.createSession();
    });
    expect(result.current.sessions[0]?.id).toBe("__pending__");

    act(() => {
      emitSessionEvent({
        kind: "sessionRenamed",
        sessionId: "thr_a",
        agentId: "agent-a",
        title: "来自 A",
      });
    });
    expect(result.current.sessions[0]?.name).toBe("New Chat");

    act(() => {
      emitSessionEvent({
        kind: "sessionRenamed",
        sessionId: "thr_b",
        agentId: "agent-b",
        title: "本会话",
        provisional: true,
      });
    });
    expect(result.current.sessions[0]?.name).toBe("本会话");
  });
});
