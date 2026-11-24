import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import BotAboutPanel from "./BotAboutPanel";

const bridge = vi.hoisted(() => ({ current: null as null | object }));
vi.mock("react-i18next", () => {
  const t = (key: string) => key;
  return { useTranslation: () => ({ t }) };
});
vi.mock("../../utils/desktopBridge", async (original) => ({
  ...(await original<typeof import("../../utils/desktopBridge")>()),
  getDesktopBridge: () => bridge.current,
  isBotWebClient: () => false,
}));
vi.mock("./BotCharacter", () => ({
  BotCharacter: () => null,
  octopCharacter: {},
}));
vi.mock("./BotUpdatePanel", () => ({ default: () => null }));
vi.mock("./useBotServerInfo", () => ({
  useBotServerInfo: () => ({ edition: "desktop", version: "1.0.5" }),
}));

function renderAbout() {
  render(
    <MemoryRouter>
      <BotAboutPanel returnTo="/octop-bot" />
    </MemoryRouter>,
  );
}

afterEach(() => {
  bridge.current = null;
});

describe("Settings → About", () => {
  it("opens the shell's server picker from the desktop's own service", () => {
    const openServerPicker = vi.fn();
    bridge.current = { openServerPicker };
    renderAbout();
    expect(screen.getByText("botAbout.serverLocal")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "botAbout.switchServer" }),
    );
    expect(openServerPicker).toHaveBeenCalledTimes(1);
  });

  it("points to the menu bar when a remote server's page has no bridge", () => {
    const ua = vi
      .spyOn(navigator, "userAgent", "get")
      .mockReturnValue("Mozilla/5.0 Electron/39.0.0");
    renderAbout();
    expect(screen.getByText("botAbout.switchFromMenu")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "botAbout.switchServer" }),
    ).toBeNull();
    ua.mockRestore();
  });

  it("leaves the server out in a plain browser", () => {
    renderAbout();
    expect(screen.queryByText("botAbout.server")).toBeNull();
    expect(
      screen.getByRole("button", { name: "botGuide.title" }),
    ).toBeInTheDocument();
  });
});
