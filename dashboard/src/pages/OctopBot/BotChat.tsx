import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Button,
  Drawer,
  Dropdown,
  Empty,
  Input,
  List,
  Space,
  Spin,
  Switch,
} from "antd";
import type { TextAreaRef } from "antd/es/input/TextArea";
import { History, MessagesSquare, Settings2, Shield } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  octopBotApi,
  type SideMessage,
  type WorkspaceBot,
} from "../../api/modules/octopBot";
import {
  octopThreadsApi,
  type OctopThread,
} from "../../api/modules/octopThreads";
import { useAgent } from "../../context/AgentContext";
import { useCurrentUser } from "../../hooks/useCurrentUser";
import { isBotClient } from "../../utils/desktopBridge";
import { BOT_HOME } from "../../utils/botClientRoute";
import { canAccessPath } from "../../utils/permissions";
import LazyMarkdown from "../../components/Markdown/LazyMarkdown";
import { apiErrorMessage } from "../../utils/apiError";
import EditAgentDrawer from "../Experts/components/EditAgentDrawer";
import ChatPage from "../Chat";
import { ChatRouteContext } from "../Chat/ChatRouteContext";
import ShareConversationDialog from "../Chat/components/ShareConversationDialog";
import { publicShareAvailable } from "../Chat/utils/publicShareHost";
import styles from "./index.module.less";
import ReferenceDialog from "./ReferenceDialog";
import { LowCreditsBanner } from "./CreditsWidgets";
import GroupMemory from "./GroupMemory";
import BotComputerSettings from "./BotComputerSettings";
import AppearanceModal from "./AppearancePicker";
import { BotCharacter, type BotMotion } from "./BotCharacter";
import RoomIdentity from "./RoomIdentity";
import BotDetailsPanel from "./BotDetailsPanel";
import CloudComputerFloat, { CloudComputerToggle } from "./CloudComputerFloat";
import { useBotServerInfo } from "./useBotServerInfo";
import directory from "./directory.module.less";

function ThreadHistory({
  agentId,
  onClose,
}: {
  agentId: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [rows, setRows] = useState<OctopThread[]>([]);
  const [limit, setLimit] = useState(30);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let current = true;
    setLoading(true);
    setError("");
    void octopThreadsApi
      .list(agentId, limit + 1, { includeBotGroups: true })
      .then((result) => {
        if (current) setRows(result);
      })
      .catch((e) => {
        if (current) setError(apiErrorMessage(e, t("octopBot.failed"), t));
      })
      .finally(() => {
        if (current) setLoading(false);
      });
    return () => {
      current = false;
    };
  }, [agentId, limit, t, attempt]);
  return (
    <Drawer open onClose={onClose} title={t("octopBot.history")}>
      <p>{t("botDirectory.privateHistoryHelp")}</p>
      {error && (
        <Alert
          type="error"
          message={error}
          action={
            <Button
              size="small"
              loading={loading}
              onClick={() => setAttempt((n) => n + 1)}
            >
              {t("octopBot.retry")}
            </Button>
          }
        />
      )}
      <List
        loading={loading}
        dataSource={rows.slice(0, limit)}
        renderItem={(row) => (
          <List.Item>
            <Button
              className={styles.historyItem}
              type="text"
              onClick={() => {
                navigate(
                  BOT_HOME +
                    "/bots/" +
                    encodeURIComponent(agentId) +
                    "/" +
                    encodeURIComponent(row.thread_id),
                );
                onClose();
              }}
            >
              {row.title || t("chatWelcome.newChat")}
            </Button>
          </List.Item>
        )}
      />
      {rows.length > limit && (
        <Button
          loading={loading}
          onClick={() => setLimit((value) => value + 30)}
        >
          {t("octopBot.more")}
        </Button>
      )}
    </Drawer>
  );
}

