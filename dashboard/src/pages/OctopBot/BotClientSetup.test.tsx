import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { authApi, type AuthStatus } from "../../api/modules/auth";
import { getAuthToken } from "../../api/request";
import { wizardApi, wizardSession } from "../Setup/wizardClient";
import BotClientSetup from "./BotClientSetup";

vi.mock("react-i18next", () => {
  const t = (key: string) => key;
  return { useTranslation: () => ({ t, i18n: { language: "zh" } }) };
});
vi.mock("./BotCharacter", () => ({
  BotCharacter: () => null,
  octopCharacter: {},
}));
vi.mock("../../utils/desktopBridge", () => ({ isDesktopShell: () => true }));

const fresh: AuthStatus = {
  setup_required: true,
  local_account: false,
  setup_done: false,
  enabled: true,
  has_password: true,
  wizard_password_exists: false,
  wizard_password_required: false,
  database_bound: false,
};
function Source() {
  return <h1>Settings {useLocation().state?.source}</h1>;
}
function openSetup(path = "/setup") {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/setup" element={<BotClientSetup />} />
        <Route path="/octop-bot/settings" element={<Source />} />
        <Route path="/octop-bot" element={<h1>Chat</h1>} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.spyOn(authApi, "getAuthStatus").mockResolvedValue(fresh);
  vi.spyOn(wizardApi, "applyDatabase").mockResolvedValue({
    ok: true,
    adopted: false,
    driver: "sqlite",
  });
  vi.spyOn(wizardApi, "begin").mockResolvedValue({
    wizard_token: "wizard-session",
    expires_in: 300,
  });
  vi.spyOn(wizardApi, "validateToken").mockResolvedValue({ valid: true });
  vi.spyOn(wizardApi, "createAdmin").mockResolvedValue({
    id: 1,
    username: "local",
    role: "admin",
    access_token: "issued-session",
    expires_in: 3600,
  });
  vi.spyOn(wizardApi, "finish").mockResolvedValue({ ok: true });
});
afterEach(() => {
  sessionStorage.clear();
  localStorage.clear();
});

describe("standalone onboarding", () => {
  it("resumes after separate account and finish failures, without rebinding the database or duplicating the account", async () => {
    vi.mocked(wizardApi.createAdmin).mockRejectedValueOnce(
      new Error("Account unavailable"),
    );
    vi.mocked(wizardApi.finish).mockRejectedValueOnce(
      new Error("Finish unavailable"),
    );
    openSetup();
    const begin = await screen.findByRole("button", {
      name: "botClient.begin",
    });
    fireEvent.click(begin);
    await screen.findByText("Account unavailable");
    fireEvent.click(begin);
    await screen.findByText("Finish unavailable");
    fireEvent.click(begin);
    expect(
      await screen.findByRole("heading", { name: "botClient.nextTitle" }),
    ).toHaveFocus();
    expect(wizardApi.applyDatabase).toHaveBeenCalledTimes(1);
    expect(wizardApi.createAdmin).toHaveBeenCalledTimes(2);
    expect(wizardApi.finish).toHaveBeenCalledTimes(2);
    expect(wizardApi.begin).toHaveBeenCalledTimes(1);
    expect(getAuthToken()).toBe("issued-session");
    fireEvent.click(screen.getByRole("button", { name: "botClient.later" }));
    expect(
      await screen.findByRole("heading", { name: "Chat" }),
    ).toBeInTheDocument();
  });

  it("can finish adding the requested local desktop account alongside an existing account", async () => {
    vi.mocked(authApi.getAuthStatus).mockResolvedValue({
      ...fresh,
      setup_required: false,
      setup_done: true,
      database_bound: true,
    });
    openSetup("/setup?localAccount=1");
    fireEvent.click(
      await screen.findByRole("button", { name: "botClient.begin" }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "botClient.lynxce.source" }),
    );
    expect(
      await screen.findByRole("heading", { name: "Settings lynxce" }),
    ).toBeInTheDocument();
    expect(wizardApi.applyDatabase).not.toHaveBeenCalled();
    expect(wizardApi.finish).toHaveBeenCalledWith(
      { provider_draft: null },
      "wizard-session",
    );
  });

  it("keeps other providers accessible at first launch", async () => {
    openSetup();
    fireEvent.click(
      await screen.findByRole("button", { name: "botClient.begin" }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "botClient.lynxce.other" }),
    );
    expect(
      await screen.findByRole("heading", { name: "Settings other" }),
    ).toBeInTheDocument();
  });

  it("returns to password verification when the saved wizard token expires before form submission", async () => {
    vi.mocked(authApi.getAuthStatus).mockResolvedValue({
      ...fresh,
      wizard_password_required: true,
      wizard_password_exists: true,
    });
    wizardSession.saveToken("expired");
    vi.mocked(wizardApi.validateToken)
      .mockResolvedValueOnce({ valid: true })
      .mockResolvedValueOnce({ valid: false });
    openSetup();
    const field = await screen.findByLabelText("wizard.admin.password");
    await userEvent.type(field, "demoAccess123{Enter}");
    expect(
      await screen.findByText("wizard.sessionExpired"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "wizard.password.verifyButton" }),
    ).toBeInTheDocument();
    expect(wizardSession.loadToken()).toBeNull();
    expect(wizardApi.createAdmin).not.toHaveBeenCalled();
  });
});
