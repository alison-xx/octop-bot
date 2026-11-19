import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { OctopAgent } from "../../context/AgentContext";
import BotClientWelcome from "./BotClientWelcome";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("../../hooks/useServerTimezone", () => ({
  useServerTimezone: () => "UTC",
}));
afterEach(cleanup);

function SettingsProbe() {
  return <output>{JSON.stringify(useLocation().state)}</output>;
}

function renderWelcome(needsModel: boolean, isChief = true) {
  const pick = vi.fn();
  render(
    <MemoryRouter initialEntries={["/octop-bot/bots/test"]}>
      <Routes>
        <Route
          path="/octop-bot/bots/test"
          element={
            <BotClientWelcome
              avatar={<span>avatar</span>}
              agent={{ name: "Chief" } as OctopAgent}
              isChief={isChief}
              welcome="My configured welcome"
              prompts={[]}
              loading={false}
              needsModel={needsModel}
              ready={!needsModel}
              canConfigure
              onRefresh={async () => {}}
              onPick={pick}
            />
          }
        />
        <Route path="/octop-bot/settings" element={<SettingsProbe />} />
      </Routes>
    </MemoryRouter>,
  );
  return pick;
}

describe("first conversation", () => {
  it("uses the actual welcome as a message and prefills Chief's team request", () => {
    const pick = renderWelcome(false);
    expect(
      screen.queryByRole("link", { name: "botClient.lynxce.register" }),
    ).toBeNull();
    expect(screen.getByText("My configured welcome")).toBeInTheDocument();
    expect(screen.queryByRole("heading")).toBeNull();
    fireEvent.click(
      screen.getByRole("button", { name: "botClient.teamLabel" }),
    );
    expect(pick).toHaveBeenCalledWith("botClient.teamPrompt");
  });
  it("carries the intended task and private conversation through model setup", () => {
    const pick = renderWelcome(true);
    expect(
      screen.getByRole("link", { name: "botClient.lynxce.register" }),
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "botClient.assignLabel" }),
    );
    expect(JSON.parse(screen.getByRole("status").textContent || "{}")).toEqual({
      from: "/octop-bot/bots/test",
      prefillInput: "botClient.assignPrompt",
    });
    expect(pick).not.toHaveBeenCalled();
  });
  it("only offers team management suggestions to Chief", () => {
    renderWelcome(false, false);
    expect(
      screen.queryByRole("button", { name: "botClient.teamLabel" }),
    ).toBeNull();
  });
});