interface SideTurn {
  question: string;
  answer?: string;
  error?: string;
}
export default function BotChat({
  bot,
  roster,
  threadId,
  title,
  motion,
  onOpenList,
  inGroup,
  onChanged,
  onDelete,
}: {
  bot: WorkspaceBot;
  roster: WorkspaceBot[];
  threadId?: string;
  title: React.ReactNode;
  motion?: BotMotion;
  onOpenList?: () => void;
  inGroup: boolean;
  onChanged: () => void;
  onDelete: () => void;
}) {
  const { t } = useTranslation();
  const { agents, refresh } = useAgent();
  const user = useCurrentUser();
  const navigate = useNavigate();
  const [details, setDetails] = useState(false);
  const [sharing, setSharing] = useState(false);
  useEffect(() => setDetails(false), [bot.agent_id]);
  const [panel, setPanel] = useState<
    | "side"
    | "appearance"
    | "history"
    | "settings"
    | "reference"
    | "teamMemory"
    | "privacy"
    | null
  >(null);
  const [privacyError, setPrivacyError] = useState("");
  const [editingAppearance, setEditingAppearance] = useState(false);
  const [privacySaving, setPrivacySaving] = useState(false);
  const [draft, setDraft] = useState("");
  const [turns, setTurns] = useState<SideTurn[]>([]);
  const [busy, setBusy] = useState(false);
  const stamp = useRef(0);
  const sideInput = useRef<TextAreaRef>(null);
  const snapshot = useRef<number>();
  const insertReference = useRef<(text: string) => void>();
  // Side answers remain scoped to the thread whose snapshot was used.
  useEffect(() => {
    const generation = ++stamp.current;
    setPanel(null);
    setEditingAppearance(false);
    setDraft("");
    setTurns([]);
    setBusy(false);
    snapshot.current = undefined;
    insertReference.current = undefined;
    return () => {
      stamp.current = generation + 1;
    };
  }, [bot.agent_id, threadId]);
  const ask = useCallback(
    async (question: string) => {
      if (!threadId || !question.trim() || busy) return;
      const text = question.trim(),
        generation = stamp.current;
      setBusy(true);
      setDraft("");
      setTurns((prev) => [...prev, { question: text }]);
      let completed: SideTurn;
      try {
        const previous: SideMessage[] = turns
          .filter((turn) => turn.answer)
          .slice(-6)
          .flatMap((turn) => [
            { role: "user" as const, text: turn.question },
            { role: "assistant" as const, text: turn.answer! },
          ]);
        const { answer, snapshot_seq } = await octopBotApi.side(
          bot.agent_id,
          threadId,
          text,
          snapshot.current,
          previous,
        );
        if (stamp.current === generation) snapshot.current = snapshot_seq;
        completed = { question: text, answer };
      } catch (e) {
        completed = {
          question: text,
          error: apiErrorMessage(e, t("octopBot.failed"), t),
        };
      }
      if (stamp.current === generation) {
        setTurns((prev) => [...prev.slice(0, -1), completed]);
        setBusy(false);
      }
    },
    [bot.agent_id, threadId, busy, t, turns],
  );
  const openSide = useCallback(
    (question: string) => {
      setPanel("side");
      if (question && threadId && !busy) void ask(question);
      else if (question) setDraft(question);
    },
    [ask, threadId, busy],
  );
  const openReference = useCallback((insert: (text: string) => void) => {
    insertReference.current = insert;
    setPanel("reference");
  }, []);
  const host = useMemo(
    () => ({
      basePath: BOT_HOME + "/bots",
      recipient: { id: bot.agent_id, name: bot.name },
      isChief: bot.is_main,
      openSide,
      openReference,
      renderAvatar: (
        id: string | null | undefined,
        size: number,
        working: boolean,
      ) => {
        const sender = id ? roster.find((b) => b.agent_id === id) : bot;
        return sender ? (
          <BotCharacter
            bot={sender}
            size={size}
            state={
              working
                ? sender.agent_id === bot.agent_id &&
                  motion &&
                  motion !== "idle"
                  ? motion
                  : "working"
                : "idle"
            }
          />
        ) : null;
      },
    }),
    [openSide, openReference, bot, roster, motion],
  );
  const standalone = isBotClient();
  const agent = agents.find((a) => a.agent_id === bot.agent_id);
  // Octop Bot cloud: a floating live screen while the Bot works on its cloud computer.
  const serverInfo = useBotServerInfo();
  const capabilityLinks = [
    ["/personalization/memory", "nav.memory"],
    ["/workbench/browser", "chat.openBrowser"],
    ["/remote-desktop/desktop", "nav.remoteDesktop"],
    ["/personalization/channels", "nav.channels"],
    ["/connectors", "nav.connectors"],
    ["/skill-packages", "nav.skillPackages"],
    ["/acp", "nav.acp"],
    ["/tasks", "nav.tasks"],
    ["/token-usage", "nav.tokenUsage"],
  ].filter(([path]) => canAccessPath(user, path));
  return (
    <>
      <div
        className={standalone ? directory.chatLayout : directory.transparent}
      >
        <div className={standalone ? directory.column : directory.transparent}>
          {standalone ? (
            <RoomIdentity
              actions={
                <>
                  {serverInfo?.capabilities.cloud_computer &&
                    agent &&
                    !agent.is_shared && (
                      <CloudComputerToggle
                        key={bot.agent_id}
                        botId={bot.agent_id}
                      />
                    )}
                  {threadId && publicShareAvailable() ? (
                    <button
                      type="button"
                      className={directory.roomPill}
                      onClick={() => setSharing(true)}
                    >
                      {t("octopBot.share")}
                    </button>
                  ) : null}
                </>
              }
              expanded={details}
              onToggle={() => setDetails((v) => !v)}
              onList={onOpenList}
            >
              {title}
            </RoomIdentity>
          ) : (
            <header className={styles.header}>
              {title}
              <Space size={2}>
                {!standalone &&
                  agent?.kind === "expert" &&
                  !agent.is_shared &&
                  canAccessPath(user, "/remote-desktop/desktop") && (
                    <BotComputerSettings
                      key={bot.agent_id}
                      botId={bot.agent_id}
                    />
                  )}
                {serverInfo?.capabilities.cloud_computer &&
                  agent &&
                  !agent.is_shared && (
                    <CloudComputerToggle
                      key={bot.agent_id}
                      botId={bot.agent_id}
                    />
                  )}
                <Button
                  type="text"
                  title={t("octopBot.history")}
                  aria-label={t("octopBot.history")}
                  icon={<History size={17} />}
                  onClick={() => setPanel("history")}
                />
                <Button
                  type="text"
                  title={t("octopBot.side")}
                  aria-label={t("octopBot.side")}
                  icon={<MessagesSquare size={17} />}
                  onClick={() => openSide("")}
                />
                <Dropdown
                  trigger={["click"]}
                  menu={{
                    items: [
                      { key: "appearance", label: t("octopBot.avatar.title") },
                      ...(!standalone
                        ? [
                            {
                              key: "edit",
                              label: t("octopBot.botSettings"),
                              disabled: !agent,
                            },
                            { key: "privacy", label: t("octopBot.privacy") },
                            { key: "team", label: t("octopBot.teamMemory") },
                            {
                              key: "capabilities",
                              label: t("octopBot.capabilities"),
                              children: capabilityLinks.map(
                                ([path, label]) => ({
                                  key: path,
                                  label: t(label),
                                }),
                              ),
                            },
                          ]
                        : []),
                    ],
                    onClick: ({ key }) => {
                      if (key === "edit") setPanel("settings");
                      else if (key === "appearance") setPanel("appearance");
                      else if (key === "privacy") {
                        setPrivacyError("");
                        setPanel("privacy");
                      } else if (key === "team") setPanel("teamMemory");
                      else
                        navigate(
                          key === "/workbench/browser"
                            ? key +
                                "?bot_id=" +
                                encodeURIComponent(bot.agent_id)
                            : key,
                        );
                    },
                  }}
                >
                  <Button
                    type="text"
                    title={t("octopBot.botSettings")}
                    aria-label={t("octopBot.botSettings")}
                    icon={<Settings2 size={17} />}
                  />
                </Dropdown>
              </Space>
            </header>
          )}
          <LowCreditsBanner />
          <div className={styles.chat}>
            <ChatRouteContext.Provider value={host}>
              <ChatPage />
            </ChatRouteContext.Provider>
          </div>
          {serverInfo?.capabilities.cloud_computer &&
            agent &&
            !agent.is_shared && (
              <CloudComputerFloat
                key={bot.agent_id}
                botId={bot.agent_id}
                botName={bot.name}
              />
            )}
        </div>
        {standalone && details && (
          <BotDetailsPanel
            key={bot.agent_id}
            bot={bot}
            motion={motion}
            onClose={() => setDetails(false)}
            onHistory={() => setPanel("history")}
            onSide={() => openSide("")}
            onAppearance={() => setPanel("appearance")}
            onEdit={() => setPanel("settings")}
            onDelete={onDelete}
            onMemory={() => setPanel("teamMemory")}
            onPrivacy={() => {
              setPrivacyError("");
              setPanel("privacy");
            }}
          />
        )}
      </div>
      {sharing && threadId && (
        <ShareConversationDialog
          open
          agentId={bot.agent_id}
          threadId={threadId}
          onClose={() => setSharing(false)}
        />
      )}
      {panel === "history" && (
        <ThreadHistory agentId={bot.agent_id} onClose={() => setPanel(null)} />
      )}
      {panel === "appearance" && (
        <AppearanceModal
          bot={bot}
          onClose={() => setPanel(null)}
          onSaved={() => {
            setPanel(null);
            onChanged();
          }}
        />
      )}
      {panel === "reference" && (
        <ReferenceDialog
          onClose={() => setPanel(null)}
          onPick={(value) => insertReference.current?.(value)}
        />
      )}
      {panel === "teamMemory" && <GroupMemory onClose={() => setPanel(null)} />}
      {panel === "privacy" && (
        <Drawer
          open
          title={t("octopBot.privacy")}
          onClose={() => setPanel(null)}
        >
          <Space>
            <Shield size={17} />
            <strong>{t("octopBot.privacy")}</strong>
            <Switch
              checked={bot.is_private}
              loading={privacySaving}
              disabled={
                !bot.is_private &&
                (!agent ||
                  agent.is_shared ||
                  agent.kind === "managed" ||
                  bot.is_main ||
                  inGroup)
              }
              onChange={async (value) => {
                setPrivacyError("");
                setPrivacySaving(true);
                try {
                  await octopBotApi.privacy(bot.agent_id, value);
                  onChanged();
                  setPanel(null);
                } catch (e) {
                  setPrivacyError(apiErrorMessage(e, t("octopBot.failed"), t));
                } finally {
                  setPrivacySaving(false);
                }
              }}
            />
          </Space>
          <p>{t("octopBot.privacyHelp")}</p>
          {privacyError && <Alert type="error" message={privacyError} />}
        </Drawer>
      )}
      {panel === "settings" && (
        <EditAgentDrawer
          avatarEditor={
            <Button
              type="text"
              onClick={() => setEditingAppearance(true)}
              icon={<BotCharacter bot={bot} size={28} />}
            >
              {t("octopBot.avatar.title")}
            </Button>
          }
          open
          agent={agent ?? null}
          onClose={() => setPanel(null)}
          onSaved={() => {
            setPanel(null);
            void refresh({ silent: true, force: true });
            onChanged();
          }}
        />
      )}
      {editingAppearance && panel === "settings" && (
        <AppearanceModal
          bot={bot}
          onClose={() => setEditingAppearance(false)}
          onSaved={() => {
            setEditingAppearance(false);
            onChanged();
          }}
        />
      )}
      {panel === "side" && (
        <Drawer
          open
          title={t("octopBot.side")}
          onClose={() => setPanel(null)}
          width={420}
          mask={false}
        >
          {!threadId && (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={t("octopBot.sideNeedsThread")}
            />
          )}
          {turns.map((turn, index) => (
            <div key={index} className={styles.sideTurn}>
              <strong>{turn.question}</strong>
              {turn.error ? (
                <Alert
                  type="error"
                  message={turn.error}
                  action={
                    threadId && (
                      <Button
                        size="small"
                        disabled={busy}
                        onClick={() => {
                          setTurns((prev) => prev.filter((it) => it !== turn));
                          void ask(turn.question);
                        }}
                      >
                        {t("octopBot.retry")}
                      </Button>
                    )
                  }
                />
              ) : turn.answer ? (
                <LazyMarkdown content={turn.answer} />
              ) : (
                <Spin size="small" />
              )}
            </div>
          ))}
          {threadId && (
            <>
              <Input.TextArea
                ref={sideInput}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                placeholder={t("octopBot.sidePrompt")}
                aria-label={t("octopBot.sidePrompt")}
                autoSize={{ minRows: 3, maxRows: 8 }}
                onKeyDown={(e) => {
                  // Ctrl/⌘ + Enter sends; plain Enter keeps adding lines.
                  if (
                    e.key === "Enter" &&
                    (e.metaKey || e.ctrlKey) &&
                    !e.nativeEvent.isComposing &&
                    e.nativeEvent.keyCode !== 229
                  ) {
                    e.preventDefault();
                    void ask(draft);
                  }
                }}
              />
              <Button
                className={styles.sideSend}
                type="primary"
                loading={busy}
                disabled={!draft.trim()}
                onClick={() => {
                  sideInput.current?.focus();
                  void ask(draft);
                }}
              >
                {t("octopBot.send")}
              </Button>
            </>
          )}
        </Drawer>
      )}
    </>
  );
}
