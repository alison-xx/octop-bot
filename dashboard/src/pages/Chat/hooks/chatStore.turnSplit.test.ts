import { deriveMessageContent } from "../utils/messageContent";
import { afterEach, expect, it, vi } from "vitest";
import {
  appendUserMessage,
  getSnapshot,
  ingestHarnessChunk,
  onSharedTurnBusy,
  removeSession,
  sendTurn,
  setMessages,
  setSessionTeamRoom,
  sharedTurnBlocksSender,
  subscribe,
} from "./chatStore";

const SESSION = "turn-split";

afterEach(() => {
  removeSession(SESSION);
  vi.unstubAllGlobals();
});

it("keeps assistant replies from different turns in separate bubbles", () => {
  ingestHarnessChunk(SESSION, {
    type: "token",
    content: "first",
    turn_id: "turn-a",
  });
  ingestHarnessChunk(SESSION, {
    type: "token",
    content: "second",
    turn_id: "turn-b",
  });
  const assistants = getSnapshot(SESSION).messages.filter(
    (message) => message.role === "assistant",
  );
  expect(assistants.map((message) => message.content)).toEqual([
    "first",
    "second",
  ]);
  expect(assistants.map((message) => message.turnId)).toEqual([
    "turn-a",
    "turn-b",
  ]);
});

it("does not continue a restored bubble from another turn", () => {
  setMessages(SESSION, [
    {
      id: "u",
      role: "user",
      content: "问题",
      timestamp: 1,
      turnId: "turn-a",
    },
    {
      id: "a",
      role: "assistant",
      content: "半截",
      status: "streaming",
      timestamp: 2,
      turnId: "turn-a",
    },
  ]);
  ingestHarnessChunk(SESSION, {
    type: "token",
    content: "另一轮",
    turn_id: "turn-b",
  });
  const assistants = getSnapshot(SESSION).messages.filter(
    (message) => message.role === "assistant",
  );
  expect(assistants.map((message) => message.content)).toEqual([
    "半截",
    "另一轮",
  ]);
  expect(assistants.map((message) => message.turnId)).toEqual([
    "turn-a",
    "turn-b",
  ]);
});

it("still concatenates tokens that belong to the same turn", () => {
  ingestHarnessChunk(SESSION, {
    type: "token",
    content: "hel",
    turn_id: "turn-a",
  });
  ingestHarnessChunk(SESSION, {
    type: "token",
    content: "lo",
    turn_id: "turn-a",
  });
  expect(
    getSnapshot(SESSION).messages.map((message) => message.content),
  ).toEqual(["hello"]);
});

class Socket {
  static instances: Socket[] = [];
  readyState = 0;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor() {
    Socket.instances.push(this);
    queueMicrotask(() => {
      this.readyState = 1;
      this.onopen?.();
    });
  }
  send(_data: string) {}
  close() {
    this.readyState = 3;
    this.onclose?.();
  }
  frame(data: object) {
    this.onmessage?.({ data: JSON.stringify(data) });
  }
}

it("blocks another user while a shared turn is running and drops a rejected send", async () => {
  Socket.instances = [];
  vi.stubGlobal("WebSocket", Socket);
  const notices: string[] = [];
  const unsubscribe = onSharedTurnBusy((event) => {
    notices.push(event.messageId);
  });
  const sent = sendTurn(
    SESSION,
    "question",
    "agent",
    "",
    undefined,
    undefined,
    null,
    SESSION,
  );
  await Promise.resolve();
  const socket = Socket.instances[0];
  socket.frame({ type: "turn.started", turn_id: "live" });
  socket.frame({
    type: "user",
    message_id: "owner-msg",
    content: "question",
    author: { user_id: 7, display_name: "Ada", username: "ada" },
  });
  expect(sharedTurnBlocksSender(SESSION, 8, true)).toBe(true);
  expect(sharedTurnBlocksSender(SESSION, 7, true)).toBe(false);
  expect(sharedTurnBlocksSender(SESSION, 8, false)).toBe(false);

  appendUserMessage(SESSION, {
    id: "other-msg",
    role: "user",
    content: "meanwhile",
    timestamp: 1,
  });
  socket.frame({
    type: "turn.busy",
    message_id: "other-msg",
    reason: "shared_turn_busy",
  });
  expect(
    getSnapshot(SESSION).messages.some((message) => message.id === "other-msg"),
  ).toBe(false);
  expect(notices).toEqual(["other-msg"]);
  expect(getSnapshot(SESSION).isStreaming).toBe(true);

  socket.frame({ type: "turn.ended", turn_id: "live" });
  await sent;
  expect(sharedTurnBlocksSender(SESSION, 8, true)).toBe(false);
  unsubscribe();
});

