import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Button, Empty, Segmented, Select, Spin } from "antd";
import {
  ArrowLeft,
  CalendarClock,
  Cloud,
  LogOut,
  MessageSquare,
  Plus,
  RefreshCw,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router-dom";
import {
  botCloudApi,
  type CloudAccount,
  type CloudCapabilities,
  type CloudSession,
} from "../../api/modules/botCloud";
import { octopBotApi, type WorkspaceBot } from "../../api/modules/octopBot";
import { BOT_HOME, botClientDestination } from "../../utils/botClientRoute";
import { apiErrorMessage } from "../../utils/apiError";
import { getDesktopBridge } from "../../utils/desktopBridge";
import { BotCharacter, octopCharacter } from "./BotCharacter";
import WalletBalance from "./WalletBalance";
import LynxceSignInForm from "./LynxceSignInForm";
import CloudChat from "./CloudChat";
import CloudSchedules from "./CloudSchedules";
import CloudImport from "./CloudImport";
import ModelSelect from "./ModelSelect";
import styles from "./cloud.module.less";

export default function CloudWorkspace() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const state = location.state as {
    from?: string;
    botId?: string;
    tab?: string;
    pausedTimerId?: string;
    importThreadId?: string;
  } | null;
  const [account, setAccount] = useState<CloudAccount | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const seq = useRef(0);
  const loadAccount = useCallback(async () => {
    const id = ++seq.current;
    try {
      const status = await botCloudApi.account();
      if (id === seq.current) {
        setAccount(status);
        setError("");
      }
    } catch (err) {
      if (id === seq.current)
        setError(apiErrorMessage(err, t("octopBot.failed"), t));
    }
  }, [t]);
  useEffect(() => {
    void loadAccount();
    window.addEventListener("focus", loadAccount);
    return () => {
      window.removeEventListener("focus", loadAccount);
    };
  }, [loadAccount]);
  /** Resolves with the error when sign-in failed (shown here, inspected by the form). */
  async function signIn(
    attempt: () => Promise<CloudAccount>,
  ): Promise<unknown> {
    setBusy(true);
    setError("");
    try {
      const next = await attempt();
      ++seq.current;
      setAccount(next);
    } catch (err) {
      setError(apiErrorMessage(err, t("octopBot.failed"), t));
      return err;
    } finally {
      setBusy(false);
    }
  }
  const workbuddyLogin = getDesktopBridge()?.workbuddyLogin;
  async function loginWorkbuddy() {
    if (!workbuddyLogin) return;
    setBusy(true);
    setError("");
    try {
      const result = await workbuddyLogin();
      if (!result.ok) {
        if (result.reason !== "cancelled")
          setError(
            t(
              result.reason === "denied"
                ? "botCloud.workbuddyDenied"
                : "botCloud.workbuddyFailed",
            ),
          );
        return;
      }
      const next = await botCloudApi.loginWorkbuddy(result.code);
      ++seq.current;
      setAccount(next);
    } catch (err) {
      setError(apiErrorMessage(err, t("octopBot.failed"), t));
    } finally {
      setBusy(false);
    }
  }
  async function logout() {
    if (!account?.account_id) return;
    setBusy(true);
    setError("");
    try {
      await botCloudApi.logout(account.account_id);
      ++seq.current;
      setAccount({ connected: false, account_id: null, display_name: null });
    } catch (err) {
      setError(apiErrorMessage(err, t("octopBot.failed"), t));
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className={styles.page}>
      <header className={styles.header} data-octop-chrome-end-pad>
        <Button
          type="text"
          icon={<ArrowLeft size={16} />}
          onClick={() =>
            navigate(botClientDestination(state?.from || BOT_HOME))
          }
        >
          {t("botDirectory.teamTab")}
        </Button>
        <h1>
          <Cloud size={18} />
          {t("botCloud.title")}
        </h1>
        {account?.connected && (
          <div className={styles.account}>
            <span>{account.display_name || account.account_id}</span>
            <Button
              type="text"
              disabled={busy}
              icon={<LogOut size={16} />}
              title={t("botCloud.signOut")}
              aria-label={t("botCloud.signOut")}
              onClick={() => void logout()}
            />
          </div>
        )}
      </header>
      {error && (
        <Alert
          type="error"
          showIcon
          message={error}
          action={
            <Button size="small" onClick={() => void loadAccount()}>
              {t("common.refresh")}
            </Button>
          }
        />
      )}
      {!account ? (
        <div className={styles.center}>{!error && <Spin />}</div>
      ) : !account.connected || !account.account_id ? (
        <div className={styles.center}>
          <section className={styles.login}>
            <BotCharacter
              look={{ ...octopCharacter, source: "character" }}
              size={66}
              badges={false}
            />
            <h2>{t("botCloud.signInTitle")}</h2>
            <p>{t("botCloud.intro")}</p>
            <LynxceSignInForm
              idPrefix="bot-cloud"
              busy={busy}
              submitLabel={t("botCloud.signIn")}
              sendCode={async (target) =>
                (
                  await botCloudApi.sendCode(
                    target,
                    i18n.language.startsWith("en") ? "en" : "zh",
                  )
                ).channel
              }
              onCode={(target, code, password) =>
                signIn(() => botCloudApi.codeLogin(target, code, password))
              }
              onPassword={(account, password) =>
                signIn(() => botCloudApi.login(account, password))
              }
              onError={(err) =>
                setError(apiErrorMessage(err, t("octopBot.failed"), t))
              }
              onClearError={() => setError("")}
            />
            {workbuddyLogin && (
              <div className={styles.altLogin}>
                <Button
                  block
                  disabled={busy}
                  onClick={() => void loginWorkbuddy()}
                >
                  {t("botCloud.workbuddySignIn")}
                </Button>
                <p>{t("botCloud.workbuddyHint")}</p>
              </div>
            )}
          </section>
        </div>
      ) : (
        <Connected
          key={account.account_id}
          accountId={account.account_id}
          botId={state?.botId}
          initialTab={state?.tab}
          pausedTimerId={state?.pausedTimerId}
          importThreadId={state?.importThreadId}
        />
      )}
    </main>
  );
}

function Connected({
  accountId,
  botId,
  initialTab,
  pausedTimerId,
  importThreadId,
}: {
  accountId: string;
  botId?: string;
  initialTab?: string;
  pausedTimerId?: string;
  importThreadId?: string;
}) {
  const { t } = useTranslation();
  const [tab, setTab] = useState(
    initialTab === "schedules" ? "schedules" : "chat",
  );
  const [sessions, setSessions] = useState<CloudSession[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [active, setActive] = useState<string>();
  const [showList, setShowList] = useState(false);
  const [listError, setListError] = useState("");
  const [listing, setListing] = useState(false);
  const [caps, setCaps] = useState<CloudCapabilities | null>(null);
  const [capError, setCapError] = useState("");
  const [bots, setBots] = useState<WorkspaceBot[]>([]);
  const [bot, setBot] = useState(botId);
  const [model, setModel] = useState("");
  const [revision, setRevision] = useState(0);
  const listSeq = useRef(0);
  const [seed, setSeed] = useState(pausedTimerId);
  const [importing, setImporting] = useState(Boolean(importThreadId && botId));
  const fetchList = useCallback(
    async (next?: string) => {
      const seq = ++listSeq.current;
      setListing(true);
      try {
        let page = await botCloudApi.sessions(accountId, next);
        // Lynxce's cursor spans all the account's apps. Skip unrelated pages so
        // an existing Octop chat is reachable from a newly connected device.
        for (
          let i = 0;
          i < 3 &&
          !page.items.length &&
          page.next_cursor &&
          seq === listSeq.current;
          i++
        ) {
          page = await botCloudApi.sessions(accountId, page.next_cursor);
        }
        if (seq !== listSeq.current) return;
        setSessions((prev) => {
          const unique = new Map(
            (next ? prev : []).map((row) => [row.id, row]),
          );
          for (const row of page.items) unique.set(row.id, row);
          return [...unique.values()];
        });
        setCursor(page.next_cursor);
        setListError("");
      } catch (err) {
        if (seq === listSeq.current)
          setListError(apiErrorMessage(err, t("octopBot.failed"), t));
      } finally {
        if (seq === listSeq.current) setListing(false);
      }
    },
    [accountId, t],
  );
  useEffect(() => {
    void fetchList();
    const refresh = () => void fetchList();
    window.addEventListener("focus", refresh);
    return () => {
      window.removeEventListener("focus", refresh);
    };
  }, [fetchList]);
  useEffect(() => {
    let live = true;
    botCloudApi
      .capabilities(accountId)
      .then((data) => {
        if (!live) return;
        setCaps(data);
        setCapError("");
        setModel((prev) =>
          data.models.includes(prev)
            ? prev
            : data.default_model || data.models[0] || "",
        );
      })
      .catch((err) => {
        if (live) {
          setCaps(null);
          setCapError(apiErrorMessage(err, t("octopBot.failed"), t));
        }
      });
    octopBotApi
      .workspace()
      .then((ws) => {
        if (live)
          setBots(
            ws.bots.filter(
              (b) =>
                b.can_join_group !== false &&
                !b.is_private &&
                b.kind === "expert",
            ),
          );
      })
      .catch(() => {
        if (live) setBots([]);
      });
    return () => {
      live = false;
    };
  }, [accountId, revision, t]);
  const select = (id?: string) => {
    setActive(id);
    setShowList(false);
    setTab("chat");
  };
  const selectedBot = bots.find((b) => b.agent_id === bot);
  return (
    <>
      {importing && botId && importThreadId && (
        <CloudImport
          accountId={accountId}
          model={model}
          botId={botId}
          threadId={importThreadId}
          onClose={() => setImporting(false)}
          onDone={(id) => {
            setImporting(false);
            select(id);
            void fetchList();
          }}
        />
      )}
      <div className={styles.tabs}>
        <Segmented
          value={tab}
          onChange={(v) => setTab(String(v))}
          options={[
            {
              value: "chat",
              label: t("botCloud.chats"),
              icon: <MessageSquare size={15} />,
            },
            {
              value: "schedules",
              label: t("botCloud.schedules"),
              icon: <CalendarClock size={15} />,
            },
          ]}
        />
        <WalletBalance key={accountId} source="cloud" accountId={accountId} />
      </div>
      {tab === "schedules" ? (
        <CloudSchedules
          accountId={accountId}
          bots={bots}
          botId={bot}
          onBot={setBot}
          seedId={seed}
          clearSeed={() => setSeed(undefined)}
          onOpen={select}
        />
      ) : (
        <div className={styles.workspace} data-show-list={showList}>
          <aside className={styles.rail}>
            <div className={styles.bar}>
              <h2>{t("botCloud.chats")}</h2>
              <Button
                type="text"
                icon={<RefreshCw size={14} />}
                aria-label={t("common.refresh")}
                disabled={listing}
                onClick={() => void fetchList()}
              />
            </div>
            <Button icon={<Plus size={15} />} onClick={() => select()}>
              {t("botCloud.newChat")}
            </Button>
            {listError && <Alert type="error" message={listError} />}
            <nav>
              {sessions.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  aria-current={active === s.id ? "page" : undefined}
                  onClick={() => select(s.id)}
                >
                  <MessageSquare size={15} />
                  <span>{s.title || t("botCloud.untitled")}</span>
                </button>
              ))}
            </nav>
            {listing ? (
              <Spin size="small" />
            ) : cursor ? (
              <Button type="link" onClick={() => void fetchList(cursor)}>
                {t("botCloud.more")}
              </Button>
            ) : (
              !sessions.length &&
              !listError && (
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description={t("botCloud.noChats")}
                />
              )
            )}
          </aside>
          <section className={styles.chat}>
            <div className={styles.bar}>
              <Button
                className={styles.mobileList}
                type="text"
                icon={<MessageSquare size={16} />}
                onClick={() => setShowList(true)}
              >
                {t("botCloud.chats")}
              </Button>
              <h2>
                {sessions.find((s) => s.id === active)?.title ||
                  (active ? t("botCloud.untitled") : t("botCloud.newChat"))}
              </h2>
              {!active && caps?.models.length ? (
                <ModelSelect
                  className={styles.modelSelect}
                  aria-label={t("botClient.profile.model")}
                  value={model || undefined}
                  onChange={setModel}
                  items={caps.models.map((id) => ({ value: id, id }))}
                />
              ) : null}
            </div>
            {!active && bots.length > 0 && (
              <div className={styles.persona}>
                <label htmlFor="cloud-bot">{t("botCloud.bot")}</label>
                <Select
                  id="cloud-bot"
                  className={styles.botSelect}
                  value={selectedBot?.agent_id || ""}
                  onChange={(v) => setBot(v || undefined)}
                  showSearch
                  optionFilterProp="search"
                  options={[
                    {
                      value: "",
                      search: t("botCloud.defaultBot"),
                      label: (
                        <span className={styles.botOption}>
                          <BotCharacter
                            look={{ ...octopCharacter, source: "character" }}
                            size={20}
                            badges={false}
                          />
                          {t("botCloud.defaultBot")}
                        </span>
                      ),
                    },
                    ...bots.map((b) => ({
                      value: b.agent_id,
                      search: b.name,
                      title: b.name,
                      label: (
                        <span className={styles.botOption}>
                          <BotCharacter bot={b} size={20} badges={false} />
                          <span>{b.name}</span>
                        </span>
                      ),
                    })),
                  ]}
                />
              </div>
            )}
            {capError && (
              <Alert
                type="error"
                message={capError}
                action={
                  <Button onClick={() => setRevision((n) => n + 1)}>
                    {t("common.retry")}
                  </Button>
                }
              />
            )}
            {caps && !caps.enabled && (
              <Alert
                type="warning"
                message={caps.reason || t("botCloud.unavailable")}
              />
            )}
            <CloudChat
              key={active || "new"}
              accountId={accountId}
              sessionId={active}
              canStart={Boolean(caps?.enabled && model)}
              model={model}
              bot={active ? undefined : selectedBot}
              onAccepted={(id) => {
                select(id);
                void fetchList();
              }}
            />
          </section>
        </div>
      )}
    </>
  );
}
