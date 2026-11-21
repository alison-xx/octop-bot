import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { MemoryRouter, Routes, Route, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { lynxceBotApi, type LynxceStatus } from "../../api/modules/lynxceBot";
import { lynxceWalletApi } from "../../api/modules/lynxceWallet";
import { providerApi } from "../../api/modules/provider";
import { octopBotApi } from "../../api/modules/octopBot";
import BotClientSettings from "./BotClientSettings";

const mocks = vi.hoisted(() => ({ role: "admin", config: vi.fn() }));
vi.mock("react-i18next", () => {
  const t = (key: string) => key;
  return { useTranslation: () => ({ t }) };
});
vi.mock("../../hooks/useCurrentUser", () => ({
  useCurrentUser: () => ({ role: mocks.role, username: "local" }),
}));
vi.mock("./BotCharacter", () => ({
  BotCharacter: () => null,
  octopCharacter: {},
}));
vi.mock("../Settings/Models", () => ({ default: () => <h2>Catalog</h2> }));
vi.mock("../Settings/Models/components", () => ({
  CustomProviderModal: ({
    onSaved,
    onClose,
  }: {
    onSaved: () => Promise<void>;
    onClose: () => void;
  }) => (
    <button
      onClick={async () => {
        await onSaved();
        onClose();
      }}
    >
      Save connection
    </button>
  ),
  LocalServiceCard: () => null,
  PresetProviderModal: () => null,
  ProviderConfigModal: () => null,
}));
vi.mock("../Settings/Models/useProviders", async (original) => ({
  ...(await original<typeof import("../Settings/Models/useProviders")>()),
  useProviders: () => mocks.config(),
}));
vi.mock("../../api/modules/lynxceBot", () => ({
  lynxceBotApi: {
    status: vi.fn(),
    models: vi.fn(),
    login: vi.fn(),
    poll: vi.fn(),
    cancel: vi.fn(),
    select: vi.fn(),
    logout: vi.fn(),
    clearModel: vi.fn(),
  },
}));
vi.mock("../../api/modules/provider", () => ({
  providerApi: { listResolvedModels: vi.fn() },
}));

const model = {
  provider_id: 1,
  provider_name: "Studio",
  provider_kind: "openai",
  model: "draft-v2",
  name: "Draft v2",
};
const thread = "/octop-bot/bots/writer/thread-3";
function Chat() {
  const loc = useLocation();
  return (
    <output>
      {loc.pathname} {loc.state?.prefillInput}
    </output>
  );
}
function openSettings(from?: string) {
  render(
    <MemoryRouter
      initialEntries={[
        {
          pathname: "/octop-bot/settings",
          state: from ? { from, prefillInput: "Write the outline" } : null,
        },
      ]}
    >
      <Routes>
        <Route path="/octop-bot/settings" element={<BotClientSettings />} />
        <Route path="*" element={<Chat />} />
      </Routes>
    </MemoryRouter>,
  );
}
beforeEach(() => {
  vi.clearAllMocks();
  vi.spyOn(lynxceWalletApi, "balance").mockResolvedValue({
    source: "model",
    connection_id: "grant-a",
    account_id: null,
    credits: 0,
    status: "available",
    recharge_mode: "ticket",
  });
  sessionStorage.clear();
  vi.mocked(lynxceBotApi.status).mockResolvedValue({
    connected: false,
    selected_model: null,
  });
  vi.mocked(lynxceBotApi.models).mockResolvedValue({ models: [] });
  vi.mocked(lynxceBotApi.clearModel).mockResolvedValue(undefined);
  mocks.role = "admin";
  vi.mocked(providerApi.listResolvedModels).mockResolvedValue([model]);
  mocks.config.mockReturnValue({
    presets: [],
    providers: [],
    loading: false,
    error: null,
    fetchAll: vi.fn(),
  });
});

describe("standalone chat model settings", () => {
  it("opens protected folders from settings after the private expert is gone", async () => {
    vi.spyOn(octopBotApi, "retainedFolders").mockResolvedValue([
      { agent_id: "former", name: "Former expert", path: "/former/files" },
    ]);
    openSettings();
    fireEvent.click(
      screen.getByRole("button", { name: "octopBot.retainedFolders" }),
    );
    await screen.findByText("/former/files");
    expect(
      screen.getByRole("button", { name: "octopBot.releaseFolder" }),
    ).toBeEnabled();
  });
  it("opens the model catalog and retained folders on NAS without calling desktop OAuth", async () => {
    vi.stubEnv("VITE_OCTOP_BOT_WEB", "1");
    try {
      openSettings();
      expect(
        await screen.findByRole("heading", { name: "Catalog" }),
      ).toBeVisible();
      expect(
        screen.getByRole("button", { name: "octopBot.retainedFolders" }),
      ).toBeVisible();
      expect(lynxceBotApi.status).not.toHaveBeenCalled();
      expect(
        screen.queryByRole("button", { name: "account.checkUpdates" }),
      ).toBeNull();
    } finally {
      vi.unstubAllEnvs();
    }
  });
  it("shows the wallet on the overview and reauthorizes only when a legacy grant requires it", async () => {
    vi.mocked(lynxceBotApi.status).mockResolvedValue({
      connected: true,
      selected_model: "personal",
    });
    const binding = {
      source: "model",
      connection_id: "grant-b",
      account_id: null,
      credits: 23,
      status: "available",
      recharge_mode: "ticket",
    } as const;
    const checkout = vi
      .spyOn(lynxceWalletApi, "recharge")
      .mockRejectedValueOnce(
        new Error(
          'Request failed: 403 Forbidden - {"error":{"code":"BOT_LYNXCE_RECHARGE_AUTH_REQUIRED"}}',
        ),
      )
      .mockResolvedValueOnce({
        url: "https://admin.lynxce.cn/recharge?token=mcrt1." + "s".repeat(43),
        expires_at: new Date(Date.now() + 900000).toISOString(),
      });
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    vi.mocked(lynxceBotApi.login).mockResolvedValue({
      attempt_id: "consent",
      authorization_url:
        "https://api.lynxce.cn/api/oauth/mcp/authorize?state=test",
    });
    vi.mocked(lynxceBotApi.poll).mockImplementationOnce(async () => {
      vi.mocked(lynxceWalletApi.balance).mockResolvedValue(binding);
      return { state: "connected", detail: null };
    });
    openSettings();
    expect(await screen.findByText("0")).toBeInTheDocument();
    expect(screen.queryByRole("radio")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "botWallet.recharge" }));
    fireEvent.click(
      await screen.findByRole("button", { name: "botWallet.authorize" }),
    );
    await screen.findByText("23");
    expect(
      await screen.findByText("botWallet.authorizedHint"),
    ).toBeInTheDocument();
    expect(checkout).toHaveBeenCalledTimes(1);
    expect(lynxceBotApi.logout).not.toHaveBeenCalled();
    expect(open).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "botWallet.recharge" }));
    await waitFor(() => expect(open).toHaveBeenCalledTimes(2));
    expect(checkout).toHaveBeenLastCalledWith(binding, expect.any(AbortSignal));
    open.mockRestore();
    checkout.mockRestore();
  });
  it("shows real model and provider, expands connection controls on demand, and returns the selected prompt to its original thread", async () => {
    openSettings(thread);
    const list = await screen.findByRole("list", {
      name: "botClient.availableModels",
    });
    expect(within(list).getByText("Draft v2")).toBeInTheDocument();
    expect(within(list).getByText("Studio")).toBeInTheDocument();
    expect(mocks.config).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("button", { name: "botClient.addConnection" }),
    );
    expect(
      screen.getByRole("radio", { name: "botClient.custom" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "common.cancel" }));
    expect(screen.queryByRole("radio")).toBeNull();
    expect(screen.getByText("botClient.draftKept")).toBeInTheDocument();
    fireEvent.click(
      screen.getAllByRole("button", { name: "common.backToChat" }).at(-1)!,
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      thread + " Write the outline",
    );
  });

  it("distinguishes a failed model request from an empty workspace and retries the real list", async () => {
    vi.mocked(providerApi.listResolvedModels)
      .mockRejectedValueOnce(new Error("Offline"))
      .mockResolvedValueOnce([]);
    openSettings();
    await screen.findByText("Offline");
    expect(screen.queryByText("botClient.connectHint")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "octopBot.retry" }));
    expect(
      await screen.findByText("botClient.connectHint"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("radio", { name: "botClient.local" }),
    ).toBeInTheDocument();
  });

  it("refreshes the available list after the configuration dialog reports a successful save", async () => {
    vi.mocked(providerApi.listResolvedModels).mockResolvedValueOnce([]);
    openSettings(thread);
    fireEvent.click(
      await screen.findByRole("radio", { name: "botClient.custom" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "botClient.customAction" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Save connection" }));
    expect(await screen.findByText("Draft v2")).toBeInTheDocument();
    expect(screen.queryByRole("radio")).toBeNull();
    expect(screen.getByText("botClient.draftKept")).toBeInTheDocument();
  });

  it("points to the model catalog when a configured service exposes no enabled chat models", async () => {
    vi.mocked(providerApi.listResolvedModels).mockResolvedValueOnce([]);
    mocks.config.mockReturnValue({
      providers: [{ name: "Studio", models: [] }],
      presets: [],
      loading: false,
      error: null,
      fetchAll: vi.fn(),
    });
    openSettings();
    fireEvent.click(
      await screen.findByRole("radio", { name: "botClient.cloud" }),
    );
    expect(
      await screen.findByText("botClient.noEnabledModels"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "botClient.manage" }));
    expect(
      screen.getByRole("heading", { name: "Catalog" }),
    ).toBeInTheDocument();
  });

  it("shows the account's permitted models without fetching admin-only configuration", async () => {
    mocks.role = "member";
    openSettings();
    expect(await screen.findByText("Draft v2")).toBeInTheDocument();
    expect(mocks.config).not.toHaveBeenCalled();
    expect(screen.queryByText("botClient.manage")).toBeNull();
    expect(
      screen.queryByText("modelConfig.promptMessageNoPermission"),
    ).toBeNull();
  });
  it("opens the browser once, reuses the pending link after switching tabs, and cancels a late authorization reply", async () => {
    vi.mocked(providerApi.listResolvedModels).mockResolvedValue([]);
    const attempt = {
      attempt_id: "abc",
      authorization_url:
        "https://api.lynxce.cn/api/oauth/mcp/authorize?state=abc",
    };
    const opened = vi.spyOn(window, "open").mockReturnValue(null);
    vi.mocked(lynxceBotApi.login).mockResolvedValue(attempt);
    let settle!: (v: { state: "connected"; detail: null }) => void;
    vi.mocked(lynxceBotApi.poll).mockImplementation(
      () =>
        new Promise((resolve) => {
          settle = resolve;
        }),
    );
    openSettings();
    const register = await screen.findByRole("link", {
      name: "botClient.lynxce.register",
    });
    expect(register).toHaveAttribute(
      "href",
      "https://admin.lynxce.cn/profile/login",
    );
    expect(register).toHaveAttribute("rel", "noopener noreferrer");
    fireEvent.click(
      await screen.findByRole("button", { name: "botClient.lynxce.login" }),
    );
    const link = await screen.findByRole("link", {
      name: "botClient.lynxce.reopen",
    });
    expect(link).toHaveAttribute("href", attempt.authorization_url);
    expect(opened).toHaveBeenCalledWith(
      attempt.authorization_url,
      "_blank",
      "noopener,noreferrer",
    );
    fireEvent.click(screen.getByRole("radio", { name: "botClient.custom" }));
    fireEvent.click(
      screen.getByRole("radio", { name: "botClient.lynxce.source" }),
    );
    expect(
      await screen.findByRole("link", { name: "botClient.lynxce.reopen" }),
    ).toHaveAttribute("href", attempt.authorization_url);
    expect(lynxceBotApi.login).toHaveBeenCalledTimes(1);
    fireEvent.click(
      screen.getByRole("button", { name: "botClient.lynxce.cancel" }),
    );
    expect(
      await screen.findByRole("button", { name: "botClient.lynxce.login" }),
    ).toBeInTheDocument();
    expect(lynxceBotApi.cancel).toHaveBeenCalledWith("abc");
    await act(async () => settle({ state: "connected", detail: null }));
    expect(lynxceBotApi.models).not.toHaveBeenCalled();
    opened.mockRestore();
  });

  it("lets a member authorize, select an upstream model without shared providers, change it, and sign out", async () => {
    mocks.role = "member";
    vi.mocked(providerApi.listResolvedModels).mockResolvedValue([]);
    let status: LynxceStatus = { connected: false, selected_model: null };
    vi.mocked(lynxceBotApi.status).mockImplementation(async () => status);
    vi.mocked(lynxceBotApi.models).mockResolvedValue({
      models: [{ id: "upstream-v2", name: "Writer" }],
    });
    vi.mocked(lynxceBotApi.login).mockResolvedValue({
      attempt_id: "abc",
      authorization_url: "https://api.lynxce.cn/api/oauth/mcp/authorize",
    });
    vi.mocked(lynxceBotApi.poll).mockImplementation(async () => {
      status = { connected: true, selected_model: null };
      return { state: "connected", detail: null };
    });
    vi.mocked(lynxceBotApi.select).mockImplementation(
      async (id) => (status = { connected: true, selected_model: id }),
    );
    vi.mocked(lynxceBotApi.logout).mockImplementation(async () => {
      status = { connected: false, selected_model: null };
    });
    const opened = vi.spyOn(window, "open").mockReturnValue(null);
    openSettings(thread);
    fireEvent.click(
      await screen.findByRole("button", { name: "botClient.lynxce.login" }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "botClient.lynxce.apply" }),
    );
    expect(lynxceBotApi.select).toHaveBeenCalledWith("upstream-v2");
    expect(
      await screen.findByRole("list", { name: "botClient.availableModels" }),
    ).toHaveTextContent("upstream-v2");
    fireEvent.click(
      screen.getByRole("button", { name: "botClient.lynxce.manage" }),
    );
    vi.mocked(lynxceBotApi.models).mockResolvedValue({
      models: [
        { id: "upstream-v2", name: "Writer" },
        { id: "rapid", name: "Fast" },
      ],
    });
    fireEvent.click(
      await screen.findByRole("button", { name: "botClient.lynxce.refresh" }),
    );
    fireEvent.mouseDown(
      await screen.findByRole("combobox", { name: "botClient.lynxce.choose" }),
    );
    fireEvent.click(await screen.findByText("Fast"));
    fireEvent.click(
      screen.getByRole("button", { name: "botClient.lynxce.apply" }),
    );
    expect(await screen.findByText("rapid")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "botClient.lynxce.logout" }),
    );
    expect(
      await screen.findByRole("button", { name: "botClient.lynxce.login" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("list")).toBeNull();
    expect(mocks.config).not.toHaveBeenCalled();
    opened.mockRestore();
  });

  it("recovers from an empty catalog and only clears the selected source after an explicit switch or successful provider save", async () => {
    let status: LynxceStatus = { connected: true, selected_model: "personal" };
    vi.mocked(lynxceBotApi.status).mockImplementation(async () => status);
    vi.mocked(lynxceBotApi.clearModel).mockImplementation(async () => {
      status = { ...status, selected_model: null };
    });
    openSettings();
    fireEvent.click(
      await screen.findByRole("button", { name: "botClient.lynxce.manage" }),
    );
    await screen.findByText("botClient.lynxce.empty");
    vi.mocked(lynxceBotApi.models).mockResolvedValue({
      models: [{ name: "Writer", id: "personal" }],
    });
    fireEvent.click(
      screen.getByRole("button", { name: "botClient.lynxce.refresh" }),
    );
    await screen.findByRole("button", { name: "botClient.lynxce.inUse" });
    fireEvent.click(screen.getByRole("radio", { name: "botClient.custom" }));
    expect(lynxceBotApi.clearModel).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("button", { name: "botClient.customAction" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Save connection" }));
    await waitFor(() =>
      expect(lynxceBotApi.clearModel).toHaveBeenCalledTimes(1),
    );
    expect(await screen.findByText("Draft v2")).toBeInTheDocument();
    expect(lynxceBotApi.logout).not.toHaveBeenCalled();
  });
  it("keeps the account connected when switching back to an existing provider", async () => {
    let status: LynxceStatus = { connected: true, selected_model: "personal" };
    vi.mocked(lynxceBotApi.status).mockImplementation(async () => status);
    vi.mocked(lynxceBotApi.clearModel).mockImplementation(async () => {
      status = { ...status, selected_model: null };
    });
    openSettings();
    fireEvent.click(
      await screen.findByRole("button", { name: "botClient.lynxce.manage" }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "botClient.lynxce.useOther" }),
    );
    expect(await screen.findByText("Draft v2")).toBeInTheDocument();
    expect(lynxceBotApi.clearModel).toHaveBeenCalledOnce();
    expect(lynxceBotApi.logout).not.toHaveBeenCalled();
    expect(
      await screen.findByRole("button", { name: "botClient.lynxce.relogin" }),
    ).toBeInTheDocument();
  });

  it("allows retry after the browser denies authorization and after a personal catalog fails to load", async () => {
    let status: LynxceStatus = { connected: false, selected_model: null };
    vi.mocked(providerApi.listResolvedModels).mockResolvedValue([]);
    vi.mocked(lynxceBotApi.status).mockImplementation(async () => status);
    vi.mocked(lynxceBotApi.login).mockResolvedValue({
      attempt_id: "attempt",
      authorization_url: "https://api.lynxce.cn/api/oauth/mcp/authorize",
    });
    vi.mocked(lynxceBotApi.poll)
      .mockResolvedValueOnce({
        state: "failed",
        detail: "Authorization expired",
      })
      .mockImplementationOnce(async () => {
        status = { connected: true, selected_model: null };
        return { state: "connected", detail: null };
      });
    vi.mocked(lynxceBotApi.models)
      .mockRejectedValueOnce(new Error("Catalog offline"))
      .mockResolvedValueOnce({ models: [{ id: "private", name: "My model" }] });
    const opened = vi.spyOn(window, "open").mockReturnValue(null);
    openSettings();
    fireEvent.click(
      await screen.findByRole("button", { name: "botClient.lynxce.login" }),
    );
    await screen.findByText("Authorization expired");
    fireEvent.click(
      screen.getByRole("button", { name: "botClient.lynxce.login" }),
    );
    await screen.findByText("Catalog offline");
    fireEvent.click(screen.getByRole("button", { name: "octopBot.retry" }));
    expect(
      await screen.findByRole("button", { name: "botClient.lynxce.apply" }),
    ).toBeEnabled();
    expect(lynxceBotApi.login).toHaveBeenCalledTimes(2);
    opened.mockRestore();
  });
  it.each(["poll", "cancel"])(
    "forgets a restored authorization if %s reports 404 after a backend restart",
    async (operation) => {
      vi.mocked(providerApi.listResolvedModels).mockResolvedValue([]);
      const key = "octop-bot:lynxce-login:local";
      sessionStorage.setItem(
        key,
        JSON.stringify({
          attempt_id: "expired",
          authorization_url:
            "https://api.lynxce.cn/api/oauth/mcp/authorize?state=fixture",
        }),
      );
      const missing = new Error("Request failed: 404 Not Found");
      if (operation === "poll")
        vi.mocked(lynxceBotApi.poll).mockRejectedValueOnce(missing);
      else {
        vi.mocked(lynxceBotApi.poll).mockResolvedValueOnce({
          state: "pending",
          detail: null,
        });
        vi.mocked(lynxceBotApi.cancel).mockRejectedValueOnce(missing);
      }
      openSettings();
      if (operation === "cancel")
        fireEvent.click(
          await screen.findByRole("button", {
            name: "botClient.lynxce.cancel",
          }),
        );
      expect(
        await screen.findByRole("button", { name: "botClient.lynxce.login" }),
      ).toBeEnabled();
      expect(sessionStorage.getItem(key)).toBeNull();
      expect(
        screen.queryByRole("link", { name: "botClient.lynxce.reopen" }),
      ).toBeNull();
    },
  );

  it.each([
    "https://unrelated.example/api/oauth/mcp/authorize",
    "https://api.lynxce.cn/other",
  ])(
    "rejects an unexpected authorization destination %s",
    async (authorization_url) => {
      vi.mocked(providerApi.listResolvedModels).mockResolvedValue([]);
      vi.mocked(lynxceBotApi.login).mockResolvedValue({
        attempt_id: "abc",
        authorization_url,
      });
      vi.mocked(lynxceBotApi.cancel).mockResolvedValue(undefined);
      const opened = vi.spyOn(window, "open").mockReturnValue(null);
      openSettings();
      fireEvent.click(
        await screen.findByRole("button", { name: "botClient.lynxce.login" }),
      );
      await screen.findByText("botClient.lynxce.invalidLink");
      expect(opened).not.toHaveBeenCalled();
      expect(lynxceBotApi.poll).not.toHaveBeenCalled();
      expect(lynxceBotApi.cancel).toHaveBeenCalledWith("abc");
      opened.mockRestore();
    },
  );
  it("can release an expired account's source lock without signing in", async () => {
    vi.mocked(lynxceBotApi.status).mockResolvedValue({
      connected: false,
      selected_model: null,
    });
    openSettings();
    fireEvent.click(
      await screen.findByRole("button", { name: "botClient.addConnection" }),
    );
    for (const tab of ["cloud", "custom", "local"])
      fireEvent.click(
        await screen.findByRole("radio", { name: "botClient." + tab }),
      );
    expect(lynxceBotApi.clearModel).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("button", { name: "botClient.lynxce.useOther" }),
    );
    await waitFor(() =>
      expect(lynxceBotApi.clearModel).toHaveBeenCalledTimes(1),
    );
    expect(lynxceBotApi.login).not.toHaveBeenCalled();
  });
});
