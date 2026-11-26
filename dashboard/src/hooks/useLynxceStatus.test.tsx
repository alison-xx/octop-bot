import { act, renderHook, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { lynxceBotApi } from "../api/modules/lynxceBot";
import { refreshBotModels, useLynxceStatus } from "./useLynxceStatus";

vi.mock("../api/modules/lynxceBot", () => ({
  lynxceBotApi: { status: vi.fn() },
}));
vi.mock("./useCurrentUser", () => ({
  useCurrentUser: () => ({ username: "local" }),
}));

it("updates the local workspace model after selecting or removing a personal key without a Lynxce login", async () => {
  const read = vi.mocked(lynxceBotApi.status);
  read.mockResolvedValue({ connected: false, selected_model: null });
  const { result } = renderHook(() => useLynxceStatus(true));
  await waitFor(() => expect(result.current.status?.connected).toBe(false));
  expect(result.current.workspaceModel).toBeNull();

  read.mockResolvedValue({
    connected: false,
    selected_model: "deepseek-v4-flash",
  });
  act(() => {
    window.dispatchEvent(new Event("focus"));
  });
  await waitFor(() =>
    expect(result.current.workspaceModel).toBe("deepseek-v4-flash"),
  );

  read.mockResolvedValue({ connected: false, selected_model: null });
  act(() => refreshBotModels());
  await waitFor(() => expect(result.current.workspaceModel).toBeNull());
});
