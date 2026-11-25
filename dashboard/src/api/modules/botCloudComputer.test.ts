import { beforeEach, expect, it, vi } from "vitest";
import { request } from "../request";
import { botCloudComputerApi as api } from "./botCloudComputer";

vi.mock("../request", () => ({ request: vi.fn() }));
const send = vi.mocked(request);
beforeEach(() => send.mockReset());

it("uses fixed paths and a header for the lifetime of a negotiated session", async () => {
  send.mockResolvedValueOnce({
    ws_path: "/api/octop-bot/computers/writer/screen/ws?ticket=once",
    session_transport: "header",
    session: "local-session",
    session_expires_in: 1800,
  });
  const { session } = await api.openScreen("writer");
  await api.typeText(session, "中文");
  await api.readClipboard(session);
  expect(send.mock.calls.map(([path]) => path)).toEqual([
    "/octop-bot/computers/writer/screen",
    "/octop-bot/screen-sessions/type",
    "/octop-bot/screen-sessions/clipboard",
  ]);
  expect(send.mock.calls[0][1]?.headers).toEqual({
    "X-Octop-Screen-Transport": "header",
  });
  expect(send.mock.calls[1][1]?.headers).toEqual({
    "X-Octop-Screen-Session": "local-session",
  });
  expect(send.mock.calls[2][1]?.headers).toEqual({
    "X-Octop-Screen-Session": "local-session",
  });
});

it("keeps the legacy desktop cloud connection view-only", async () => {
  send.mockResolvedValueOnce({ session_transport: null, session: "" });
  const { session } = await api.openScreen("writer");
  expect(session).toEqual({ viewOnly: true });
  expect(() => api.readClipboard(session)).toThrow();
  expect(send).toHaveBeenCalledTimes(1);
});
