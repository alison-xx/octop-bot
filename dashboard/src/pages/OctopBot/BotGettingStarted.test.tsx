import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Routes, Route, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  BOT_GUIDE,
  BOT_HOME,
  BOT_SETTINGS,
  botGuideSeenKey,
} from "../../utils/botClientRoute";
import BotGettingStarted from "./BotGettingStarted";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("../../hooks/useCurrentUser", () => ({
  useCurrentUser: () => ({ id: 42 }),
}));
vi.mock("./BotCharacter", () => ({
  BotCharacter: () => null,
  octopCharacter: {},
}));
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
afterEach(() => {
  cleanup();
  localStorage.clear();
});
describe("Bot getting started", () => {
  it("opens the real model settings and keeps the conversation to return to", () => {
    openGuide({ returnTo: "/octop-bot/bots/chief/t1" });
    fireEvent.click(
      screen.getByRole("button", { name: "botClient.connectModel" }),
    );
    expect(JSON.parse(screen.getByRole("status").textContent!)).toEqual({
      pathname: BOT_SETTINGS,
      state: {
        source: "lynxce",
        from: BOT_GUIDE,
        guideReturnTo: "/octop-bot/bots/chief/t1",
      },
    });
    expect(localStorage.getItem(botGuideSeenKey(42))).toBeNull();
  });
  it("resumes at the team step then takes only the chosen draft to Chief", () => {
    openGuide({ step: "team" });
    expect(
      screen.getByRole("heading", { name: "botGuide.team.title" }),
    ).toHaveFocus();
    fireEvent.click(screen.getByRole("button", { name: "botGuide.next" }));
    fireEvent.click(screen.getByRole("radio", { name: "botClient.planLabel" }));
    fireEvent.click(screen.getByRole("button", { name: "botGuide.openDraft" }));
    expect(JSON.parse(screen.getByRole("status").textContent!)).toEqual({
      pathname: BOT_HOME,
      state: { prefillInput: "botClient.planPrompt" },
    });
    expect(localStorage.getItem(botGuideSeenKey(42))).toBe("1");
  });
  it("remembers dismissal and returns to the original conversation", () => {
    openGuide({ returnTo: "/octop-bot/groups/editors" });
    fireEvent.click(screen.getByRole("button", { name: "botGuide.skip" }));
    expect(JSON.parse(screen.getByRole("status").textContent!)).toEqual({
      pathname: "/octop-bot/groups/editors",
      state: null,
    });
    expect(localStorage.getItem(botGuideSeenKey(42))).toBe("1");
  });
});
