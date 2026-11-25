import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { botCloudComputerApi } from "../../api/modules/botCloudComputer";
import CloudComputerCard from "./CloudComputerCard";

vi.mock("./CloudComputerScreen", () => ({
  default: ({
    wsPath,
    interactive,
    session,
  }: {
    wsPath: string;
    interactive: boolean;
    session?: string;
  }) => <div data-testid="screen">{`${wsPath}|${interactive}|${session}`}</div>,
  screenSocketUrl: (path: string, origin: string) =>
    new URL(path, origin).toString().replace(/^http/, "ws"),
}));

vi.mock("react-i18next", () => {
  const t = (key: string, values?: Record<string, unknown>) =>
    values ? `${key}:${JSON.stringify(values)}` : key;
  return { useTranslation: () => ({ t }) };
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("Octop Bot cloud computer card", () => {
  it("shows the disk price and overdue days", async () => {
    vi.spyOn(botCloudComputerApi, "status").mockResolvedValue({
      state: "paused",
      spec: "standard",
      running_since: null,
      paid_until: null,
      takeover: false,
      disk_gb: 40,
      disk_daily_credits: 192,
      disk_billing: true,
      disk_overdue_days: 2,
    });
    render(<CloudComputerCard botId="bot-1" />);
    expect(
      await screen.findByText('cloudComputer.diskFee:{"gb":40,"credits":192}'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('cloudComputer.diskOverdue:{"days":2}'),
    ).toBeInTheDocument();
  });

  it("shows a running computer and pauses it", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(1_700_000_600_000);
    vi.spyOn(botCloudComputerApi, "status").mockResolvedValue({
      state: "running",
      spec: "standard",
      running_since: 1_700_000_000,
      paid_until: 1_700_000_900,
      takeover: false,
    });
    const pause = vi.spyOn(botCloudComputerApi, "pause").mockResolvedValue({
      state: "paused",
      spec: "standard",
      running_since: null,
      paid_until: null,
      takeover: false,
    });
    render(<CloudComputerCard botId="bot-1" />);
    expect(
      await screen.findByText("cloudComputer.state.running"),
    ).toBeInTheDocument();
    expect(
      screen.getByText('cloudComputer.runningFor:{"minutes":10}'),
    ).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "cloudComputer.pause" }),
    );
    expect(pause).toHaveBeenCalledWith("bot-1");
    expect(
      await screen.findByText("cloudComputer.state.paused"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "cloudComputer.pause" }),
    ).toBeNull();
  });

  it("opens the screen view-only and gives the user control on takeover", async () => {
    const running = {
      state: "running" as const,
      spec: "standard",
      running_since: null,
      paid_until: null,
      takeover: false,
    };
    vi.spyOn(botCloudComputerApi, "status").mockResolvedValue(running);
    vi.spyOn(botCloudComputerApi, "openScreen").mockResolvedValue({
      ws_path: "/api/octop-bot/computers/bot-1/screen/ws?ticket=t1",
      expires_in: 60,
      session: "s1",
    });
    const takeover = vi
      .spyOn(botCloudComputerApi, "takeover")
      .mockResolvedValue({ ...running, takeover: true });
    render(<CloudComputerCard botId="bot-1" />);
    await userEvent.click(
      await screen.findByRole("button", { name: "cloudComputer.view" }),
    );
    expect(await screen.findByTestId("screen")).toHaveTextContent(
      "/api/octop-bot/computers/bot-1/screen/ws?ticket=t1|false|s1",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "cloudComputer.takeOver" }),
    );
    expect(takeover).toHaveBeenCalledWith("bot-1", true);
    // Taken over: the screen gets control, and its session for IME text and the clipboard.
    expect(await screen.findByTestId("screen")).toHaveTextContent("|true|s1");
  });

  it("explains when the computer starts before it has run", async () => {
    vi.spyOn(botCloudComputerApi, "status").mockResolvedValue({
      state: "none",
      spec: "standard",
      running_since: null,
      paid_until: null,
      takeover: false,
    });
    render(<CloudComputerCard botId="bot-1" />);
    expect(
      await screen.findByText("cloudComputer.state.none"),
    ).toBeInTheDocument();
    expect(screen.getByText("cloudComputer.hint")).toBeInTheDocument();
  });
});
