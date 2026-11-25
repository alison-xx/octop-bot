import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Routes, Route, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { BOT_GUIDE, BOT_HOME, BOT_SETTINGS } from "../../utils/botClientRoute";
import BotGettingStarted from "./BotGettingStarted";

const change = vi.hoisted(() => vi.fn(() => Promise.resolve({})));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("../../api/modules/botOnboarding", () => ({
  botOnboardingApi: { change },
}));
vi.mock("./BotCharacter", () => ({
  BotCharacter: () => null,
  octopCharacter: {},
}));
vi.mock("./LynxceRegistration", () => ({ default: () => null }));
function Destination() {
  const { pathname, state } = useLocation();
  return <output>{JSON.stringify({ pathname, state })}</output>;
}
function openGuide(state?: Record<string, string>) {
  render(
    <MemoryRouter initialEntries={[{ pathname: BOT_GUIDE, state }]}>
      <Routes>
        <Route path={BOT_GUIDE} element={<BotGettingStarted />} />
        <Route path="*" element={<Destination />} />
      </Routes>
    </MemoryRouter>,
  );
}
const destination = () => JSON.parse(screen.getByRole("status").textContent!);
afterEach(() => {
  cleanup();
  change.mockClear();
});
describe("Bot getting started (model step)", () => {
  it("opens the real model settings and keeps the conversation to return to", () => {
    openGuide({ returnTo: "/octop-bot/bots/chief/t1" });
    expect(
      screen.getByRole("heading", { name: "botGuide.model.title" }),
    ).toHaveFocus();
    fireEvent.click(
      screen.getByRole("button", { name: "botClient.connectModel" }),
    );
    expect(destination()).toEqual({
      pathname: BOT_SETTINGS,
      state: {
        source: "lynxce",
        from: BOT_GUIDE,
        guideReturnTo: "/octop-bot/bots/chief/t1",
      },
    });
  });
  it("goes on to Chief, where the rest of the onboarding happens", () => {
    openGuide();
    fireEvent.click(screen.getByRole("button", { name: /botGuide.next/ }));
    expect(destination()).toEqual({ pathname: BOT_HOME, state: null });
    expect(change).not.toHaveBeenCalled();
  });
  it("skipping ends the onboarding and returns to the original conversation", () => {
    openGuide({ returnTo: "/octop-bot/groups/editors" });
    fireEvent.click(screen.getByRole("button", { name: "botGuide.skip" }));
    expect(change).toHaveBeenCalledWith({ action: "skip" });
    expect(destination()).toEqual({
      pathname: "/octop-bot/groups/editors",
      state: null,
    });
  });
});
