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
  it("signs the bound owner in with their Lynxce account", async () => {
    vi.spyOn(authApi, "getLynxceIdentityStatus").mockResolvedValue({
      enabled: true,
      claimed: true,
    });
    const login = vi
      .spyOn(authApi, "lynxceLogin")
      .mockResolvedValue(session as never);
    open();
    await userEvent.type(
      await screen.findByLabelText("botOnboarding.account"),
      "alice",
    );
    await userEvent.type(
      screen.getByLabelText("botOnboarding.password"),
      "secret-pass{Enter}",
    );
    expect(
      await screen.findByRole("heading", { name: "Workspace" }),
    ).toBeInTheDocument();
    expect(login).toHaveBeenCalledWith("alice", "secret-pass", "en");
    expect(getAuthToken()).toBe("issued");
  });

  it("asks only for the password when the owner chose their own model", async () => {
    vi.spyOn(authApi, "getLynxceIdentityStatus").mockResolvedValue({
      enabled: true,
      claimed: false,
    });
    const login = vi
      .spyOn(authApi, "login")
      .mockResolvedValue(session as never);
    open();
    await userEvent.type(
      await screen.findByLabelText("botOnboarding.password"),
      "own-pass{Enter}",
    );
    expect(
      await screen.findByRole("heading", { name: "Workspace" }),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("botOnboarding.account")).toBeNull();
    expect(login).toHaveBeenCalledWith("local", "own-pass");
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
