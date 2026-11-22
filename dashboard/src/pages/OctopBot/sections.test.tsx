import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { ConfigProvider } from "antd";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  octopBotApi,
  type BotGroup,
  type BotWorkspace,
} from "../../api/modules/octopBot";
import OctopBotPage from "./index";
import { octopAgentsApi } from "../../api/modules/octopAgents";

const fixture = vi.hoisted(() => ({ mobile: false }));
vi.mock("react-i18next", () => {
  const t = (key: string, data?: { name?: string; groups?: string }) =>
    key + (data?.name || data?.groups ? ":" + (data.name || data.groups) : "");
  return { useTranslation: () => ({ t, i18n: { language: "zh" } }) };
});
vi.mock("../../utils/desktopBridge", async (original) => ({
  ...(await original<typeof import("../../utils/desktopBridge")>()),
  isBotClient: () => true,
  isBotOnlyDesktop: () => true,
}));
vi.mock("../../hooks/useCurrentUser", () => ({
  useCurrentUser: () => ({ role: "admin", username: "owner" }),
}));
vi.mock("../../context/AgentContext", () => ({
  useAgent: () => ({ agents: [], refresh: vi.fn() }),
}));
vi.mock("../../hooks/useIsMobile", () => ({
  useIsMobile: () => fixture.mobile,
}));
vi.mock("./useBotMotion", () => ({ useBotMotion: () => "idle" }));
vi.mock("../Chat/hooks/chatStore", () => ({
  onStreamEvent: () => () => {},
  subscribe: () => () => {},
  getSnapshot: () => ({ messages: [] }),
}));
vi.mock("./BotCharacter", () => ({
  BotCharacter: () => null,
  GroupCharacter: () => null,
  octopCharacter: {},
}));
vi.mock("./BotChat", () => ({
  default: function BotChat({ onOpenList }: { onOpenList?: () => void }) {
    const location = useLocation();
    return (
      <>
        {location.state?.newChat && <output>{location.pathname}</output>}
        {onOpenList && <button onClick={onOpenList}>Directory</button>}
      </>
    );
  },
}));
vi.mock("./GroupRoom", () => ({ default: () => null }));
vi.mock("./GroupForms", async (original) => ({
  ...(await original<typeof import("./GroupForms")>()),
  GroupForm: ({
    seed,
    onSaved,
  }: {
    seed?: { name: string; memberIds: string[] };
    onSaved: (group: BotGroup) => void;
  }) => (
    <>
      <output>{JSON.stringify(seed)}</output>
      <button
        onClick={() =>
          onSaved({
            name: "New chat",
            group_id: "new-chat",
            admin_id: "writer",
            member_ids: ["writer"],
            reply_mode: "admin_first",
          })
        }
      >
        Confirm new chat
      </button>
    </>
  ),
}));
vi.mock("./DirectorySearch", () => ({
  default: ({ items }: { items: { key: string; keywords: string }[] }) => (
    <output>{JSON.stringify(items.map((it) => [it.key, it.keywords]))}</output>
  ),
}));
vi.mock("./BotQuickCreate", () => ({ default: () => null }));
vi.mock("../Chat/components/ChatNavDrawers", () => ({
  ExpertCreateDrawer: () => null,
}));
vi.mock("../Experts/components/ManagedDrawer", () => ({ default: () => null }));
vi.mock("./RetainedFolders", () => ({
  default: () => <h2>Protected folders</h2>,
}));
vi.mock("./AppearancePicker", () => ({
  default: () => null,
  AppearancePicker: () => null,
  saveAppearance: vi.fn(),
}));

