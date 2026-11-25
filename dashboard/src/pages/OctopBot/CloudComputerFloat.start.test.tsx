import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  botCloudComputerApi,
  type CloudComputerStatus,
} from "../../api/modules/botCloudComputer";
import { ApiResponseError } from "../../api/responseError";
import CloudComputerHandoff from "./CloudComputerHandoff";
import CloudComputerFloat, {
  nextMode,
  toggleCloudFloat,
} from "./CloudComputerFloat";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}));
vi.mock(import("../../api/modules/botCloudComputer"), async (original) => ({
  ...(await original()),
  botCloudComputerApi: {
    ...(await original()).botCloudComputerApi,
    status: vi.fn(),
    glance: vi.fn(),
    openScreen: vi.fn(),
    takeover: vi.fn(),
  },
}));
vi.mock("./CloudComputerScreen", () => ({
  default: () => <div>live screen</div>,
}));

const off: CloudComputerStatus = {
  state: "paused",
  spec: "standard",
  running_since: null,
  paid_until: null,
  takeover: false,
  busy: false,
  activity: null,
  activity_at: null,
};
const api = vi.mocked(botCloudComputerApi);

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  api.status.mockResolvedValue(off);
  api.glance.mockRejectedValue(new Error("off"));
});

describe("opening the cloud computer from its icon", () => {
  it.each([false, true])(
    "opens only one handoff screen (legacy read-only: %s)",
    async (readOnly) => {
      api.status.mockResolvedValue({ ...off, state: "running" });
      api.takeover.mockResolvedValue({
        ...off,
        state: "running",
        takeover: true,
      });
      api.openScreen.mockResolvedValue({
        ws_path: "/ws",
        session: readOnly ? { viewOnly: true } : "s",
        expires_in: 60,
      });
      render(
        <>
          <CloudComputerFloat botId="writer" botName="Writer" />
          <CloudComputerHandoff botId="writer" />
        </>,
      );
      fireEvent.click(
        screen.getByRole("button", { name: "cloudComputer.handoffOpen" }),
      );
      expect(await screen.findByText("live screen")).toBeInTheDocument();
      expect(screen.getAllByRole("dialog")).toHaveLength(1);
      expect(api.openScreen).toHaveBeenCalledTimes(1);
      expect(api.takeover).toHaveBeenCalledTimes(readOnly ? 0 : 1);
      if (readOnly)
        expect(
          screen.getByText("cloudComputer.legacyViewOnly"),
        ).toBeInTheDocument();
    },
  );

  it("keeps the window open while the computer starts", () => {
    const rules = { pillOnly: false, idleSinceMs: null, nowMs: 0 };
    expect(nextMode("window", off, { ...rules, starting: true })).toBe(
      "window",
    );
    expect(nextMode("window", off, { ...rules, pinned: true })).toBe("pill");
  });

  it("starts a computer that is off and shows that it is starting", async () => {
    let ready: (ticket: { ws_path: string; session: string }) => void = () =>
      undefined;
    api.openScreen.mockReturnValue(
      new Promise((resolve) => {
        ready = resolve as typeof ready;
      }) as never,
    );
    render(<CloudComputerFloat botId="writer" botName="Writer" />);
    await act(async () => undefined);
    expect(api.openScreen).not.toHaveBeenCalled();
    act(() => toggleCloudFloat("writer"));
    expect(await screen.findByRole("status")).toHaveTextContent(
      "cloudComputer.float.starting",
    );
    expect(api.openScreen).toHaveBeenCalledWith("writer");
    api.status.mockResolvedValue({ ...off, state: "running" });
    await act(async () => ready({ ws_path: "/ws", session: "s" }));
    expect(await screen.findByText("live screen")).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("says why when the computer could not start", async () => {
    api.openScreen.mockRejectedValue(new Error("no free computer"));
    render(<CloudComputerFloat botId="writer" botName="Writer" />);
    await act(async () => undefined);
    act(() => toggleCloudFloat("writer"));
    expect(await screen.findByText("no free computer")).toBeInTheDocument();
    // The pill stays clickable to try again.
    fireEvent.click(
      screen.getByRole("button", { name: "cloudComputer.float.open" }),
    );
    expect(api.openScreen).toHaveBeenCalledTimes(2);
  });

  it("stops showing that it is starting when no computer is free", async () => {
    api.status.mockResolvedValue({ ...off, state: "none" });
    api.openScreen.mockRejectedValue(
      new ApiResponseError(
        503,
        { code: "BOT_COMPUTER_BUSY", message: "No cloud computer is free" },
        null,
      ),
    );
    render(<CloudComputerFloat botId="writer" botName="Writer" />);
    await act(async () => undefined);
    act(() => toggleCloudFloat("writer"));
    expect(
      await screen.findByText("No cloud computer is free"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("cloudComputer.float.starting"),
    ).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "cloudComputer.float.retry" }),
    );
    expect(api.openScreen).toHaveBeenCalledTimes(2);
  });
});
