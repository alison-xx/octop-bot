import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { authApi, type AuthStatus } from "../../api/modules/auth";
import { botCloudApi } from "../../api/modules/botCloud";
import { renewDesktopSession } from "../../api/desktopSession";
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
const desktopShell = vi.hoisted(() => ({ on: true }));
vi.mock("../../utils/desktopBridge", () => ({
  isDesktopShell: () => desktopShell.on,
  getDesktopBridge: () => undefined,
}));
vi.mock("../../api/desktopSession", () => ({
  desktopLocalAutoLoginHeld: () => false,
  // A token for the desktop "local" account: {"uname":"local"}.
  isLocalDesktopUser: (token: string) => token.startsWith("local"),
  releaseDesktopLocalAutoLogin: vi.fn(),
  renewDesktopSession: vi.fn(),
}));

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
  desktopShell.on = true;
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
  it("signs a returning desktop user straight back in to this computer", async () => {
    vi.mocked(authApi.getAuthStatus).mockResolvedValue({
      ...fresh,
      setup_required: false,
      setup_done: true,
      database_bound: true,
      local_account: true,
    });
    vi.mocked(renewDesktopSession).mockResolvedValue({
      access_token: "local-renewed",
    } as never);
    openSetup();
    expect(
      await screen.findByRole("heading", { name: "Chat" }),
    ).toBeInTheDocument();
    expect(getAuthToken()).toBe("local-renewed");
    expect(wizardApi.createAdmin).not.toHaveBeenCalled();
  });

  it("offers this computer again when the silent sign-in fails, with no Octop password", async () => {
    vi.mocked(authApi.getAuthStatus).mockResolvedValue({
      ...fresh,
      setup_required: false,
      setup_done: true,
      database_bound: true,
      local_account: true,
    });
    vi.mocked(renewDesktopSession).mockResolvedValue({
      access_token: "local-again",
    } as never);
    openSetup();
    fireEvent.click(
      await screen.findByRole("button", { name: "botOnboarding.useLocal" }),
    );
    expect(
      await screen.findByRole("heading", { name: "Chat" }),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText(/password/i)).toBeNull();
    expect(wizardApi.createAdmin).not.toHaveBeenCalled();
  });

  it("creates the account in place of a separate start step and resumes after account and finish failures", async () => {
    vi.mocked(wizardApi.createAdmin).mockRejectedValueOnce(
      new Error("Account unavailable"),
    );
    vi.mocked(wizardApi.finish).mockRejectedValueOnce(
      new Error("Finish unavailable"),
    );
    openSetup();
    const later = await screen.findByRole("button", {
      name: "botOnboarding.useLocal",
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
      // A fresh local owner chooses its models before meeting the team.
      await screen.findByRole("heading", { name: "Settings" }),
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
    fireEvent.click(
      await screen.findByRole("button", { name: "botOnboarding.useLocal" }),
    );
    expect(
      // A fresh local owner chooses its models before meeting the team.
      await screen.findByRole("heading", { name: "Settings" }),
    ).toBeInTheDocument();
    expect(wizardApi.applyDatabase).not.toHaveBeenCalled();
    expect(wizardApi.finish).toHaveBeenCalledWith(
      { provider_draft: null },
      "wizard-session",
    );
  });

  it("signs in to Lynxce on first launch, after creating the local owner silently", async () => {
    const login = vi.spyOn(botCloudApi, "login").mockResolvedValue({
      connected: true,
      account_id: "13800000000",
      display_name: "Alice",
    });
    openSetup();
    await userEvent.click(
      await screen.findByRole("button", { name: "lynxceSignIn.tabPassword" }),
    );
    await userEvent.type(
      screen.getByLabelText("lynxceSignIn.account"),
      "13800000000",
    );
    await userEvent.type(
      screen.getByLabelText("lynxceSignIn.password"),
      "lynxce-pass{Enter}",
    );
    expect(
      await screen.findByRole("heading", { name: "Settings lynxce" }),
    ).toBeInTheDocument();
    expect(login).toHaveBeenCalledWith("13800000000", "lynxce-pass");
    // The local owner comes first, without a password, and only once.
    expect(wizardApi.createAdmin).toHaveBeenCalledTimes(1);
    expect(wizardApi.createAdmin).toHaveBeenCalledWith(
      { username: "local", display_name: null, locale: "zh" },
      "wizard-session",
    );
    expect(login.mock.invocationCallOrder[0]).toBeGreaterThan(
      vi.mocked(wizardApi.finish).mock.invocationCallOrder[0],
    );
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
    await userEvent.click(
      await screen.findByRole("button", { name: "lynxceSignIn.tabPassword" }),
    );
    await userEvent.type(
      screen.getByLabelText("lynxceSignIn.account"),
      " alice@example.invalid ",
    );
    await userEvent.type(
      screen.getByLabelText("lynxceSignIn.password"),
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

  it("offers web owners only the Lynxce account, never a local password", async () => {
    desktopShell.on = false;
    vi.mocked(authApi.getAuthStatus).mockResolvedValue({
      ...fresh,
      lynxce_login: true,
    });
    openSetup();
    expect(
      await screen.findByRole("button", { name: "lynxceSignIn.tabPassword" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("botOnboarding.useLocal")).toBeNull();
    expect(screen.queryByLabelText("wizard.admin.password")).toBeNull();
  });

  it("returns to password verification when the saved wizard token expires before form submission", async () => {
    desktopShell.on = false;
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
