import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { OnboardingState } from "../../../api/modules/botOnboarding";
import { botGuideSeenKey } from "../../../utils/botClientRoute";
import { useOnboarding } from "./useOnboarding";

const api = vi.hoisted(() => ({
  read: vi.fn(),
  change: vi.fn(),
  account: vi.fn(),
  bridge: null as null | object,
  streamListener: null as null | ((event: { kind: string }) => void),
}));
vi.mock("../../../api/modules/botOnboarding", () => ({
  botOnboardingApi: { read: api.read, change: api.change },
}));
vi.mock("../../../api/modules/botCloud", () => ({
  botCloudApi: { account: api.account },
}));
vi.mock("../../../utils/desktopBridge", () => ({
  getDesktopBridge: () => api.bridge,
}));
vi.mock("../../Chat/hooks/chatStore", () => ({
  onStreamEvent: (listener: (event: { kind: string }) => void) => {
    api.streamListener = listener;
    return () => {
      api.streamListener = null;
    };
  },
}));

const state = (patch: Partial<OnboardingState> = {}): OnboardingState => ({
  show: true,
  status: "pending",
  step: "welcome",
  team: null,
  reason: null,
  ...patch,
});

afterEach(() => {
  vi.clearAllMocks();
  api.bridge = null;
  localStorage.clear();
  sessionStorage.clear();
});

describe("useOnboarding", () => {
  it("reads the owner's onboarding once the workspace is open", async () => {
    api.read.mockResolvedValue(state());
    const { result, rerender } = renderHook(
      ({ enabled }) => useOnboarding(enabled, 7),
      { initialProps: { enabled: false } },
    );
    expect(api.read).not.toHaveBeenCalled();
    rerender({ enabled: true });
    await waitFor(() => expect(result.current.state?.status).toBe("pending"));
  });

  it("does not guide again after the older desktop guide was seen", async () => {
    localStorage.setItem(botGuideSeenKey(7), "1");
    api.read.mockResolvedValue(state());
    api.change.mockResolvedValue(
      state({ show: false, status: "skipped", reason: "legacy" }),
    );
    const { result } = renderHook(() => useOnboarding(true, 7));
    await waitFor(() => expect(result.current.state?.status).toBe("skipped"));
    expect(api.change).toHaveBeenCalledWith({
      action: "skip",
      reason: "legacy",
    });
  });

  it("guides a desktop signed in to Lynxce on this computer too", async () => {
    // Signed in, Bots still run here (scheme C), so the guide does not wait for the cloud.
    api.bridge = { botOnly: true, useLynxceCloud: vi.fn() };
    api.account.mockResolvedValue({ connected: true });
    api.read.mockResolvedValue(state());
    const { result } = renderHook(() => useOnboarding(true, 7));
    await waitFor(() => expect(result.current.state?.show).toBe(true));
    expect(api.account).not.toHaveBeenCalled();
  });

  it("checks again after each reply while waiting for Chief's team", async () => {
    api.read.mockResolvedValue(state({ status: "active", step: "ask" }));
    const { result } = renderHook(() => useOnboarding(true, 7));
    await waitFor(() => expect(result.current.state?.step).toBe("ask"));
    api.read.mockResolvedValue(state({ status: "active", step: "team_ready" }));
    act(() => api.streamListener?.({ kind: "streamEnd" }));
    await waitFor(() => expect(result.current.state?.step).toBe("team_ready"));
    expect(api.streamListener).toBeNull();
  });

  it("hides the guide when skipping fails to reach the server", async () => {
    api.read.mockResolvedValue(state());
    api.change.mockRejectedValue(new Error("offline"));
    const { result } = renderHook(() => useOnboarding(true, 7));
    await waitFor(() => expect(result.current.state?.show).toBe(true));
    await act(async () => {
      expect(await result.current.change({ action: "skip" })).toBeNull();
    });
    expect(result.current.state?.show).toBe(false);
  });

  it("shows nothing when the server cannot be read", async () => {
    api.read.mockRejectedValue(new Error("offline"));
    const { result } = renderHook(() => useOnboarding(true, 7));
    await waitFor(() => expect(api.read).toHaveBeenCalled());
    expect(result.current.state).toBeNull();
  });
});
