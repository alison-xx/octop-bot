import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Button,
  Drawer,
  Dropdown,
  Empty,
  Popover,
  Spin,
  type MenuProps,
} from "antd";
import { message } from "@/utils/antdMessage";
import {
  Search,
  ArrowDown,
  Bot,
  Menu,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  Settings2,
  Store,
  Users,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  Navigate,
  useLocation,
  useNavigate,
  useParams,
} from "react-router-dom";
import {
  octopBotApi,
  type BotGroup,
  type BotLayout,
  type BotSection,
  type BotWorkspace,
  type WorkspaceBot,
} from "../../api/modules/octopBot";
import { octopThreadsApi } from "../../api/modules/octopThreads";
import { BOT_HOME, BOT_MARKET } from "../../utils/botClientRoute";
import { pickPreferredSession, toSession } from "../Chat/hooks/useSessions";
import { useAgent } from "../../context/AgentContext";
import { useBotActivity } from "../../hooks/useBotActivity";
import { useCurrentUser } from "../../hooks/useCurrentUser";
import { useIsMobile } from "../../hooks/useIsMobile";
import { useListPanelCollapsed } from "../../hooks/useListPanelCollapsed";
import { apiErrorMessage, parseApiError } from "../../utils/apiError";
import { navAllowed } from "../../utils/permissions";
import { isBotClient } from "../../utils/desktopBridge";
import { BotCharacter, octopCharacter, GroupCharacter } from "./BotCharacter";
import { useBotMotion } from "./useBotMotion";
import { useBotInbox } from "./useBotInbox";
import AppearanceModal, {
  AppearancePicker,
  saveAppearance,
  type AppearanceChoice,
} from "./AppearancePicker";
import { ExpertCreateDrawer } from "../Chat/components/ChatNavDrawers";
import BotQuickCreate from "./BotQuickCreate";
import { getSnapshot, onStreamEvent, subscribe } from "../Chat/hooks/chatStore";
import ManagedDrawer from "../Experts/components/ManagedDrawer";
import BotChat from "./BotChat";
import { GroupForm, canInviteBot, type GroupSeed } from "./GroupForms";
import GroupRoom from "./GroupRoom";
import { roomDraft } from "./GroupRoomDraft";
import { useOnboarding } from "./onboarding/useOnboarding";
import type { OnboardingKind } from "../../api/modules/botOnboarding";
import {
  OnboardingAsk,
  OnboardingCoach,
  OnboardingStrip,
  OnboardingTeamReady,
  OnboardingWelcome,
} from "./onboarding/OnboardingParts";
import AccountMenu from "./AccountMenu";
import CloudMove from "./CloudMove";
import RetainedFolders from "./RetainedFolders";
import DeleteBotDialog from "./DeleteBotDialog";
import DeleteGroupDialog from "./DeleteGroupDialog";
import SectionEditor, {
  moveEntries,
  type SectionAction,
} from "./SectionEditor";
import sectionStyles from "./sections.module.less";
import { useDirectoryContextMenu } from "./useDirectoryContextMenu";
import SectionHeader from "./SectionHeader";
import DirectorySearch from "./DirectorySearch";
import {
  DIRECTORY_DRAG_TYPE,
  DirectoryItem,
  type DirectoryEntry,
} from "./DirectoryItem";
import directory from "./directory.module.less";
import MoreUnreads from "./MoreUnreads";
import styles from "./index.module.less";
import offlineArt from "../../assets/bot/offline.webp";

type Item = DirectoryEntry;
const urlFor = (item: Item) =>
  item.bot
    ? BOT_HOME + "/bots/" + encodeURIComponent(item.bot.agent_id)
    : BOT_HOME + "/groups/" + encodeURIComponent(item.group!.group_id);