let server: BotWorkspace;
const getComputedStyle = window.getComputedStyle.bind(window);
beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(window, "getComputedStyle").mockImplementation((el) =>
    getComputedStyle(el),
  );
  fixture.mobile = false;
  server = {
    revision: 4,
    chief_id: "chief",
    pinned: ["bot:writer"],
    sections: [
      {
        name: "Drafts",
        items: ["bot:writer"],
        collapsed: false,
        color: "green",
      },
    ],
    bots: [
      ["chief", "Chief"],
      ["writer", "Writer"],
      ["editor", "Editor"],
      ["private", "Private"],
    ].map(([agent_id, name]) => ({
      agent_id,
      name,
      is_main: agent_id === "chief",
      is_private: agent_id === "private",
    })),
    groups: [
      {
        group_id: "team",
        name: "Editorial",
        admin_id: "chief",
        member_ids: ["chief", "editor"],
        reply_mode: "admin_first",
      },
    ],
  };
  vi.spyOn(octopBotApi, "workspace").mockImplementation(async () =>
    structuredClone(server),
  );
  vi.spyOn(octopBotApi, "saveLayout").mockImplementation(async (layout) => {
    expect(layout.revision).toBe(server.revision);
    const saved = { ...layout, revision: layout.revision + 1 };
    server = { ...server, ...saved };
    return saved;
  });
});
function CloudRoute() {
  return <output>{useLocation().state?.from}</output>;
}
function openDirectory() {
  return render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <MemoryRouter initialEntries={["/octop-bot/bots/chief"]}>
        <Routes>
          <Route path="/octop-bot/bots/:agentId" element={<OctopBotPage />} />
          <Route path="/octop-bot/groups/:groupId" element={<OctopBotPage />} />
          <Route path="/octop-bot/cloud" element={<CloudRoute />} />
        </Routes>
      </MemoryRouter>
    </ConfigProvider>,
  );
}
function section(name: string) {
  return within(
    document.querySelector(
      'section[data-section-name="' + name + '"]',
    ) as HTMLElement,
  );
}
const create = "octopBot.newSection";
const save = "octopBot.save";
const edit = (s: string) => "octopBot.sectionUI.manageEntries:" + s;
async function actions(s: string) {
  fireEvent.click(
    await screen.findByRole("button", { name: "octopBot.itemActions:" + s }),
  );
}

async function blankMenu(key: string, keyboard = false) {
  const surface = await screen.findByRole("group", {
    name: "botDirectory.teamTab",
  });
  if (keyboard) fireEvent.keyDown(surface, { key: "F10", shiftKey: true });
  else fireEvent.contextMenu(surface, { clientX: 40, clientY: 110 });
  fireEvent.click(await screen.findByRole("menuitem", { name: key }));
}

// Mirrors request(): the status line followed by the API error envelope.
const layoutChanged = (code = "BOT_LAYOUT_CHANGED") =>
  new Error(
    "Request failed: 409 Conflict - " +
      JSON.stringify({ error: { code, message: "changed" } }),
  );