it("releases the composer when a shared turn rejects the send", async () => {
  Socket.instances = [];
  vi.stubGlobal("WebSocket", Socket);
  const notices: string[] = [];
  const unsubscribe = onSharedTurnBusy((event) => {
    notices.push(event.messageId);
  });
  const sent = sendTurn(
    SESSION,
    "meanwhile",
    "agent",
    "",
    undefined,
    undefined,
    null,
    SESSION,
    null,
    null,
    null,
    undefined,
    null,
    null,
    null,
    "rejected-msg",
  );
  await Promise.resolve();
  const socket = Socket.instances[0];
  socket.frame({
    type: "turn.busy",
    message_id: "rejected-msg",
    reason: "shared_turn_busy",
  });
  await sent;
  expect(notices).toEqual(["rejected-msg"]);
  expect(getSnapshot(SESSION).isStreaming).toBe(false);
  unsubscribe();
});

it("blocks another user while a shared team member is still speaking", async () => {
  const session = "turn-split-team";
  Socket.instances = [];
  vi.stubGlobal("WebSocket", Socket);
  setSessionTeamRoom(session, true);
  const sent = sendTurn(
    session,
    "question",
    "team-host",
    "",
    undefined,
    undefined,
    null,
    session,
  );
  await Promise.resolve();
  const socket = Socket.instances[0];
  socket.frame({ type: "turn.started", turn_id: "host-turn" });
  socket.frame({
    type: "user",
    message_id: "owner-msg",
    content: "question",
    author: { user_id: 7, display_name: "Ada", username: "ada" },
  });
  socket.frame({ type: "turn.ended", turn_id: "host-turn" });
  ingestHarnessChunk(session, {
    type: "token",
    content: "member",
    turn_id: "host-turn",
    agent_id: "member-1",
  });
  expect(sharedTurnBlocksSender(session, 8, true)).toBe(true);
  expect(sharedTurnBlocksSender(session, 7, true)).toBe(false);
  ingestHarnessChunk(session, {
    type: "token",
    content: "next",
    turn_id: "later-turn",
    agent_id: "member-1",
  });
  expect(
    getSnapshot(session)
      .messages.filter((message) => message.speakerAgentId === "member-1")
      .map((message) => message.content),
  ).toEqual(["member", "next"]);
  removeSession(session);
  await sent;
});

it("paints growing answer snapshots after reasoning before the server finishes", async () => {
  Socket.instances = [];
  vi.stubGlobal("WebSocket", Socket);
  const sent = sendTurn(
    SESSION,
    "question",
    "agent",
    "",
    undefined,
    undefined,
    null,
    SESSION,
  );
  await Promise.resolve();
  const socket = Socket.instances[0];
  const paints: string[] = [];
  const unsubscribe = subscribe(SESSION, () => {
    const last = getSnapshot(SESSION).messages.at(-1);
    if (last?.role === "assistant")
      paints.push(deriveMessageContent(last).textContent);
  });
  try {
    socket.frame({ type: "turn.started", turn_id: "live" });
    socket.frame({ type: "reasoning", content: "think", turn_id: "live" });
    socket.frame({ type: "token", content: "First", turn_id: "live" });
    await vi.waitFor(() => expect(paints).toContain("First"));
    socket.frame({
      type: "token",
      content: "First and second",
      turn_id: "live",
    });
    await vi.waitFor(() => expect(paints).toContain("First and second"));
    socket.frame({ type: "token", content: " and third", turn_id: "live" });
    await vi.waitFor(() =>
      expect(paints).toContain("First and second and third"),
    );
  } finally {
    unsubscribe();
    socket.frame({ type: "turn.ended", turn_id: "live" });
    socket.frame({ type: "done" });
    await sent;
  }
});

it("keeps concurrent media progress tied to its call and times delivery until the result frame", () => {
  vi.spyOn(Date, "now").mockReturnValue(10000);
  try {
    for (const [index, id] of ["pic", "video"].entries())
      ingestHarnessChunk(SESSION, {
        type: "tool_call_chunk",
        id,
        index,
        name: id === "pic" ? "generate_image" : "generate_video",
        args: "{}",
      });
    const update = (id: string, phase: string) =>
      ingestHarnessChunk(SESSION, {
        type: "custom",
        data: { kind: "media_progress", phase, call_id: id },
      });
    update("pic", "delivering");
    update("video", "generating");
    vi.mocked(Date.now).mockReturnValue(12400);
    ingestHarnessChunk(SESSION, {
      type: "tool_result",
      messages: [{ tool_call_id: "pic", content: "done" }],
    });
    const messages = getSnapshot(SESSION).messages;
    expect(
      messages.find((m) => m.toolData?.callId === "pic")?.toolData
        ?.deliveryToChatMs,
    ).toBe(2400);
    expect(
      messages.find((m) => m.toolData?.callId === "video")?.toolData
        ?.mediaProgress?.phase,
    ).toBe("generating");
  } finally {
    vi.restoreAllMocks();
  }
});
