import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { botCloudComputerApi } from "../../api/modules/botCloudComputer";
import CloudComputerCard from "./CloudComputerCard";

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
  it("shows a running computer and pauses it", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(1_700_000_600_000);
    vi.spyOn(botCloudComputerApi, "status").mockResolvedValue({
      state: "running",
      spec: "standard",
      running_since: 1_700_000_000,
      paid_until: 1_700_000_900,
    });
    const pause = vi.spyOn(botCloudComputerApi, "pause").mockResolvedValue({
      state: "paused",
      spec: "standard",
      running_since: null,
      paid_until: null,
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
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("explains when the computer starts before it has run", async () => {
    vi.spyOn(botCloudComputerApi, "status").mockResolvedValue({
      state: "none",
      spec: "standard",
      running_since: null,
      paid_until: null,
    });
    render(<CloudComputerCard botId="bot-1" />);
    expect(
      await screen.findByText("cloudComputer.state.none"),
    ).toBeInTheDocument();
    expect(screen.getByText("cloudComputer.hint")).toBeInTheDocument();
  });
});