describe("directory sections", () => {
  it("confirms deletion of a private Bot, handles errors and opens its protected folder", async () => {
    const remove = vi
      .spyOn(octopAgentsApi, "remove")
      .mockRejectedValueOnce(new Error("Busy"))
      .mockImplementation(async (id) => {
        server.bots = server.bots.filter((bot) => bot.agent_id !== id);
      });
    openDirectory();
    const openDelete = async () => {
      fireEvent.contextMenu(
        await screen.findByRole("button", { name: "Private" }),
      );
      fireEvent.click(
        await screen.findByRole("menuitem", { name: "octopBot.deleteBot" }),
      );
      return within(
        await screen.findByRole("dialog", {
          name: "experts.confirmDelete:Private",
        }),
      );
    };
    const first = await openDelete();
    expect(first.getByText("octopBot.deletePrivateHint")).toBeInTheDocument();
    fireEvent.click(first.getByRole("button", { name: "common.cancel" }));
    expect(remove).not.toHaveBeenCalled();
    const confirm = await openDelete();
    fireEvent.click(
      confirm.getByRole("button", { name: "octopBot.deleteBot" }),
    );
    await confirm.findByText("Busy");
    fireEvent.click(
      confirm.getByRole("button", { name: "octopBot.deleteBot" }),
    );
    await screen.findByRole("heading", { name: "Protected folders" });
    expect(remove).toHaveBeenCalledWith("private");
    expect(screen.queryByRole("button", { name: "Private" })).toBeNull();
  });

  it("keeps Chief fixed and requires removing a group member before deletion", async () => {
    openDirectory();
    fireEvent.contextMenu(await screen.findByRole("button", { name: "Chief" }));
    const menu = within(await screen.findByRole("menu"));
    expect(menu.queryByText("octopBot.deleteBot")).toBeNull();
    fireEvent.contextMenu(screen.getByRole("button", { name: "Editor" }));
    fireEvent.click(
      await screen.findByRole("menuitem", { name: "octopBot.deleteBot" }),
    );
    const confirm = within(await screen.findByRole("dialog"));
    expect(confirm.getByText("octopBot.deleteBotHint")).toBeInTheDocument();
    expect(
      confirm.getByText("octopBot.deleteGroupMemberHint:Editorial"),
    ).toBeInTheDocument();
    expect(
      confirm.getByRole("button", { name: "octopBot.deleteBot" }),
    ).toBeDisabled();
  });

  it("opens a fresh chat for the contact chosen from the directory", async () => {
    openDirectory();
    await actions("Writer");
    fireEvent.click(
      await screen.findByRole("menuitem", {
        name: "botDirectory.newPrivateChat",
      }),
    );
    expect(await screen.findByText("/octop-bot/bots/writer")).toBeVisible();
  });

  it("prepares another group using the source administrator, members and reply mode", async () => {
    server.groups[0].admin_id = "editor";
    server.groups[0].reply_mode = "all_members";
    openDirectory();
    await actions("Editorial");
    fireEvent.click(
      await screen.findByRole("menuitem", {
        name: "botDirectory.newGroupWithMembers",
      }),
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      '{"memberIds":["editor","chief"],"replyMode":"all_members"}',
    );
  });

  it("creates a named section containing several selected entries, preserves pins inside it and keeps Chief fixed", async () => {
    openDirectory();
    await screen.findByRole("button", { name: "Writer" });
    expect(
      section("Drafts").getByRole("button", { name: "Writer" }),
    ).toBeVisible();
    await blankMenu(create);
    const dialog = within(await screen.findByRole("dialog"));
    expect(dialog.queryByRole("checkbox", { name: /Chief/ })).toBeNull();
    fireEvent.change(dialog.getByLabelText("octopBot.sectionUI.name"), {
      target: { value: "Press" },
    });
    fireEvent.click(dialog.getByRole("checkbox", { name: /Writer/ }));
    fireEvent.click(dialog.getByRole("checkbox", { name: /Editorial/ }));
    fireEvent.click(dialog.getByRole("button", { name: save }));
    await waitFor(() => expect(server.revision).toBe(5));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(server.sections).toEqual([
      { name: "Drafts", color: "green", collapsed: false, items: [] },
      { name: "Press", items: ["bot:writer", "group:team"] },
    ]);
    expect(server.pinned).toEqual(["bot:writer"]);
    expect(
      section("Press").getByRole("button", { name: "Writer" }),
    ).toBeVisible();
    expect(screen.getAllByRole("button", { name: "Writer" })).toHaveLength(1);
  });

  it("shows a conflicting save in the editor and applies only the user's changes on retry", async () => {
    openDirectory();
    fireEvent.click(
      await screen.findByRole("button", { name: edit("Drafts") }),
    );
    const dialog = within(screen.getByRole("dialog"));
    fireEvent.click(dialog.getByRole("checkbox", { name: /Editor editor/ }));
    vi.mocked(octopBotApi.saveLayout).mockImplementationOnce(async () => {
      server = {
        ...server,
        revision: 5,
        sections: [
          { ...server.sections[0], items: ["bot:writer", "group:team"] },
        ],
      };
      throw layoutChanged();
    });
    fireEvent.click(dialog.getByRole("button", { name: save }));
    await dialog.findByText("octopBot.sectionUI.conflict");
    expect(
      dialog.getByRole("checkbox", { name: /Editor editor/ }),
    ).toBeChecked();
    expect(dialog.getByRole("checkbox", { name: /Editorial/ })).toBeChecked();
    fireEvent.click(dialog.getByRole("button", { name: save }));
    await waitFor(() => expect(server.revision).toBe(6));
    expect(server.sections[0].items).toEqual([
      "bot:writer",
      "group:team",
      "bot:editor",
    ]);
  });

  it("treats only the layout revision code as a conflict and keeps a retry for other 409s", async () => {
    openDirectory();
    fireEvent.click(
      await screen.findByRole("button", { name: edit("Drafts") }),
    );
    const dialog = within(screen.getByRole("dialog"));
    fireEvent.click(dialog.getByRole("checkbox", { name: /Editor editor/ }));
    const workspace = vi.mocked(octopBotApi.workspace);
    const loads = workspace.mock.calls.length;
    vi.mocked(octopBotApi.saveLayout).mockRejectedValueOnce(
      layoutChanged("TEAM_MEMBER_INVALID"),
    );
    fireEvent.click(dialog.getByRole("button", { name: save }));
    await waitFor(() =>
      expect(dialog.queryByText("octopBot.sectionUI.conflict")).toBeNull(),
    );
    await dialog.findByText(/apiErrors\.TEAM_MEMBER_INVALID|changed/);
    expect(workspace.mock.calls.length).toBe(loads);
  });

  it("moves a filtered selection out of a section and leaves its group chat and unrelated Bots in place", async () => {
    server.sections[0].items = ["bot:writer", "bot:editor", "group:team"];
    openDirectory();
    await blankMenu("octopBot.sectionUI.moveMany", true);
    const dialog = within(screen.getByRole("dialog"));
    fireEvent.change(
      dialog.getByRole("textbox", { name: "octopBot.sectionUI.find" }),
      { target: { value: "bot:" } },
    );
    fireEvent.click(
      dialog.getByRole("checkbox", {
        name: "octopBot.sectionUI.selectMatches",
      }),
    );
    fireEvent.mouseDown(
      dialog.getByRole("combobox", { name: "octopBot.sectionUI.destination" }),
    );
    fireEvent.click(screen.getByTitle("octopBot.ungrouped"));
    fireEvent.click(
      dialog.getByRole("button", { name: "octopBot.sectionUI.moveAction" }),
    );
    await waitFor(() => expect(server.revision).toBe(5));
    expect(server.sections[0].items).toEqual(["group:team"]);
    expect(server.groups).toHaveLength(1);
    expect(server.pinned).toEqual(["bot:writer"]);
  });

  it("renames, reorders, collapses and dissolves a section while retaining its bots and conversations", async () => {
    server.sections.push({ name: "Ops", items: ["bot:editor"] });
    openDirectory();
    await actions("Ops");
    fireEvent.click(
      await screen.findByRole("menuitem", { name: "octopBot.moveUp" }),
    );
    await waitFor(() => expect(server.sections[0].name).toBe("Ops"));
    await actions("Ops");
    fireEvent.click(
      await screen.findByRole("menuitem", { name: "common.rename" }),
    );
    const name = await screen.findByRole("textbox", {
      name: "octopBot.sectionUI.name",
    });
    fireEvent.change(name, { target: { value: "Drafts" } });
    expect(screen.getByRole("button", { name: save })).toBeDisabled();
    fireEvent.change(name, { target: { value: "News" } });
    fireEvent.keyDown(name, { key: "Enter", code: "Enter", keyCode: 13 });
    await waitFor(() => expect(server.sections[0].name).toBe("News"));
    fireEvent.click(section("News").getByRole("button", { name: /News 1/ }));
    await waitFor(() => expect(server.sections[0].collapsed).toBe(true));
    expect(screen.queryByRole("button", { name: "Editor" })).toBeNull();
    await actions("News");
    fireEvent.click(
      await screen.findByRole("menuitem", { name: "octopBot.dissolveSection" }),
    );
    const confirm = within(await screen.findByRole("dialog"));
    expect(
      confirm.getByText("octopBot.sectionUI.removeHint:News"),
    ).toBeInTheDocument();
    fireEvent.click(
      confirm.getByRole("button", { name: "octopBot.dissolveSection" }),
    );
    await waitFor(() =>
      expect(server.sections.map((s) => s.name)).toEqual(["Drafts"]),
    );
    expect(screen.getByRole("button", { name: "Editor" })).toBeVisible();
    expect(server.bots).toHaveLength(4);
  });

  it("lists only the section's eligible Bots in its group chat seed and exposes sections to directory search", async () => {
    server.sections[0].items = [
      "bot:writer",
      "bot:private",
      "bot:editor",
      "group:team",
    ];
    server.bots.find((b) => b.agent_id === "editor")!.can_join_group = false;
    openDirectory();
    await screen.findByRole("button", { name: "Writer" });
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    expect(screen.getByRole("status").textContent).toContain(
      '["bot:writer","Drafts',
    );
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    await actions("Drafts");
    fireEvent.click(
      await screen.findByRole("menuitem", {
        name: "octopBot.sectionUI.startChat",
      }),
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      '{"name":"Drafts","memberIds":["writer"]}',
    );
    expect(octopBotApi.saveLayout).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Confirm new chat" }));
    await waitFor(() =>
      expect(server.sections[0].items).toContain("group:new-chat"),
    );
  });

  it("retries a failed layout action inside the mobile directory", async () => {
    fixture.mobile = true;
    openDirectory();
    fireEvent.click(await screen.findByRole("button", { name: "Directory" }));
    await screen.findByRole("button", { name: "Writer" });
    vi.mocked(octopBotApi.saveLayout).mockRejectedValueOnce(
      new Error("Connection lost"),
    );
    fireEvent.click(
      section("Drafts").getByRole("button", { name: /Drafts 1/ }),
    );
    expect(await screen.findByText("Connection lost")).toBeVisible();
    expect(server.sections[0].collapsed).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "octopBot.retry" }));
    await waitFor(() => expect(server.sections[0].collapsed).toBe(true));
    expect(octopBotApi.saveLayout).toHaveBeenCalledTimes(2);
  });
  it("keeps section commands off the toolbar and general add menu", async () => {
    openDirectory();
    const add = await screen.findByRole("button", { name: "octopBot.add" });
    expect(screen.queryByRole("button", { name: create })).toBeNull();
    expect(
      screen.queryByRole("button", { name: "octopBot.sectionUI.moveMany" }),
    ).toBeNull();
    fireEvent.click(add);
    expect(
      await screen.findByRole("menuitem", { name: "octopBot.newGroup" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: create })).toBeNull();
    expect(octopBotApi.saveLayout).not.toHaveBeenCalled();
  });

  it.each([
    ["Writer", false],
    ["Editorial", true],
  ])(
    "opens the menu for %s only and preselects that contact when creating a section",
    async (name, keyboard) => {
      openDirectory();
      const row = await screen.findByRole("button", { name: String(name) });
      if (keyboard) fireEvent.keyDown(row, { key: "ContextMenu" });
      else fireEvent.contextMenu(row, { clientX: 75, clientY: 140 });
      expect(await screen.findByText("octopBot.move")).toBeInTheDocument();
      expect(screen.getAllByRole("menu")).toHaveLength(1);
      fireEvent.click(screen.getByRole("menuitem", { name: create }));
      const dialog = within(await screen.findByRole("dialog"));
      expect(
        dialog.getByRole("checkbox", { name: new RegExp(String(name)) }),
      ).toBeChecked();
      expect(
        dialog.getByRole("checkbox", { name: /Private/ }),
      ).not.toBeChecked();
    },
  );

  it("opens the section's own menu with Shift+F10 and restores focus to its header on Escape", async () => {
    openDirectory();
    await screen.findByRole("button", { name: "Writer" });
    const header = section("Drafts").getByRole("button", { name: /Drafts 1/ });
    header.focus();
    fireEvent.keyDown(header, { key: "F10", shiftKey: true });
    const menu = await screen.findByRole("menu");
    expect(
      within(menu).getByRole("menuitem", { name: "octopBot.sectionUI.edit" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: create })).toBeNull();
    fireEvent.keyDown(menu, { key: "Escape", keyCode: 27 });
    await waitFor(() => expect(screen.queryByRole("menu")).toBeNull());
    expect(header).toHaveFocus();
  });

  it("retains move and create commands behind the existing touch overflow", async () => {
    fixture.mobile = true;
    openDirectory();
    fireEvent.click(await screen.findByRole("button", { name: "Directory" }));
    await actions("Writer");
    for (const name of [create, "octopBot.move", "octopBot.sectionUI.moveMany"])
      expect(await screen.findByText(name)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: create })).toBeNull();
  });

  it("moves an item using its context submenu while closing an earlier overflow menu", async () => {
    openDirectory();
    await actions("Editor");
    const trigger = screen.getByRole("button", {
      name: "octopBot.itemActions:Editor",
    });
    fireEvent.contextMenu(trigger, { clientX: 140, clientY: 200 });
    await waitFor(() => expect(screen.getAllByRole("menu")).toHaveLength(1));
    const submenu = within(screen.getByRole("menu")).getByText("octopBot.move");
    fireEvent.mouseOver(submenu.closest("[role=menuitem]")!);
    fireEvent.click(await screen.findByRole("menuitem", { name: "Drafts" }));
    await waitFor(() =>
      expect(server.sections[0].items).toEqual(["bot:writer", "bot:editor"]),
    );
  });

  it("opens the cloud workspace from the standalone footer with a return path", async () => {
    openDirectory();
    fireEvent.click(
      await screen.findByRole("button", { name: "botCloud.title" }),
    );
    expect(await screen.findByRole("status")).toHaveTextContent(
      "/octop-bot/bots/chief",
    );
  });
});
