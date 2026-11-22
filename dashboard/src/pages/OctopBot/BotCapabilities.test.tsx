import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import {
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";
import { octopBotApi } from "../../api/modules/octopBot";
import BotClientRoutes from "./BotClientRoutes";

const mocks = vi.hoisted(() => ({
  user: { role: "admin", permissions: [] as string[] } as {
    role: string;
    permissions: string[];
  } | null,
  active: "writer" as string | null,
  setActiveAgent: vi.fn(),
  agents: [] as { agent_id: string; kind?: string; name?: string }[],
}));

/** Upstream page stub that can follow the links real pages use. */
const upstream = vi.hoisted(() => (name: string) => async () => {
  const { createElement: h } = await import("react");
  const { useNavigate } = await import("react-router-dom");
  function Page() {
    const navigate = useNavigate();
    const go = (label: string, to: string, state?: unknown) =>
      h(
        "button",
        { key: label, onClick: () => navigate(to, { state }) },
        label,
      );
    return h("div", null, [
      h("h2", { key: "title" }, name + " page"),
      go("chat", "/chat", { prefillInput: "Summarise the base" }),
      go("packages", "/skill-packages"),
      go("models", "/admin/models"),
      go("experts", "/experts"),
      go("tab", "?tab=custom"),
    ]);
  }
  return { default: Page };
});

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("../../hooks/useCurrentUser", () => ({
  useCurrentUser: () => mocks.user,
}));
vi.mock("../../hooks/useIsMobile", () => ({ useIsMobile: () => false }));
vi.mock("../../context/AgentContext", () => ({
  useAgent: () => ({
    agents: mocks.agents,
    activeAgentId: mocks.active,
    activeAgent: mocks.agents.find((a) => a.agent_id === mocks.active) ?? null,
    setActiveAgent: mocks.setActiveAgent,
  }),
}));
vi.mock("../../api/modules/octopBot", () => ({
  octopBotApi: { workspace: vi.fn() },
}));
vi.mock("../../layouts/PageShell", async () => {
  const { createElement: h } = await import("react");
  return {
    default: ({ title, children }: { title: string; children: unknown }) =>
      h("section", null, h("h2", null, title), children),
    pageShellStyles: {},
  };
});
vi.mock("../Agent/Skills/components/SkillsTabs", () => ({
  default: ({ agentId }: { agentId: string }) => "skills of " + agentId,
}));
vi.mock("../Agent/Memory/MemoryPanel", () => ({
  default: ({ agentId }: { agentId: string }) => "memory of " + agentId,
}));
vi.mock("../Agent/Channels/ChannelsPanel", () => ({
  default: ({ agentId }: { agentId: string }) => "channels of " + agentId,
}));
vi.mock("../Agent/Connectors", upstream("connectors"));
vi.mock("../SkillPackages", upstream("skill-packages"));
vi.mock("../KnowledgeBases", upstream("knowledge"));
vi.mock("../Admin/Plugins", upstream("plugins"));
vi.mock("../Agent/ACP", upstream("acp"));
vi.mock("../Control/CronJobs", upstream("tasks"));
vi.mock("./index", async () => {
  const { createElement: h } = await import("react");
  const { useLocation } = await import("react-router-dom");
  return {
    default: function Workspace() {
      const { state } = useLocation();
      return h("p", null, "workspace " + (state?.prefillInput ?? ""));
    },
  };
});
vi.mock("./BotClientSettings", async () => {
  const { createElement: h } = await import("react");
  const { useLocation } = await import("react-router-dom");
  return {
    default: function Settings() {
      const { state } = useLocation();
      return h("p", null, "settings from " + state?.from);
    },
  };
});
vi.mock("./CloudWorkspace", () => ({ default: () => null }));
vi.mock("./BotGettingStarted", () => ({ default: () => null }));
vi.mock("./BotClientSetup", () => ({ default: () => null }));

function Where() {
  const { pathname, search } = useLocation();
  return <output data-testid="where">{pathname + search}</output>;
}
function open(path: string, state?: unknown) {
  const [pathname, query] = path.split("?");
  return render(
    <MemoryRouter
      initialEntries={[{ pathname, search: query ? "?" + query : "", state }]}
    >
      <BotClientRoutes />
      <Where />
    </MemoryRouter>,
  );
}
const where = () => screen.getByTestId("where").textContent;
const nav = () =>
  within(screen.getByRole("navigation", { name: "botCapabilities.title" }));

// Load the lazy route chunks up front so the first test does not race them.
beforeAll(async () => {
  await import("./BotCapabilities");
  await import("./BotCapabilityPanels");
});
beforeEach(() => {
  vi.clearAllMocks();
  mocks.user = { role: "admin", permissions: [] };
  mocks.active = "writer";
  mocks.agents = [{ agent_id: "writer", name: "Writer" }];
  vi.mocked(octopBotApi.workspace).mockResolvedValue({
    chief_id: "chief",
  } as Awaited<ReturnType<typeof octopBotApi.workspace>>);
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Bot client capabilities", () => {
  it.each([
    ["connectors", "connectors page"],
    ["skills", "pageShell.skills.title"],
    ["skill-packages", "skill-packages page"],
    ["knowledge", "knowledge page"],
    ["memory", "pageShell.memory.title"],
    ["channels", "pageShell.channels.title"],
    ["plugins", "plugins page"],
    ["acp", "acp page"],
    ["tasks", "tasks page"],
  ])("renders the %s section inside the Bot shell", async (section, title) => {
    open("/octop-bot/capabilities/" + section);
    expect(
      await screen.findByRole("heading", { name: title }, { timeout: 5000 }),
    ).toBeVisible();
    expect(
      nav().getByRole("button", {
        name: "botCapabilities.sections." + section,
      }),
    ).toHaveAttribute("aria-current", "page");
    expect(
      screen.getByRole("heading", { name: "botCapabilities.title" }),
    ).toBeVisible();
  });

  it("scopes agent panels to the active Bot and keeps team hosts out of skills", async () => {
    open("/octop-bot/capabilities/memory");
    expect(await screen.findByText("memory of writer")).toBeVisible();
    mocks.agents = [{ agent_id: "writer", kind: "team", name: "Crew" }];
    fireEvent.click(
      nav().getByRole("button", { name: "botCapabilities.sections.skills" }),
    );
    expect(
      await screen.findByText("agentSelector.teamNeedsExpert"),
    ).toBeVisible();
    expect(screen.queryByText("skills of writer")).toBeNull();
  });

  it("opens the first section and maps upstream dashboard paths into the area", async () => {
    open("/octop-bot/capabilities");
    await screen.findByRole("heading", { name: "connectors page" });
    expect(where()).toBe("/octop-bot/capabilities/connectors");
  });

  it.each([
    ["/connectors?tab=custom", "/octop-bot/capabilities/connectors?tab=custom"],
    ["/personalization/skills", "/octop-bot/capabilities/skills"],
    ["/knowledge-bases", "/octop-bot/capabilities/knowledge"],
    ["/admin/plugins?tab=market", "/octop-bot/capabilities/plugins?tab=market"],
    ["/tasks", "/octop-bot/capabilities/tasks"],
    ["/acp", "/octop-bot/capabilities/acp"],
  ])("redirects %s to its Bot page", async (path, expected) => {
    open(path);
    await screen.findByRole("navigation", { name: "botCapabilities.title" });
    expect(where()).toBe(expected);
  });

  it("defaults the agent to the Bot named in the link, the Bot the user came from, else the Chief", async () => {
    const view = open("/octop-bot/capabilities/skills?bot=editor");
    await screen.findByText("skills of writer");
    expect(mocks.setActiveAgent).toHaveBeenCalledWith("editor");
    expect(octopBotApi.workspace).not.toHaveBeenCalled();
    view.unmount();

    mocks.setActiveAgent.mockClear();
    const next = open("/octop-bot/capabilities/tasks", {
      from: "/octop-bot/bots/reviewer/thread-1",
    });
    await screen.findByRole("heading", { name: "tasks page" });
    expect(mocks.setActiveAgent).toHaveBeenCalledWith("reviewer");
    next.unmount();

    mocks.setActiveAgent.mockClear();
    open("/octop-bot/capabilities/tasks", { from: "/octop-bot" });
    await screen.findByRole("heading", { name: "tasks page" });
    await vi.waitFor(() =>
      expect(mocks.setActiveAgent).toHaveBeenCalledWith("chief"),
    );
    // Moving between sections keeps the user's own pick.
    fireEvent.click(
      nav().getByRole("button", { name: "botCapabilities.sections.acp" }),
    );
    await screen.findByRole("heading", { name: "acp page" });
    expect(mocks.setActiveAgent).toHaveBeenCalledTimes(1);
  });

  it("keeps embedded page links inside the Bot client", async () => {
    open("/octop-bot/capabilities/knowledge");
    fireEvent.click(await screen.findByRole("button", { name: "tab" }));
    expect(where()).toBe("/octop-bot/capabilities/knowledge?tab=custom");
    fireEvent.click(screen.getByRole("button", { name: "packages" }));
    await screen.findByRole("heading", { name: "skill-packages page" });
    expect(where()).toBe("/octop-bot/capabilities/skill-packages");

    fireEvent.click(screen.getByRole("button", { name: "models" }));
    expect(
      await screen.findByText(
        "settings from /octop-bot/capabilities/skill-packages",
      ),
    ).toBeVisible();
  });

  it("sends chat links to the scoped Bot with their draft", async () => {
    open("/octop-bot/capabilities/tasks");
    fireEvent.click(await screen.findByRole("button", { name: "chat" }));
    expect(
      await screen.findByText("workspace Summarise the base"),
    ).toBeVisible();
    expect(where()).toBe("/octop-bot/bots/writer");
  });

  it("sends unknown dashboard links to the workspace instead of a dead end", async () => {
    open("/octop-bot/capabilities/acp");
    fireEvent.click(await screen.findByRole("button", { name: "experts" }));
    await screen.findByText(/^workspace/);
    expect(where()).toBe("/octop-bot");
  });

  it("only lists the sections the account may open", async () => {
    mocks.user = {
      role: "user",
      permissions: ["connector_enabled", "memory", "tasks"],
    };
    open("/octop-bot/capabilities/acp");
    await screen.findByRole("heading", { name: "connectors page" });
    expect(where()).toBe("/octop-bot/capabilities/connectors");
    expect(
      nav()
        .getAllByRole("button")
        .map((b) => b.textContent),
    ).toEqual([
      "botCapabilities.sections.connectors",
      "botCapabilities.sections.memory",
      "botCapabilities.sections.tasks",
    ]);
    expect(nav().queryByText("botCapabilities.groups.reach")).toBeNull();
  });

  it("explains when nothing can be managed", async () => {
    mocks.user = { role: "user", permissions: [] };
    open("/octop-bot/capabilities/connectors");
    expect(await screen.findByText("botCapabilities.empty")).toBeVisible();
    expect(screen.queryByRole("navigation")).toBeNull();
  });

  it("returns to where the user came from after switching sections", async () => {
    open("/octop-bot/capabilities/connectors", {
      from: "/octop-bot/bots/writer/thread-2",
    });
    await screen.findByRole("heading", { name: "connectors page" });
    fireEvent.click(
      nav().getByRole("button", { name: "botCapabilities.sections.plugins" }),
    );
    await screen.findByRole("heading", { name: "plugins page" });
    fireEvent.click(screen.getByRole("button", { name: "common.backToChat" }));
    expect(where()).toBe("/octop-bot/bots/writer/thread-2");
  });

  it("subscribes to desktop shortcuts once and reads the current route", async () => {
    let openSettings = () => {};
    const bridge = {
      onBotShortcut: vi.fn(() => vi.fn()),
      onOpenBotSettings: vi.fn((callback: () => void) => {
        openSettings = callback;
        return vi.fn();
      }),
    };
    vi.stubGlobal("octopDesktop", bridge);
    open("/octop-bot/capabilities/connectors");
    await screen.findByRole("heading", { name: "connectors page" });
    for (const [section, shown] of [
      ["memory", "memory of writer"],
      ["tasks", "tasks page"],
      ["acp", "acp page"],
    ]) {
      fireEvent.click(
        nav().getByRole("button", {
          name: "botCapabilities.sections." + section,
        }),
      );
      await screen.findByText(shown);
    }
    expect(bridge.onBotShortcut).toHaveBeenCalledTimes(1);
    expect(bridge.onOpenBotSettings).toHaveBeenCalledTimes(1);
    expect(bridge.onBotShortcut.mock.results[0].value).not.toHaveBeenCalled();
    act(() => openSettings());
    expect(
      await screen.findByText("settings from /octop-bot/capabilities/acp"),
    ).toBeVisible();
  });
});
