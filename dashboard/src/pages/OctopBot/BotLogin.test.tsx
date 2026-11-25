import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { authApi, type AuthStatus } from "../../api/modules/auth";
import { clearAuthToken, getAuthToken } from "../../api/request";
import { botWebLogin } from "../../api/modules/botWebLogin";
import BotLogin from "./BotLogin";
import BotLoginPreview from "./BotLoginPreview";

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
        <Route
          path="/octop-bot/groups/project"
          element={<h1>Project group</h1>}
        />
        <Route path="/setup" element={<h1>Setup</h1>} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(botWebLogin, "config").mockResolvedValue({
    enabled: false,
    url: "",
    state: "",
  });
  vi.spyOn(authApi, "getAuthStatus").mockResolvedValue(ready);
});
afterEach(() => {
  clearAuthToken();
  sessionStorage.clear();
  window.history.replaceState(null, "", "/");
});

describe("Bot web sign-in", () => {
  it("cycles the demos, keeping the current conversation while reading or signing in", () => {
    vi.useFakeTimers();
    try {
      const onUse = vi.fn();
      const view = render(<BotLoginPreview modalOpen={false} onUse={onUse} />);
      const question = (scene: string) =>
        screen.getByText(`botPreview.scenes.${scene}.question`);
      expect(question("retail")).toBeVisible();
      act(() => vi.advanceTimersByTime(14000));
      expect(question("sales")).toBeVisible();
      view.rerender(<BotLoginPreview modalOpen onUse={onUse} />);
      act(() => vi.advanceTimersByTime(28000));
      expect(question("sales")).toBeVisible();
      view.rerender(<BotLoginPreview modalOpen={false} onUse={onUse} />);
      fireEvent.click(screen.getByRole("button", { name: "botPreview.next" }));
      act(() => vi.advanceTimersByTime(28000));
      expect(question("launch")).toBeVisible();
      fireEvent.click(screen.getByRole("button", { name: "botPreview.play" }));
      act(() => vi.advanceTimersByTime(14000));
      expect(question("retail")).toBeVisible();
      expect(onUse).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });
  it("offers Lynxce sign-in to everyone on Octop Bot cloud", async () => {
    vi.spyOn(authApi, "getLynxceIdentityStatus").mockResolvedValue({
      enabled: true,
      claimed: false,
      cloud: true,
    });
    open();
    expect(
      await screen.findByRole("main", { name: "botPreview.workspace" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(botWebLogin.config).not.toHaveBeenCalled();
    await userEvent.click(
      screen.getByRole("button", { name: "botPreview.openComputer" }),
    );
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(await screen.findByText("botWebLogin.intro")).toBeInTheDocument();
    expect(screen.queryByLabelText("botOnboarding.legacyPassword")).toBeNull();
  });

  it("returns to the preview during a slow login and ignores the late session", async () => {
    vi.spyOn(authApi, "getLynxceIdentityStatus").mockResolvedValue({
      enabled: true,
      claimed: false,
      cloud: true,
    });
    let complete!: () => void;
    const login = vi.spyOn(authApi, "lynxceLogin").mockImplementation(
      () =>
        new Promise((resolve) => {
          complete = () => resolve(session as never);
        }),
    );
    open();
    await userEvent.click(
      await screen.findByRole("button", { name: "botPreview.composer" }),
    );
    await userEvent.click(
      await screen.findByRole("button", { name: "botWebLogin.passwordMode" }),
    );
    fireEvent.change(screen.getByLabelText("lynxceSignIn.account"), {
      target: { value: "alice" },
    });
    const password = screen.getByLabelText("lynxceSignIn.password");
    fireEvent.change(password, { target: { value: "secret-pass" } });
    fireEvent.submit(password.closest("form")!);
    expect(login).toHaveBeenCalledOnce();
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    await act(async () => {
      complete();
    });
    expect(
      screen.getByRole("main", { name: "botPreview.workspace" }),
    ).toBeVisible();
    expect(getAuthToken()).toBe("");
  });
  it.each(["wechat", "workbuddy"] as const)(
    "redeems the %s callback once and resumes the saved Bot",
    async (provider) => {
      vi.stubEnv("VITE_OCTOP_BOT_WEB", "1");
      vi.spyOn(authApi, "getLynxceIdentityStatus").mockResolvedValue({
        enabled: true,
        claimed: false,
        cloud: true,
      });
      sessionStorage.setItem(
        "octop.bot.login-return",
        "/octop-bot/groups/project",
      );
      sessionStorage.setItem(
        "octop.cloud.web.login.v1",
        JSON.stringify({
          provider,
          callbackState: "tab-state",
          state: provider === "wechat" ? "local-proof" : "tab-state",
          time: Date.now(),
        }),
      );
      const exchange = vi
        .spyOn(botWebLogin, "exchange")
        .mockResolvedValue({ access_token: "issued" });
      window.history.replaceState(
        null,
        "",
        "/login#provider=" + provider + "&code=sample&state=tab-state",
      );
      open();
      expect(
        await screen.findByRole("heading", { name: "Project group" }),
      ).toBeInTheDocument();
      expect(exchange).toHaveBeenCalledTimes(1);
      expect(exchange).toHaveBeenCalledWith(
        provider,
        "sample",
        provider === "wechat" ? "local-proof" : "tab-state",
        "en",
      );
      expect(window.location.hash).toBe("");
      expect(sessionStorage.getItem("octop.cloud.web.login.v1")).toBeNull();
      expect(getAuthToken()).toBe("issued");
      vi.unstubAllEnvs();
    },
  );

  it.each(["cancelled", "expired"] as const)(
    "keeps conventional sign-in available after a %s callback",
    async (reason) => {
      vi.spyOn(authApi, "getLynxceIdentityStatus").mockResolvedValue({
        enabled: true,
        claimed: false,
        cloud: true,
      });
      const exchange = vi.spyOn(botWebLogin, "exchange");
      if (reason === "cancelled")
        sessionStorage.setItem(
          "octop.cloud.web.login.v1",
          JSON.stringify({
            provider: "wechat",
            state: "tab-state",
            time: Date.now(),
          }),
        );
      window.history.replaceState(
        null,
        "",
        "/login#provider=wechat&state=tab-state&" +
          (reason === "cancelled" ? "error=access_denied" : "code=sample"),
      );
      open();
      expect(
        await screen.findByText("botWebLogin." + reason),
      ).toBeInTheDocument();
      expect(screen.getByLabelText("lynxceSignIn.target")).toBeEnabled();
      expect(exchange).not.toHaveBeenCalled();
    },
  );
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
      await screen.findByRole("button", { name: "botWebLogin.passwordMode" }),
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
    expect(login).toHaveBeenCalledWith(
      "13800000000",
      "123456",
      "en",
      "",
      undefined,
    );
    expect(getAuthToken()).toBe("issued");
  });

  it("asks a new email account for a password, then signs in with the same code", async () => {
    vi.spyOn(authApi, "getLynxceIdentityStatus").mockResolvedValue({
      enabled: true,
      claimed: false,
      cloud: true,
    });
    vi.spyOn(authApi, "lynxceSendCode").mockResolvedValue({ channel: "email" });
    const login = vi
      .spyOn(authApi, "lynxceCodeLogin")
      .mockRejectedValueOnce(
        new Error(
          '422: {"error":{"code":"LYNXCE_SIGNUP_PASSWORD_REQUIRED","message":"Set a password"}}',
        ),
      )
      .mockResolvedValue(session as never);
    open();
    await userEvent.click(
      await screen.findByRole("button", { name: "botPreview.composer" }),
    );
    await userEvent.type(
      await screen.findByLabelText("lynxceSignIn.target"),
      "new@b.cn",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "lynxceSignIn.send" }),
    );
    await screen.findByText("lynxceSignIn.sentEmail");
    await userEvent.type(screen.getByLabelText("lynxceSignIn.code"), "123456");
    expect(login).toHaveBeenLastCalledWith(
      "new@b.cn",
      "123456",
      "en",
      "",
      undefined,
    );
    expect(
      await screen.findByLabelText("lynxceSignIn.newPassword"),
    ).toBeInTheDocument();
    const submit = screen.getByRole("button", {
      name: "botWebLogin.submit",
    });
    await userEvent.type(
      screen.getByLabelText("lynxceSignIn.newPassword"),
      "short",
    );
    // Too short: the form points at the password instead of signing in.
    await userEvent.click(submit);
    expect(login).toHaveBeenCalledTimes(1);
    await userEvent.type(
      screen.getByLabelText("lynxceSignIn.newPassword"),
      "-enough{Enter}",
    );
    expect(
      await screen.findByRole("heading", { name: "Workspace" }),
    ).toBeInTheDocument();
    expect(login).toHaveBeenLastCalledWith(
      "new@b.cn",
      "123456",
      "en",
      "",
      "short-enough",
    );
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
      screen.getByRole("button", { name: "botWebLogin.passwordMode" }),
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
