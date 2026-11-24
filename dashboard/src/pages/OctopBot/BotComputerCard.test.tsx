import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { botComputerApi } from "../../api/modules/botComputer";
import BotComputerCard from "./BotComputerCard";

const connect = vi.fn();
vi.mock("../../hooks/useDesktopStream", () => ({
  useDesktopStream: () => ({
    status: "idle",
    connect,
    disconnect: vi.fn(),
  }),
}));

vi.mock("react-i18next", () => {
  const t = (key: string) => key;
  return { useTranslation: () => ({ t }) };
});

const state = {
  available: true,
  level: "foreground" as const,
  apps: [],
  paused: false,
  active_app: null,
};

afterEach(() => {
  vi.restoreAllMocks();
  connect.mockReset();
  delete (window as { octopDesktop?: unknown }).octopDesktop;
});

describe("Octop Bot local computer card", () => {
  it("asks for missing macOS grants instead of waiting for the screen", async () => {
    const request = vi.fn().mockResolvedValue(false);
    const relaunch = vi.fn();
    (window as { octopDesktop?: unknown }).octopDesktop = {
      requestComputerPermission: request,
      relaunch,
    };
    vi.spyOn(botComputerApi, "state").mockResolvedValue({
      ...state,
      permissions_needed: ["screen_recording", "accessibility"],
    });
    vi.spyOn(botComputerApi, "apps").mockResolvedValue([]);
    render(<BotComputerCard botId="bot-1" />);
    await userEvent.click(
      await screen.findByText("octopBot.computer.needsPermission"),
    );
    expect(
      await screen.findByText("octopBot.computer.permTitle"),
    ).toBeInTheDocument();
    const grants = screen.getAllByRole("button", {
      name: "octopBot.computer.permGrant",
    });
    expect(grants).toHaveLength(2);
    await userEvent.click(grants[0]);
    expect(request).toHaveBeenCalledWith("screen_recording");
    await userEvent.click(
      screen.getByRole("button", { name: "octopBot.computer.permRelaunch" }),
    );
    expect(relaunch).toHaveBeenCalled();
    expect(connect).not.toHaveBeenCalled();
  });

  it("streams the screen once macOS allows it", async () => {
    vi.spyOn(botComputerApi, "state").mockResolvedValue({
      ...state,
      permissions_needed: [],
    });
    render(<BotComputerCard botId="bot-1" />);
    expect(
      await screen.findByText("octopBot.computer.foreground"),
    ).toBeInTheDocument();
    expect(connect).toHaveBeenCalled();
    expect(
      screen.queryByText("octopBot.computer.permTitle"),
    ).not.toBeInTheDocument();
  });
});
