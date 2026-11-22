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
  lynxce_login: false,
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
        <Route path="/octop-bot/guide" element={<h1>Team guide</h1>} />
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
  it("creates the account in place of a separate start step and resumes after account and finish failures", async () => {
    vi.mocked(wizardApi.createAdmin).mockRejectedValueOnce(
      new Error("Account unavailable"),
    );
    vi.mocked(wizardApi.finish).mockRejectedValueOnce(
      new Error("Finish unavailable"),
    );
    openSetup();
    const later = await screen.findByRole("button", {
      name: "botClient.later",
    });
    expect(
      screen.queryByRole("button", { name: /botClient.begin/ }),
    ).not.toBeInTheDocument();
    fireEvent.click(later);
    await screen.findByText("Account unavailable");
    fireEvent.click(later);
    await screen.findByText("Finish unavailable");
    fireEvent.click(later);
    expect(
      await screen.findByRole("heading", { name: "Team guide" }),
    ).toBeInTheDocument();
    expect(wizardApi.applyDatabase).toHaveBeenCalledTimes(1);
    expect(wizardApi.createAdmin).toHaveBeenCalledTimes(2);
    expect(wizardApi.createAdmin).toHaveBeenLastCalledWith(
      { username: "local", display_name: null, locale: "zh" },
      "wizard-session",
    );
    expect(wizardApi.finish).toHaveBeenCalledTimes(2);
    expect(wizardApi.begin).toHaveBeenCalledTimes(1);
    expect(getAuthToken()).toBe("issued-session");
  });

  it("can finish adding the requested local desktop account alongside an existing account", async () => {
    vi.mocked(authApi.getAuthStatus).mockResolvedValue({
      ...fresh,
      setup_required: false,
      setup_done: true,
      database_bound: true,
    });
    openSetup("/setup?localAccount=1");
    const registration = await screen.findByRole("link", {
      name: "botClient.lynxce.register",
    });
    expect(registration).toHaveAttribute("target", "_blank");
    expect(registration).toHaveAccessibleDescription(
      "botClient.lynxce.registerHint",
    );
    fireEvent.click(
      await screen.findByRole("button", { name: /botClient.lynxce.source/ }),
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
      await screen.findByRole("button", { name: "botClient.lynxce.other" }),
    );
    expect(
      await screen.findByRole("heading", { name: "Settings other" }),
    ).toBeInTheDocument();
  });

  it("signs the web owner in with a Lynxce account without any local account or setup password", async () => {
    vi.mocked(authApi.getAuthStatus).mockResolvedValue({
      ...fresh,
      lynxce_login: true,
    });
    const login = vi.spyOn(authApi, "lynxceLogin").mockResolvedValue({
      access_token: "lynxce-session",
      token_type: "Bearer",
      expires_in: 3600,
      user: { id: 1, username: "owner", role: "admin" },
      token: "lynxce-session",
    } as never);
    openSetup();
    await userEvent.type(
      await screen.findByLabelText("botOnboarding.account"),
      " alice@example.invalid ",
    );
    await userEvent.type(
      screen.getByLabelText("botOnboarding.password"),
      "lynxce-pass{Enter}",
    );
    expect(
      await screen.findByRole("heading", { name: "Settings other" }),
    ).toBeInTheDocument();
    expect(login).toHaveBeenCalledWith(
      "alice@example.invalid",
      "lynxce-pass",
      "zh",
    );
    expect(wizardApi.applyDatabase).toHaveBeenCalledTimes(1);
    expect(wizardApi.createAdmin).not.toHaveBeenCalled();
    expect(getAuthToken()).toBe("lynxce-session");
  });

  it("lets a web owner who brings their own model choose a sign-in password", async () => {
    vi.mocked(authApi.getAuthStatus).mockResolvedValue({
      ...fresh,
      lynxce_login: true,
    });
    openSetup();
    fireEvent.click(await screen.findByText("botOnboarding.localTab"));
    await userEvent.type(
      await screen.findByLabelText("botOnboarding.localPassword"),
      "Own-model-pass1{Enter}",
    );
    expect(
      await screen.findByRole("heading", { name: "Settings other" }),
    ).toBeInTheDocument();
    expect(wizardApi.createAdmin).toHaveBeenCalledWith(
      {
        username: "local",
        display_name: null,
        locale: "zh",
        password: "Own-model-pass1",
      },
      "wizard-session",
    );
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