export default function OctopBotPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const { agentId, threadId, groupId } = useParams();
  const standalone = isBotClient();
  const motion = useBotMotion(threadId);
  // Bots with a question, approval or takeover waiting for me get a dot in the directory.
  const inbox = useBotInbox();
  const waitingBots = useMemo(
    () => new Set(inbox.map((entry) => entry.agent_id)),
    [inbox],
  );
  const [newLook, setNewLook] = useState<AppearanceChoice | null>(null);
  const [retryLook, setRetryLook] = useState<{
    id: string;
    choice: AppearanceChoice;
  } | null>(null);
  const { agents, refresh: refreshAgents } = useAgent();
  const user = useCurrentUser();
  const mobile = useIsMobile();
  const [workspace, setWorkspace] = useState<BotWorkspace | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<WorkspaceBot | null>(null);
  const [deleteGroupTarget, setDeleteGroupTarget] = useState<BotGroup | null>(
    null,
  );
  const [error, setError] = useState("");
  const [showList, setShowList] = useState(false);
  const { collapsed, toggle } = useListPanelCollapsed(
    "octop.bot.directory.collapsed",
  );
  const compactDirectory = standalone && !mobile && collapsed;
  const directoryMenu = useDirectoryContextMenu(
    workspace?.revision,
    location.pathname,
    showList,
  );
  const [dragging, setDragging] = useState(false);
  const revealSection = useRef<string>();
  const sectionNodes = useRef(new Map<string, HTMLElement>());
  const [searchOpen, setSearchOpen] = useState(false);
  const [previews, setPreviews] = useState<Record<string, string>>({});
  const rememberPreview = useCallback((key: string, value: string) => {
    const preview = value.replace(/\s+/g, " ").trim().slice(0, 160);
    if (preview)
      setPreviews((prev) =>
        prev[key] === preview ? prev : { ...prev, [key]: preview },
      );
  }, []);
  useEffect(() => {
    if (!standalone || !agentId || !threadId) return;
    const update = () => {
      const { messages, isStreaming } = getSnapshot(threadId);
      if (isStreaming) return;
      const last = messages
        .slice()
        .reverse()
        .find(
          (m) =>
            (m.role === "user" || m.role === "assistant") && m.content.trim(),
        );
      if (last) rememberPreview("bot:" + agentId, last.content);
    };
    update();
    return subscribe(threadId, update);
  }, [standalone, agentId, threadId, rememberPreview]);
  useEffect(() => {
    if (!standalone) return;
    const keydown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        if (
          event.isComposing ||
          document.querySelector("[data-section-editor]") ||
          event.repeat ||
          (event.target instanceof Element &&
            event.target.closest('[aria-modal="true"]') &&
            !searchOpen &&
            !showList)
        )
          return;
        event.preventDefault();
        setSearchOpen((open) => !open);
      }
    };
    window.addEventListener("keydown", keydown);
    return () => window.removeEventListener("keydown", keydown);
  }, [standalone, searchOpen, showList]);
  const [dialog, setDialog] = useState<
    "bot" | "managed" | "group" | "editGroup" | "section" | "retained" | null
  >(null);
  useEffect(() => {
    if (dialog || !revealSection.current) return;
    const name = revealSection.current;
    revealSection.current = undefined;
    sectionNodes.current.get(name)?.scrollIntoView?.({ block: "nearest" });
  }, [dialog, workspace?.revision]);
  const [sectionAction, setSectionAction] = useState<SectionAction>({
    kind: "create",
  });
  const [createIn, setCreateIn] = useState<string>();
  const [groupSeed, setGroupSeed] = useState<GroupSeed>();
  const [layoutError, setLayoutError] = useState("");
  const failedLayout = useRef<BotLayout>();
  const layoutBusy = useRef(false);
  const [layoutSaving, setLayoutSaving] = useState(false);
  const contactRequest = useRef(0);
  const version = useRef(0);
  const mounted = useRef(true);
  const refresh = useCallback(async () => {
    const current = ++version.current;
    try {
      const next = await octopBotApi.workspace();
      if (mounted.current && current === version.current) {
        setWorkspace((prev) =>
          prev && prev.revision > (next.revision ?? 0)
            ? {
                ...next,
                pinned: prev.pinned,
                sections: prev.sections,
                revision: prev.revision,
              }
            : next,
        );
        setError("");
      }
    } catch (e) {
      if (mounted.current && current === version.current)
        setError(apiErrorMessage(e, t("octopBot.failed"), t));
    }
  }, [t]);
  useEffect(() => {
    mounted.current = true;
    void refresh();
    const unsub = onStreamEvent((event) => {
      if (event.kind === "streamEnd") void refresh();
    });
    const focus = () => {
      if (document.visibilityState === "visible") void refresh();
    };
    document.addEventListener("visibilitychange", focus);
    return () => {
      mounted.current = false;
      unsub();
      document.removeEventListener("visibilitychange", focus);
    };
  }, [refresh]);
  const hasPreparingBot = workspace?.bots.some((bot) => bot.preparing) ?? false;
  useEffect(() => {
    if (!hasPreparingBot) return;
    const timer = window.setInterval(() => {
      void refresh();
      void refreshAgents({ silent: true, force: true });
    }, 1500);
    return () => window.clearInterval(timer);
  }, [hasPreparingBot, refresh, refreshAgents]);

  const workspaceRef = useRef(workspace);
  workspaceRef.current = workspace;
  const activityNameOf = useCallback((kind: "bot" | "group", id: string) => {
    const ws = workspaceRef.current;
    if (!ws) return null;
    return kind === "bot"
      ? ws.bots.find((b) => b.agent_id === id)?.name ?? null
      : ws.groups.find((g) => g.group_id === id)?.name ?? null;
  }, []);
  const openFromNotice = useCallback(
    (target: string) => {
      const [kind, id] = [
        target.slice(0, target.indexOf(":")),
        target.slice(target.indexOf(":") + 1),
      ];
      contactRequest.current++;
      setSearchOpen(false);
      setShowList(false);
      navigate(
        BOT_HOME +
          (kind === "group" ? "/groups/" : "/bots/") +
          encodeURIComponent(id),
      );
    },
    [navigate],
  );
  const botActivity = useBotActivity({
    enabled: workspace !== null,
    openTarget: groupId
      ? "group:" + groupId
      : agentId
      ? "bot:" + agentId
      : null,
    nameOf: activityNameOf,
    onOpen: openFromNotice,
  });
  const refreshActivity = botActivity.refresh;
  const onboarding = useOnboarding(
    standalone && workspace !== null,
    user?.id ?? null,
  );
  const changeOnboarding = onboarding.change;
  const guide = onboarding.state?.show ? onboarding.state : null;
  const guideTeam =
    guide?.status === "active" &&
    (guide.step === "team_ready" || guide.step === "first_message")
      ? guide.team
      : null;
  const [onboardingBusy, setOnboardingBusy] = useState(false);
  // New onboarding contacts keep their badge until the owner opens them.
  const [openedContacts, setOpenedContacts] = useState<string[]>([]);
  const openedKey = groupId ? "group:" + groupId : agentId && "bot:" + agentId;
  useEffect(() => {
    if (openedKey)
      setOpenedContacts((prev) =>
        prev.includes(openedKey) ? prev : [...prev, openedKey],
      );
  }, [openedKey]);
  const prefilledGroup = useRef<string>();
  useEffect(() => {
    if (!guideTeam || !user || groupId !== guideTeam.group_id) return;
    if (guide?.step === "team_ready")
      void changeOnboarding({ action: "step", step: "first_message" });
    if (prefilledGroup.current === groupId) return;
    prefilledGroup.current = groupId;
    // Chief's suggested first task waits in the group's composer.
    const draft = roomDraft(user.id, groupId);
    if (guideTeam.first_task && !draft.read().text.trim())
      draft.patch({ text: guideTeam.first_task });
  }, [guideTeam, guide?.step, groupId, user, changeOnboarding]);
  /** The line sent to Chief for the owner's pick, visible in the chat. */
  const teamRequest = useCallback(
    (kind: OnboardingKind, label: string, note?: string | null) => {
      const detail = note?.trim().replace(/[。．.！!]+$/u, "");
      return [
        t(`botOnboarding.guide.request.${kind}`, { label }),
        detail ? t("botOnboarding.guide.request.note", { note: detail }) : "",
        t("botOnboarding.guide.request.team"),
      ].join("");
    },
    [t],
  );
  const askChief = useCallback(
    (text: string) =>
      navigate(location.pathname, { replace: true, state: { autoSend: text } }),
    [navigate, location.pathname],
  );
  const skipOnboarding = useCallback(() => {
    void changeOnboarding({ action: "skip" });
    void message.info({
      content: t("botOnboarding.guide.skipped"),
      duration: 6,
    });
  }, [changeOnboarding, t]);
  useEffect(
    () =>
      onStreamEvent((event) => {
        if (event.kind === "streamEnd") refreshActivity();
      }),
    [refreshActivity],
  );
  const close = useCallback(() => {
    setDialog(null);
    setGroupSeed(undefined);
    setCreateIn(undefined);
  }, []);
  const openCreation = useCallback(
    (kind: "bot" | "managed" | "group", section?: string, seed?: GroupSeed) => {
      setShowList(false);
      setCreateIn(section);
      setGroupSeed(seed);
      setNewLook(null);
      setDialog(kind);
    },
    [],
  );
  const openMarket = useCallback(() => {
    setShowList(false);
    navigate(BOT_MARKET, { state: { from: location.pathname } });
  }, [navigate, location.pathname]);
  const startGroupWithMembers = useCallback(
    (group: BotGroup) => {
      const section = workspace?.sections.find((s) =>
        s.items.includes("group:" + group.group_id),
      );
      setSearchOpen(false);
      openCreation("group", section?.name, {
        memberIds: [
          group.admin_id,
          ...group.member_ids.filter((id) => id !== group.admin_id),
        ],
        replyMode: group.reply_mode,
      });
    },
    [openCreation, workspace],
  );
  const startPrivateChat = useCallback(
    (id: string, replace = false) => {
      contactRequest.current++;
      setShowList(false);
      setSearchOpen(false);
      navigate(BOT_HOME + "/bots/" + encodeURIComponent(id), {
        replace,
        state: { newChat: true },
      });
    },
    [navigate],
  );
  const jump = (path: string) => {
    contactRequest.current++;
    setShowList(false);
    navigate(path);
  };
  const onBotCreated = async (id: string) => {
    close();
    const choice = newLook ?? { kind: "reset" as const };
    let failure = "";
    try {
      await saveAppearance(id, choice);
    } catch (e) {
      failure = apiErrorMessage(e, t("octopBot.failed"), t);
    }
    setNewLook(null);
    await placeCreated("bot:" + id);
    void refreshAgents({ silent: true, force: true });
    await refresh();
    jump(BOT_HOME + "/bots/" + encodeURIComponent(id));
    if (failure) {
      setError(failure);
      setRetryLook({ id, choice });
    }
  };
  const onGroupSaved = async (group: BotGroup) => {
    close();
    if (dialog === "group") await placeCreated("group:" + group.group_id);
    setWorkspace((prev) =>
      prev
        ? {
            ...prev,
            groups: [
              ...prev.groups.filter((g) => g.group_id !== group.group_id),
              group,
            ],
          }
        : prev,
    );
    jump(BOT_HOME + "/groups/" + encodeURIComponent(group.group_id));
  };
  const setLayout = async (
    layout: Pick<BotLayout, "sections" | "pinned">,
    revision = workspace?.revision ?? 0,
  ) => {
    if (layoutBusy.current) return false;
    layoutBusy.current = true;
    setLayoutSaving(true);
    setLayoutError("");
    failedLayout.current = undefined;
    try {
      const saved = await octopBotApi.saveLayout({ ...layout, revision });
      if (mounted.current)
        setWorkspace((prev) =>
          prev && saved.revision >= (prev.revision ?? 0)
            ? { ...prev, ...saved }
            : prev,
        );
      return true;
    } catch (e) {
      if (mounted.current) {
        // A stale revision is HTTP 409 with this structured error code.
        const conflict = parseApiError(e)?.code === "BOT_LAYOUT_CHANGED";
        if (conflict) {
          await refresh();
          setLayoutError(t("octopBot.sectionUI.conflict"));
        } else {
          failedLayout.current = { ...layout, revision };
          setLayoutError(apiErrorMessage(e, t("octopBot.failed"), t));
        }
      }
      return false;
    } finally {
      layoutBusy.current = false;
      if (mounted.current) setLayoutSaving(false);
    }
  };
  const editSection = (action: SectionAction) => {
    setLayoutError("");
    failedLayout.current = undefined;
    setSectionAction(action);
    setDialog("section");
  };
  const placeCreated = async (key: string) => {
    if (!createIn || !workspace) return;
    if (!workspace.sections.some((s) => s.name === createIn)) {
      setLayoutError(t("octopBot.sectionUI.missing"));
      return;
    }
    await setLayout({
      pinned: workspace.pinned,
      sections: moveEntries(workspace.sections, [key], createIn),
    });
  };
  const shortcut = location.state?.botShortcut;
  useEffect(() => {
    if (!workspace || !shortcut || (!agentId && !groupId && workspace.chief_id))
      return;
    const target = agentId ?? workspace.chief_id ?? workspace.bots[0]?.agent_id;
    const group = workspace.groups.find((g) => g.group_id === groupId);
    if (shortcut === "newChat" && group) {
      navigate(location.pathname, { replace: true, state: null });
      startGroupWithMembers(group);
    } else if (shortcut === "newChat" && target) {
      startPrivateChat(target, true);
    } else {
      navigate(location.pathname, { replace: true, state: null });
      setSearchOpen(shortcut === "search");
    }
  }, [
    shortcut,
    workspace,
    agentId,
    groupId,
    navigate,
    location.pathname,
    startGroupWithMembers,
    startPrivateChat,
  ]);
  const workspaceBots = workspace?.bots;
  const workspaceGroups = workspace?.groups;
  const workspaceSections = workspace?.sections;
  // Stable entries let memoized directory rows skip renders that change nothing for them.
  const all = useMemo<Item[]>(
    () => [
      ...(workspaceBots ?? []).map((bot) => ({
        key: "bot:" + bot.agent_id,
        name: bot.name,
        bot,
      })),
      ...(workspaceGroups ?? []).map((group) => ({
        key: "group:" + group.group_id,
        name: group.name,
        group,
      })),
    ],
    [workspaceBots, workspaceGroups],
  );
  const groupMembers = useMemo(
    () =>
      new Map(
        (workspaceGroups ?? []).map((group) => [
          group.group_id,
          group.member_ids.flatMap((id) =>
            (workspaceBots ?? []).filter((b) => b.agent_id === id),
          ),
        ]),
      ),
    [workspaceBots, workspaceGroups],
  );
  const sectionNames = useMemo(
    () => (workspaceSections ?? []).map((section) => section.name),
    [workspaceSections],
  );
  const itemAction = useRef<(item: Item, key: string) => void>(() => {});
  const onItemAction = useCallback(
    (item: Item, key: string) => itemAction.current(item, key),
    [],
  );
  const itemPick = useRef<(item: Item) => void>(() => {});
  const onItemPick = useCallback((item: Item) => itemPick.current(item), []);
  if (!workspace)
    return (
      <div className={styles.center}>
        {error ? (
          <Alert
            type="error"
            message={error}
            action={
              <Button onClick={() => void refresh()}>
                {t("octopBot.retry")}
              </Button>
            }
          />
        ) : (
          <Spin />
        )}
      </div>
    );
  if (!agentId && !groupId && workspace.chief_id) {
    return (
      <Navigate
        replace
        state={location.state}
        to={BOT_HOME + "/bots/" + encodeURIComponent(workspace.chief_id)}
      />
    );
  }
  const { bots, groups, sections, pinned } = workspace;
  const selectedBot = bots.find((bot) => bot.agent_id === agentId);
  const selectedGroup = groups.find((group) => group.group_id === groupId);
  const teamGroup =
    guideTeam && groups.find((g) => g.group_id === guideTeam.group_id);
  const membersOf = (group: BotGroup) =>
    group.member_ids.flatMap((id) => bots.filter((b) => b.agent_id === id));
  const chiefGuide =
    !selectedBot?.is_main ||
    guide?.status !== "active" ? undefined : guide.step === "ask" ? (
      <OnboardingAsk
        building={motion !== "idle"}
        onRetry={
          guide.choice
            ? () =>
                askChief(
                  teamRequest(
                    guide.choice!.kind,
                    guide.choice!.label,
                    guide.choice!.note,
                  ),
                )
            : undefined
        }
        onSkip={skipOnboarding}
      />
    ) : teamGroup ? (
      <OnboardingTeamReady
        name={teamGroup.name}
        members={membersOf(teamGroup).map((b) => b.name)}
        portraits={<GroupCharacter members={membersOf(teamGroup)} size={30} />}
        onOpen={() =>
          jump(BOT_HOME + "/groups/" + encodeURIComponent(teamGroup.group_id))
        }
        onSkip={skipOnboarding}
      />
    ) : undefined;
  const byKey = new Map(all.map((it) => [it.key, it]));
  const assigned = new Map(
    sections.flatMap((s) => s.items.map((id) => [id, s.name] as const)),
  );
  const collapsedPortraits = (items: Item[]) => {
    const ids = new Set(
      items.flatMap((it) =>
        it.bot ? [it.bot.agent_id] : it.group?.member_ids ?? [],
      ),
    );
    return [...ids].slice(0, 3).flatMap((id) => {
      const it = byKey.get("bot:" + id);
      return it ? [<span key={id}>{portrait(it, 17)}</span>] : [];
    });
  };
  const picked = groupId ? "group:" + groupId : "bot:" + agentId;
  const moveItem = (key: string, destination?: number, reveal = false) => {
    if (layoutSaving || !byKey.has(key) || key === "bot:" + workspace.chief_id)
      return;
    const target =
      destination === undefined ? undefined : sections[destination]?.name;
    if (
      assigned.get(key) === target &&
      !(reveal && destination !== undefined && sections[destination].collapsed)
    )
      return;
    const next = moveEntries(sections, [key], target);
    if (reveal && destination !== undefined)
      next[destination] = { ...next[destination], collapsed: false };
    void setLayout({ pinned, sections: next });
  };
  const onDragOver = (e: React.DragEvent) => {
    if (e.dataTransfer.types.includes(DIRECTORY_DRAG_TYPE)) e.preventDefault();
  };
  const onDrop = (e: React.DragEvent, index?: number) => {
    const key = e.dataTransfer.getData(DIRECTORY_DRAG_TYPE);
    if (key) {
      e.preventDefault();
      setDragging(false);
      moveItem(key, index, true);
    }
  };
  const activity = new Map(agents.map((a) => [a.agent_id, a]));
  const countUnread = (it: Item) => botActivity.unread[it.key] ?? 0;
  const recent = (it: Item) =>
    botActivity.recent[it.key] ??
    (it.bot ? activity.get(it.bot.agent_id)?.last_active ?? 0 : 0);
  const ordered = (items: Item[]) =>
    items.sort(
      (a, b) =>
        Number(pinned.includes(b.key)) - Number(pinned.includes(a.key)) ||
        recent(b) - recent(a),
    );
  const previewFor = (item: Item) => {
    if (item.bot?.preparing) return t("botDirectory.preparing");
    if (previews[item.key]) return previews[item.key];
    if (item.bot?.is_main) return t("botDirectory.coordinator");
    if (item.bot)
      return (
        item.bot.description?.trim() ||
        activity.get(item.bot.agent_id)?.welcome_message?.trim() ||
        t("botDirectory.teammate")
      );
    return (
      botActivity.groupPreview[item.key] ??
      item.group?.member_ids
        .flatMap((id) => bots.find((b) => b.agent_id === id)?.name ?? [])
        .join(" · ") ??
      ""
    );
  };
  const portrait = (item: Item, size: number) =>
    item.bot ? (
      <BotCharacter
        bot={item.bot}
        state={item.bot.agent_id === agentId ? motion : "idle"}
        size={size}
      />
    ) : (
      <GroupCharacter
        members={item.group!.member_ids.flatMap((id) =>
          bots.filter((b) => b.agent_id === id),
        )}
        size={size}
      />
    );
  const pickContact = (item: Item) => {
    const request = ++contactRequest.current;
    setSearchOpen(false);
    setShowList(false);
    if (
      (item.bot && item.bot.agent_id === agentId && threadId) ||
      (item.group && item.group.group_id === groupId)
    )
      return;
    if (item.bot && agentId === item.bot.agent_id && !threadId) {
      void octopThreadsApi
        .list(agentId)
        .then((rows) => {
          const recent = pickPreferredSession(rows.map(toSession));
          if (recent && mounted.current && request === contactRequest.current)
            jump(urlFor(item) + "/" + encodeURIComponent(recent.threadId));
        })
        .catch((e) => {
          if (mounted.current && request === contactRequest.current)
            setError(apiErrorMessage(e, t("octopBot.failed"), t));
        });
      return;
    }
    jump(urlFor(item));
  };
  const chiefKey = "bot:" + workspace.chief_id;
  const backgroundMenu: MenuProps = {
    items: [
      { key: "create", label: t("octopBot.newSection") },
      {
        key: "bulk",
        label: t("octopBot.sectionUI.moveMany"),
        disabled: !sections.length || !all.some((it) => it.key !== chiefKey),
      },
    ],
    onClick: ({ key }) =>
      editSection({ kind: key === "bulk" ? "move" : "create" }),
  };
  const bulkFromChiefDisabled =
    !sections.length || !all.some((it) => it.key !== chiefKey);
  itemAction.current = (item, key) => {
    if (key === "newChat") {
      if (item.bot) startPrivateChat(item.bot.agent_id);
      else if (item.group) startGroupWithMembers(item.group);
      return;
    }
    if (item.key === chiefKey)
      return editSection({ kind: key === "bulk" ? "move" : "create" });
    if (key === "deleteBot" && item.bot) {
      setShowList(false);
      setDeleteTarget(item.bot);
      return;
    }
    if (key === "deleteGroup" && item.group) {
      setShowList(false);
      setDeleteGroupTarget(item.group);
      return;
    }
    if (key === "create") {
      editSection({ kind: "create", entry: item.key });
      return;
    }
    if (key === "bulk") {
      editSection({ kind: "move" });
      return;
    }
    if (key === "pin") {
      void setLayout({
        sections,
        pinned: pinned.includes(item.key)
          ? pinned.filter((id) => id !== item.key)
          : [...pinned, item.key],
      });
      return;
    }
    moveItem(item.key, key === "none" ? undefined : Number(key.slice(1)));
  };
  itemPick.current = (item) =>
    standalone ? pickContact(item) : jump(urlFor(item));
  const freshContacts = new Set(
    guideTeam
      ? [
          "group:" + guideTeam.group_id,
          ...guideTeam.bot_ids.map((id) => "bot:" + id),
        ].filter((key) => !openedContacts.includes(key))
      : [],
  );
  const renderItem = (item: Item) => {
    const chief = item.key === chiefKey;
    const row = (
      <DirectoryItem
        key={item.key}
        item={item}
        chief={chief}
        fresh={freshContacts.has(item.key)}
        pinned={pinned.includes(item.key)}
        selected={picked === item.key}
        compact={compactDirectory}
        standalone={standalone}
        disabled={layoutSaving}
        unread={countUnread(item)}
        waiting={Boolean(item.bot && waitingBots.has(item.bot.agent_id))}
        subtitle={
          item.bot && waitingBots.has(item.bot.agent_id)
            ? t("botInbox.needsYou")
            : chief
            ? t("botDirectory.chiefRole")
            : previewFor(item)
        }
        motion={item.bot && item.bot.agent_id === agentId ? motion : "idle"}
        members={item.group && groupMembers.get(item.group.group_id)}
        sectionNames={sectionNames}
        assignedTo={assigned.get(item.key)}
        bulkDisabled={chief ? bulkFromChiefDisabled : !sections.length}
        menuEvents={directoryMenu.events}
        overflowProps={directoryMenu.overflowProps}
        onAction={onItemAction}
        onPick={onItemPick}
        onDragging={setDragging}
      />
    );
    // Point at the group Chief just built, next to the sidebar.
    return guide?.step === "team_ready" &&
      guideTeam &&
      item.group?.group_id === guideTeam.group_id &&
      !mobile &&
      !compactDirectory ? (
      <Popover
        key={item.key}
        open
        placement="right"
        content={<OnboardingCoach onOpen={() => jump(urlFor(item))} />}
      >
        <div>{row}</div>
      </Popover>
    ) : (
      row
    );
  };
  const renderSection = (
    name: string,
    items: Item[],
    options?: { section: BotSection; index: number },
  ) =>
    (items.length > 0 || (options && !compactDirectory)) && (
      <section
        className={styles.section}
        data-section-name={options?.section.name}
        aria-label={compactDirectory ? name : undefined}
        ref={(node) => {
          if (!options) return;
          if (node) sectionNodes.current.set(name, node);
          else sectionNodes.current.delete(name);
        }}
        key={options ? "section:" + name : "default:" + name}
        onDragOver={onDragOver}
        onDrop={(e) => onDrop(e, options?.index)}
      >
        {compactDirectory ? null : options ? (
          <SectionHeader
            section={options.section}
            count={items.length}
            unread={items.reduce((n, it) => n + countUnread(it), 0)}
            first={options.index === 0}
            last={options.index === sections.length - 1}
            disabled={layoutSaving}
            menuEvents={directoryMenu.events}
            overflow={directoryMenu.overflowProps("section:" + name)}
            portraits={
              standalone && options.section.collapsed
                ? collapsedPortraits(items)
                : undefined
            }
            onManage={() => editSection({ kind: "edit", name })}
            onNewBot={
              navAllowed(user, "experts")
                ? () => openCreation("bot", name)
                : undefined
            }
            onNewGroup={() => openCreation("group", name)}
            onStartGroup={
              items.some((it) => it.bot && canInviteBot(it.bot))
                ? () =>
                    openCreation("group", name, {
                      name,
                      memberIds: items.flatMap((it) =>
                        it.bot && canInviteBot(it.bot) ? [it.bot.agent_id] : [],
                      ),
                    })
                : undefined
            }
            onEdit={(patch) =>
              void setLayout({
                pinned,
                sections: sections.map((s, i) =>
                  i === options.index ? { ...s, ...patch } : s,
                ),
              })
            }
            onRename={() =>
              editSection({ kind: "edit", name, focusName: true })
            }
            onMove={(direction) => {
              const next = [...sections];
              const dest = options.index + direction;
              [next[options.index], next[dest]] = [
                next[dest],
                next[options.index],
              ];
              void setLayout({ pinned, sections: next });
            }}
            onRemove={() =>
              void setLayout({
                pinned,
                sections: sections.filter((_, i) => i !== options.index),
              })
            }
          />
        ) : standalone ? (
          <h3 className={directory.contactHeading}>
            <span>{name}</span>
            <span>{items.length}</span>
          </h3>
        ) : (
          <h3>{name}</h3>
        )}
        {(compactDirectory || !options?.section.collapsed) &&
          ordered(items).map(renderItem)}
        {options && !options.section.collapsed && items.length === 0 && (
          <Button
            type="text"
            size="small"
            className={sectionStyles.empty}
            disabled={layoutSaving}
            onClick={() => editSection({ kind: "edit", name })}
          >
            {t("octopBot.sectionUI.addEntries")}
          </Button>
        )}
      </section>
    );
  const layoutAlert = layoutError && dialog !== "section" && (
    <Alert
      type="error"
      message={layoutError}
      showIcon
      closable
      onClose={() => setLayoutError("")}
      action={
        failedLayout.current && (
          <Button
            size="small"
            disabled={layoutSaving}
            onClick={() => {
              const failed = failedLayout.current;
              if (failed && failed.revision === (workspace.revision ?? 0))
                void setLayout(failed, failed.revision);
              else {
                failedLayout.current = undefined;
                setLayoutError(t("octopBot.sectionUI.conflict"));
              }
            }}
          >
            {t("octopBot.retry")}
          </Button>
        )
      }
    />
  );
  const toggleLabel = t(
    compactDirectory ? "botDirectory.expand" : "botDirectory.collapse",
  );
  const unreadTarget = compactDirectory
    ? all.find((item) => item.key !== picked && countUnread(item) > 0)
    : undefined;
  const sidebar = (
    <nav
      className={standalone ? directory.directory : styles.nav}
      data-collapsed={compactDirectory || undefined}
      aria-label={t("nav.octopBot")}
    >
      <div className={standalone ? directory.navHeader : styles.navHeader}>
        {standalone ? (
          <BotCharacter
            look={{ ...octopCharacter, source: "character" }}
            size={23}
            badges={false}
          />
        ) : (
          <Bot size={19} />
        )}
        <strong>{t("nav.octopBot")}</strong>
        {unreadTarget && (
          <button
            type="button"
            className={directory.unreadJump}
            title={t("chat.unreadMessages") + " · " + unreadTarget.name}
            aria-label={t("chat.unreadMessages") + " · " + unreadTarget.name}
            onClick={() => pickContact(unreadTarget)}
          >
            <ArrowDown size={15} />
          </button>
        )}
        {standalone && (
          <button
            className={directory.directoryToggle}
            type="button"
            title={toggleLabel}
            aria-label={toggleLabel}
            aria-expanded={!compactDirectory}
            aria-controls="octop-bot-contacts"
            onClick={mobile ? () => setShowList(false) : toggle}
          >
            {compactDirectory ? (
              <PanelLeftOpen size={16} />
            ) : (
              <PanelLeftClose size={16} />
            )}
          </button>
        )}
        {standalone && (
          <Button
            type="text"
            className={directory.iconButton}
            title={t("botDirectory.find") + " (Ctrl / ⌘ K)"}
            aria-label={t("botDirectory.find")}
            icon={<Search size={16} />}
            onClick={() => setSearchOpen(true)}
          />
        )}
        {standalone && navAllowed(user, "experts") && (
          <Button
            type="text"
            className={directory.iconButton}
            title={t("botMarket.entry")}
            aria-label={t("botMarket.entry")}
            icon={<Store size={16} />}
            onClick={openMarket}
          />
        )}
        <Dropdown
          trigger={["click"]}
          {...directoryMenu.overflowProps("add")}
          menu={{
            items: [
              ...(standalone
                ? [
                    {
                      key: "newChat",
                      label: t(
                        selectedGroup
                          ? "botDirectory.newGroupWithMembers"
                          : "botDirectory.newPrivateChat",
                      ),
                      disabled:
                        !selectedGroup && !selectedBot && !workspace.chief_id,
                    },
                  ]
                : []),
              ...(navAllowed(user, "experts")
                ? [
                    { key: "bot", label: t("octopBot.newBot") },
                    ...(!standalone
                      ? [{ key: "managed", label: t("octopBot.newManaged") }]
                      : [{ key: "market", label: t("botMarket.menuEntry") }]),
                  ]
                : []),
              { key: "group", label: t("octopBot.newGroup") },
            ],
            onClick: ({ key }) => {
              if (key === "market") {
                openMarket();
              } else if (key === "newChat") {
                if (selectedGroup) startGroupWithMembers(selectedGroup);
                else
                  startPrivateChat(
                    selectedBot?.agent_id ?? workspace.chief_id!,
                  );
              } else {
                openCreation(key as "bot" | "managed" | "group");
              }
            },
          }}
        >
          <Button
            type="text"
            size="small"
            className={standalone ? directory.iconButton : undefined}
            aria-label={t("octopBot.add")}
            title={t("octopBot.add")}
            icon={<Plus size={17} />}
          />
        </Dropdown>
      </div>
      <div
        className={standalone ? directory.contacts : styles.railList}
        id="octop-bot-contacts"
        role="group"
        aria-label={t("botDirectory.teamTab")}
        tabIndex={0}
        {...(layoutSaving ? {} : directoryMenu.events(backgroundMenu, true))}
        {...(layoutSaving ? {} : directoryMenu.touchBackground(backgroundMenu))}
      >
        {all.filter((it) => it.key === chiefKey).map(renderItem)}
        {dragging && sections.length > 0 && (
          <div
            className={sectionStyles.drop}
            onDragOver={onDragOver}
            onDrop={(e) => onDrop(e)}
          >
            {t("octopBot.sectionUI.dropUngrouped")}
          </div>
        )}
        {!compactDirectory && (!mobile || showList) && layoutAlert}

        {standalone ? (
          <>
            {renderSection(
              t("octopBot.pinned"),
              all.filter(
                (it) =>
                  it.key !== chiefKey &&
                  pinned.includes(it.key) &&
                  !assigned.has(it.key),
              ),
            )}
            {renderSection(
              t("octopBot.groups"),
              all.filter(
                (it) =>
                  it.group && !pinned.includes(it.key) && !assigned.has(it.key),
              ),
            )}
            {renderSection(
              t("botDirectory.people"),
              all.filter(
                (it) =>
                  it.bot &&
                  it.key !== chiefKey &&
                  !pinned.includes(it.key) &&
                  !assigned.has(it.key),
              ),
            )}
            {!compactDirectory &&
              all.length === 1 &&
              navAllowed(user, "experts") && (
                <Button
                  className={directory.firstMember}
                  type="dashed"
                  block
                  icon={<Plus size={15} />}
                  onClick={() => {
                    openCreation("bot");
                  }}
                >
                  {t("botDirectory.addFirst")}
                </Button>
              )}
            {!compactDirectory &&
              all.length === 1 &&
              navAllowed(user, "experts") && (
                <Button
                  className={directory.firstMember}
                  type="text"
                  block
                  icon={<Store size={15} />}
                  onClick={openMarket}
                >
                  {t("botMarket.browse")}
                </Button>
              )}
          </>
        ) : (
          <>
            {renderSection(
              t("octopBot.bots"),
              all.filter(
                (it) => it.bot && it.key !== chiefKey && !assigned.has(it.key),
              ),
            )}
            {renderSection(
              t("octopBot.groups"),
              all.filter((it) => it.group && !assigned.has(it.key)),
            )}
          </>
        )}
        {sections.map((s, index) =>
          renderSection(
            s.name,
            s.items.flatMap((key) => {
              const item = byKey.get(key);
              return item && key !== chiefKey ? [item] : [];
            }),
            { section: s, index },
          ),
        )}
        {standalone && !compactDirectory && (
          <MoreUnreads watch={botActivity.unread} />
        )}
      </div>
      {standalone ? (
        <div
          className={
            compactDirectory ? directory.railFooter : sectionStyles.footer
          }
        >
          <AccountMenu compact={compactDirectory} />
          <CloudMove />
        </div>
      ) : (
        <>
          <Button
            type="text"
            className={styles.newGroup}
            onClick={() => setDialog("retained")}
          >
            {t("octopBot.retainedFolders")}
          </Button>
          <Button
            type="text"
            className={styles.newGroup}
            icon={<Users size={15} />}
            onClick={() => setDialog("group")}
          >
            {t("octopBot.newGroup")}
          </Button>
        </>
      )}
    </nav>
  );
  const listButton = mobile ? () => setShowList(true) : undefined;
  const selectedItem = all.find((it) => it.key === picked);
  const title =
    standalone && selectedItem ? (
      <>
        {portrait(selectedItem, 22)}
        <strong>{selectedItem.name}</strong>
      </>
    ) : (
      <div className={styles.title}>
        {mobile && (
          <Button
            type="text"
            aria-label={t("octopBot.switchChat")}
            icon={<Menu size={18} />}
            onClick={() => setShowList(true)}
          />
        )}
        {selectedGroup ? (
          <GroupCharacter
            members={selectedGroup.member_ids.flatMap((id) =>
              bots.filter((b) => b.agent_id === id),
            )}
            size={33}
          />
        ) : (
          <BotCharacter bot={selectedBot} state={motion} size={34} />
        )}
        <div>
          <h2>{selectedGroup?.name ?? selectedBot?.name}</h2>
          {selectedGroup ? (
            <small>
              {t("octopBot.memberCount", {
                count: selectedGroup.member_ids.length,
              })}
            </small>
          ) : !standalone && selectedBot?.description ? (
            <small>{selectedBot.description}</small>
          ) : null}
        </div>
      </div>
    );
  return (
    <div className={standalone ? directory.shell : styles.shell}>
      {mobile ? (
        <Drawer
          open={showList}
          title={null}
          closable={false}
          placement="left"
          width={standalone ? 244 : 270}
          onClose={() => setShowList(false)}
          styles={{ body: { padding: 0 } }}
        >
          {sidebar}
        </Drawer>
      ) : (
        sidebar
      )}
      {directoryMenu.popup}
      {standalone && searchOpen && (
        <DirectorySearch
          items={all.map((it) => ({
            key: it.key,
            name: it.name,
            preview: previewFor(it),
            keywords: [
              assigned.get(it.key),
              it.bot
                ? [it.bot.agent_id, it.bot.description].join(" ")
                : it.group?.member_ids
                    .map((id) => activity.get(id)?.name ?? id)
                    .join(" "),
            ].join(" "),
            portrait: portrait(it, 30),
          }))}
          onClose={() => setSearchOpen(false)}
          onThread={(hit) => {
            setSearchOpen(false);
            jump(
              BOT_HOME +
                "/bots/" +
                encodeURIComponent(hit.agent_id) +
                "/" +
                encodeURIComponent(hit.thread_id),
            );
          }}
          onPick={(key) => {
            const item = all.find((it) => it.key === key);
            if (item) pickContact(item);
          }}
        />
      )}
      <main className={standalone ? directory.main : styles.main}>
        {((mobile && !showList) || compactDirectory) && layoutAlert}
        {mobile && standalone && !selectedItem && (
          <Button onClick={listButton}>{t("botDirectory.expand")}</Button>
        )}
        {error && (
          <Alert
            type="error"
            message={error}
            closable
            onClose={() => setError("")}
          />
        )}
        {selectedBot ? (
          <BotChat
            bot={selectedBot}
            motion={motion}
            roster={bots}
            threadId={threadId}
            title={title}
            onOpenList={listButton}
            inGroup={groups.some((g) =>
              g.member_ids.includes(selectedBot.agent_id),
            )}
            onChanged={() => void refresh()}
            onDelete={() => setDeleteTarget(selectedBot)}
            composerTop={chiefGuide}
          />
        ) : selectedGroup ? (
          <>
            {!standalone && (
              <header className={styles.header}>
                {title}
                <Button
                  type="text"
                  icon={<Settings2 size={17} />}
                  aria-label={t("octopBot.groupSettings")}
                  onClick={() => setDialog("editGroup")}
                />
              </header>
            )}
            <GroupRoom
              key={selectedGroup.group_id}
              group={selectedGroup}
              bots={bots}
              title={standalone ? title : undefined}
              onOpenList={listButton}
              onOpenSettings={() => setDialog("editGroup")}
              onNewGroup={() => startGroupWithMembers(selectedGroup)}
              onMember={(id) =>
                jump(BOT_HOME + "/bots/" + encodeURIComponent(id))
              }
              onPreview={rememberPreview}
              {...(guideTeam?.group_id === selectedGroup.group_id && {
                guide: (
                  <OnboardingStrip
                    wide
                    step={3}
                    title={t("botOnboarding.guide.groupTitle")}
                    hint={t("botOnboarding.guide.groupHint")}
                    onSkip={skipOnboarding}
                  />
                ),
                onSent: () => {
                  void changeOnboarding({ action: "complete" });
                  void message.success({
                    content: t("botOnboarding.guide.done"),
                    duration: 6,
                  });
                },
              })}
            />
          </>
        ) : (
          <div className={styles.center}>
            <Empty
              className={styles.illustratedEmpty}
              image={<img src={offlineArt} alt="" />}
              description={t("octopBot.unavailable")}
            >
              <Button onClick={() => jump(BOT_HOME)}>
                {t("nav.octopBot")}
              </Button>
            </Empty>
          </div>
        )}
      </main>
      {guide &&
        selectedBot?.is_main &&
        (guide.status === "pending" || guide.step === "welcome") && (
          <OnboardingWelcome
            busy={onboardingBusy}
            onStart={({ label, ...pick }) => {
              setOnboardingBusy(true);
              void changeOnboarding({ action: "start", ...pick })
                .then(() => askChief(teamRequest(pick.kind, label, pick.note)))
                .finally(() => setOnboardingBusy(false));
            }}
            onSkip={skipOnboarding}
          />
        )}
      {(dialog === "group" || (dialog === "editGroup" && selectedGroup)) && (
        <GroupForm
          bots={bots}
          chiefId={workspace.chief_id}
          seed={dialog === "group" ? groupSeed : undefined}
          group={dialog === "editGroup" ? selectedGroup : undefined}
          onClose={close}
          onSaved={onGroupSaved}
        />
      )}
      {dialog === "bot" && standalone && (
        <BotQuickCreate
          choice={newLook}
          onChoose={setNewLook}
          onClose={close}
          onCreated={onBotCreated}
          onBrowseMarket={() => {
            close();
            openMarket();
          }}
        />
      )}
      {dialog === "bot" && !standalone && (
        <ExpertCreateDrawer
          open
          onClose={close}
          onCreated={onBotCreated}
          avatarEditor={
            <AppearancePicker value={newLook} onChange={setNewLook} />
          }
        />
      )}
      {dialog === "managed" && (
        <ManagedDrawer
          open
          onClose={close}
          onCreated={onBotCreated}
          avatarEditor={
            <AppearancePicker value={newLook} onChange={setNewLook} />
          }
        />
      )}
      {retryLook && selectedBot?.agent_id === retryLook.id && (
        <AppearanceModal
          bot={selectedBot}
          initial={retryLook.choice}
          onClose={() => setRetryLook(null)}
          onSaved={() => {
            setRetryLook(null);
            void refresh();
          }}
        />
      )}
      {dialog === "retained" && <RetainedFolders onClose={close} />}
      {deleteTarget && (
        <DeleteBotDialog
          bot={deleteTarget}
          groups={groups}
          onClose={() => setDeleteTarget(null)}
          onDeleted={() => {
            setDeleteTarget(null);
            if (deleteTarget.agent_id === agentId) {
              jump(
                BOT_HOME + "/bots/" + encodeURIComponent(workspace.chief_id),
              );
            }
            setWorkspace(
              (current) =>
                current && {
                  ...current,
                  bots: current.bots.filter(
                    (bot) => bot.agent_id !== deleteTarget.agent_id,
                  ),
                },
            );
            if (deleteTarget.is_private) setDialog("retained");
            void refreshAgents({ silent: true, force: true });
            void refresh();
          }}
        />
      )}
      {deleteGroupTarget && (
        <DeleteGroupDialog
          group={deleteGroupTarget}
          onClose={() => setDeleteGroupTarget(null)}
          onDeleted={() => {
            setDeleteGroupTarget(null);
            if (deleteGroupTarget.group_id === groupId) {
              jump(
                BOT_HOME + "/bots/" + encodeURIComponent(workspace.chief_id),
              );
            }
            setWorkspace(
              (current) =>
                current && {
                  ...current,
                  groups: current.groups.filter(
                    (group) => group.group_id !== deleteGroupTarget.group_id,
                  ),
                },
            );
            void refresh();
          }}
        />
      )}
      {dialog === "section" && (
        <SectionEditor
          action={sectionAction}
          sections={sections}
          contacts={all
            .filter((it) => it.key !== chiefKey)
            .map((it) => ({
              key: it.key,
              name: it.name,
              detail: it.bot
                ? it.bot.description?.trim() || it.bot.agent_id
                : t("octopBot.sectionUI.groupChat"),
              avatar: portrait(it, 26),
            }))}
          saving={layoutSaving}
          error={layoutError}
          onSave={async (next, reveal) => {
            const saved = await setLayout({ sections: next, pinned });
            if (saved) revealSection.current = reveal;
            return saved;
          }}
          onClose={() => {
            setLayoutError("");
            failedLayout.current = undefined;
            close();
          }}
        />
      )}
    </div>
  );
}
