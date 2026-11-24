import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { authApi, type AuthStatus } from "../../api/modules/auth";
import { getAuthToken, setAuthToken } from "../../api/request";
import BotLogin from "./BotLogin";

vi.mock("react-i18next", () => {
  const t = (key: string) => key;
  return { useTranslation: () => ({ t, i18n: { language: "en" } }) };
});
vi.mock("./BotCharacter", () => ({
  BotCharacter: () => null,
  octopCharacter: {},
}));

const ready: AuthStatus = {
  setup_required: false,
  local_account: false,
  setup_done: true,
  enabled: true,
  has_password: true,
  wizard_password_exists: false,
  wizard_password_required: false,
  database_bound: true,
  lynxce_login: true,
};
const session = {
  access_token: "issued",
  token_type: "Bearer",
  expires_in: 60,
  user: { id: 1, username: "owner", role: "admin" },
  token: "issued",
};

function open() {
  render(
    <MemoryRouter initialEntries={["/login"]}>
      <Routes>
        <Route path="/login" element={<BotLogin />} />
        <Route path="/octop-bot" element={<h1>Workspace</h1>} />
        <Route path="/setup" element={<h1>Setup</h1>} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(authApi, "getAuthStatus").mockResolvedValue(ready);
});
afterEach(() => setAuthToken(null));

describe("Bot web sign-in", () => {
  it("offers Lynxce sign-in to everyone on Octop Bot cloud", async () => {
    vi.spyOn(authApi, "getLynxceIdentityStatus").mockResolvedValue({
      enabled: true,
      claimed: false,
      cloud: true,
    });
    open();
    expect(
      await screen.findByText("botOnboarding.loginCloudBody"),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("botOnboarding.legacyPassword")).toBeNull();
  });

  it("signs the bound owner in with their Lynxce account", async () => {
    vi.spyOn(authApi, "getLynxceIdentityStatus").mockResolvedValue({
      enabled: true,
      claimed: true,
    });
    const login = vi
      .spyOn(authApi, "lynxceLogin")
      .mockResolvedValue(session as never);
    open();
    await userEvent.click(
      await screen.findByRole("button", { name: "lynxceSignIn.tabPassword" }),
    );
    await userEvent.type(
      screen.getByLabelText("lynxceSignIn.account"),
      "alice",
    );
    await userEvent.type(
      screen.getByLabelText("lynxceSignIn.password"),
      "secret-pass{Enter}",
    );
    expect(
      await screen.findByRole("heading", { name: "Workspace" }),
    ).toBeInTheDocument();
    expect(login).toHaveBeenCalledWith("alice", "secret-pass", "en", "");
    expect(getAuthToken()).toBe("issued");
  });

  it("signs in with a one-time code by default", async () => {
    vi.spyOn(authApi, "getLynxceIdentityStatus").mockResolvedValue({
      enabled: true,
      claimed: true,
    });
    const send = vi
      .spyOn(authApi, "lynxceSendCode")
      .mockResolvedValue({ channel: "phone" });
    const login = vi
      .spyOn(authApi, "lynxceCodeLogin")
      .mockResolvedValue(session as never);
    open();
    await userEvent.type(
      await screen.findByLabelText("lynxceSignIn.target"),
      " 13800000000 ",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "lynxceSignIn.send" }),
    );
    expect(send).toHaveBeenCalledWith("13800000000", "en");
    expect(
      await screen.findByText("lynxceSignIn.sentPhone"),
    ).toBeInTheDocument();
    // The sixth digit submits on its own.
    await userEvent.type(screen.getByLabelText("lynxceSignIn.code"), "12a3456");
    expect(
      await screen.findByRole("heading", { name: "Workspace" }),
    ).toBeInTheDocument();
    expect(login).toHaveBeenCalledWith("13800000000", "123456", "en", "");
    expect(getAuthToken()).toBe("issued");
  });

  it("binds a server set up with a local password once, through Lynxce", async () => {
    vi.spyOn(authApi, "getLynxceIdentityStatus").mockResolvedValue({
      enabled: true,
      claimed: false,
      legacy_owner: true,
    });
    const login = vi
      .spyOn(authApi, "lynxceLogin")
      .mockResolvedValue(session as never);
    const passwordLogin = vi.spyOn(authApi, "login");
    open();
    await userEvent.type(
      await screen.findByLabelText("botOnboarding.legacyPassword"),
      "old-pass",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "lynxceSignIn.tabPassword" }),
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
      await screen.findByRole("heading", { name: "Workspace" }),
    ).toBeInTheDocument();
    expect(login).toHaveBeenCalledWith(
      "13800000000",
      "lynxce-pass",
      "en",
      "old-pass",
    );
    expect(passwordLogin).not.toHaveBeenCalled();
  });

  it("sends a fresh instance to setup", async () => {
    vi.mocked(authApi.getAuthStatus).mockResolvedValue({
      ...ready,
      setup_required: true,
    });
    vi.spyOn(authApi, "getLynxceIdentityStatus").mockResolvedValue({
      enabled: true,
      claimed: false,
    });
    open();
    expect(
      await screen.findByRole("heading", { name: "Setup" }),
    ).toBeInTheDocument();
  });
});
