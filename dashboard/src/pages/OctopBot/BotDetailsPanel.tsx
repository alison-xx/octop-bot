import { useEffect, useRef, useState } from "react";
import { Button, Drawer, Grid } from "antd";
import {
  BarChart3,
  Blocks,
  CalendarClock,
  Cloud,
  UploadCloud,
  ChevronRight,
  Cpu,
  History,
  Image,
  MessagesSquare,
  Monitor,
  NotebookPen,
  Pencil,
  Shield,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import type { WorkspaceBot } from "../../api/modules/octopBot";
import { octopAgentsApi } from "../../api/modules/octopAgents";
import { providerApi } from "../../api/modules/provider";
import type { ResolvedModel } from "../../api/types";
import { useAgent } from "../../context/AgentContext";
import { useCurrentUser } from "../../hooks/useCurrentUser";
import { canAccessPath, userCan } from "../../utils/permissions";
import { apiErrorMessage } from "../../utils/apiError";
import {
  BOT_CAPABILITY_UPSTREAM,
  BOT_CLOUD,
  BOT_SETTINGS,
  botCapabilityPath,
} from "../../utils/botClientRoute";
import {
  MODEL_AUTO_VALUE,
  defaultModelFromForm,
  defaultModelToForm,
  modelOptionValue,
} from "../../utils/modelOptions";
import { BotCharacter, type BotMotion } from "./BotCharacter";
import { useLynxceStatus } from "../../hooks/useLynxceStatus";
import { isBotOnlyDesktop } from "../../utils/desktopBridge";
import styles from "./BotDetailsPanel.module.less";
import BotActivityLibrary from "./BotActivityLibrary";
import BotComputerCard from "./BotComputerCard";
import BotSchedulesDialog from "./BotSchedulesDialog";
import BotUsageDialog from "./BotUsageDialog";
import CloudComputerCard from "./CloudComputerCard";
import { useBotServerInfo } from "./useBotServerInfo";
import ModelName from "./ModelName";
import ModelSelect, { type ModelItem } from "./ModelSelect";

interface Props {
  bot: WorkspaceBot;
  motion?: BotMotion;
  onClose: () => void;
  onHistory: () => void;
  onSide: () => void;
  onAppearance: () => void;
  onEdit: () => void;
  onMemory: () => void;
  onPrivacy: () => void;
  onDelete: () => void;
}

export default function BotDetailsPanel({
  bot,
  motion,
  onClose,
  onHistory,
  onSide,
  onAppearance,
  onEdit,
  onMemory,
  onPrivacy,
  onDelete,
}: Props) {
  const { t } = useTranslation();
  const edition = useBotServerInfo()?.edition;
  const cloud = edition === "cloud";
  const { agents, refresh } = useAgent();
  const user = useCurrentUser();
  const navigate = useNavigate();
  const location = useLocation();
  const { threadId } = useParams<{ threadId: string }>();
  const [activity, setActivity] = useState<"schedules" | "usage" | null>(null);
  const wide = Grid.useBreakpoint().lg === true;
  const closeButton = useRef<HTMLButtonElement>(null);
  const agent = agents.find((a) => a.agent_id === bot.agent_id);
  const [models, setModels] = useState<ResolvedModel[] | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [failedSelection, setFailedSelection] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [retry, setRetry] = useState(0);
  const botOnly = isBotOnlyDesktop();
  const { status } = useLynxceStatus(botOnly);
  const personalModel =
    agent?.kind !== "managed" && status?.connected && status.selected_model;
  const canConfigure =
    botOnly || userCan(user, "providers") || userCan(user, "ollama_models");
  useEffect(() => {
    let current = true;
    setModels(null);
    setError("");
    providerApi
      .listResolvedModels(bot.agent_id)
      .then((rows) => {
        if (current) setModels(rows);
      })
      .catch((e) => {
        if (current) setError(apiErrorMessage(e, t("octopBot.failed"), t));
      });
    return () => {
      current = false;
    };
  }, [bot.agent_id, retry, t]);
  useEffect(() => {
    if (!wide) return;
    const trigger = document.activeElement;
    closeButton.current?.focus({ preventScroll: true });
    return () => {
      if (trigger instanceof HTMLElement && trigger.isConnected)
        trigger.focus({ preventScroll: true });
    };
  }, [wide]);

  const changeModel = async (value: string) => {
    setSaving(true);
    setFailedSelection(null);
    setSaved(false);
    setError("");
    try {
      await octopAgentsApi.setDefaultModel(
        bot.agent_id,
        defaultModelFromForm(value),
      );
      await refresh({ silent: true, force: true });
      setSaved(true);
    } catch (e) {
      setFailedSelection(value);
      setError(apiErrorMessage(e, t("botClient.profile.editModelFailed"), t));
    } finally {
      setSaving(false);
    }
  };
  const goToSettings = () =>
    navigate(BOT_SETTINGS, {
      state: {
        from: location.pathname,
        source: personalModel ? "lynxce" : undefined,
      },
    });
  const canManageSchedules =
    userCan(user, "tasks") && agent?.is_owner === true && !agent.bridge;
  const canViewUsage = userCan(user, "token_usage") && !!agent && !agent.bridge;
  const canOpenCapabilities =
    agent?.is_owner === true &&
    !agent.bridge &&
    (["skills", "connectors"] as const).some((s) =>
      canAccessPath(user, BOT_CAPABILITY_UPSTREAM[s]),
    );
  const canUseBotInCloud =
    botOnly &&
    !bot.is_private &&
    agent?.is_owner &&
    !agent.bridge &&
    agent.kind !== "managed";
  const actions = [
    ...(canUseBotInCloud
      ? [
          {
            icon: Cloud,
            label: t("botCloud.workWithBot"),
            open: () =>
              navigate(BOT_CLOUD, {
                state: { from: location.pathname, botId: bot.agent_id },
              }),
          },
        ]
      : []),
    ...(canUseBotInCloud && threadId
      ? [
          {
            icon: UploadCloud,
            label: t("botCloud.importChat"),
            open: () =>
              navigate(BOT_CLOUD, {
                state: {
                  from: location.pathname,
                  botId: bot.agent_id,
                  importThreadId: threadId,
                },
              }),
          },
        ]
      : []),
    { icon: History, label: t("octopBot.history"), open: onHistory },
    ...(canOpenCapabilities
      ? [
          {
            icon: Blocks,
            label: t("botCapabilities.profileEntry"),
            open: () =>
              navigate(
                botCapabilityPath("skills") +
                  "?bot=" +
                  encodeURIComponent(bot.agent_id),
                { state: { from: location.pathname } },
              ),
          },
        ]
      : []),
    ...(canManageSchedules
      ? [
          {
            icon: CalendarClock,
            label: t("botClient.activity.schedules"),
            open: () => setActivity("schedules"),
          },
        ]
      : []),
    ...(canViewUsage
      ? [
          {
            icon: BarChart3,
            label: t("botClient.activity.usage"),
            open: () => setActivity("usage"),
          },
        ]
      : []),
    { icon: MessagesSquare, label: t("octopBot.side"), open: onSide },
    { icon: NotebookPen, label: t("octopBot.teamMemory"), open: onMemory },
    ...(!bot.is_main
      ? [{ icon: Shield, label: t("octopBot.privacy"), open: onPrivacy }]
      : []),
  ];
  const modelValue = defaultModelToForm(agent?.default_model);
  const items: ModelItem[] = (models ?? []).map((m) => ({
    value: modelOptionValue(m),
    id: m.model,
    name: m.name,
    group: m.provider_name,
  }));
  if (modelValue && !items.some((item) => item.value === modelValue)) {
    items.push({ value: modelValue, id: modelValue });
  }
  const contents = (
    <section
      className={styles.contents}
      data-bot-profile
      aria-label={t("botClient.profile.title")}
    >
      <header className={styles.top}>
        <h2>{t("botClient.profile.title")}</h2>
        <button
          ref={closeButton}
          type="button"
          className={styles.icon}
          onClick={onClose}
          title={t("common.close")}
          aria-label={t("common.close")}
        >
          <X size={17} />
        </button>
      </header>
      <div className={styles.scroller}>
        <div className={styles.identity}>
          <button
            className={styles.portrait}
            onClick={onAppearance}
            type="button"
            aria-label={t("botClient.profile.look")}
            title={t("botClient.profile.look")}
          >
            <BotCharacter bot={bot} size={74} state={motion} badges={false} />
            <span className={styles.editPhoto}>
              <Image size={12} />
            </span>
          </button>
          <h3>{bot.name}</h3>
          <span>
            {t(
              bot.is_main
                ? "botClient.profile.chief"
                : "botClient.profile.member",
            )}
          </span>
        </div>
        {bot.description && (
          <section className={styles.block}>
            <h4>{t("botClient.profile.role")}</h4>
            <p>{bot.description}</p>
          </section>
        )}
        {agent?.is_owner === true && !agent.bridge && (
          <section className={styles.block}>
            <BotActivityLibrary
              agentId={bot.agent_id}
              canToggle={canManageSchedules}
            />
          </section>
        )}
        <section className={styles.block}>
          <h4>
            <Cpu size={14} />
            {t("botClient.profile.model")}
          </h4>
          {personalModel ? (
            <button type="button" className={styles.row} onClick={goToSettings}>
              <span className={styles.modelRow}>
                <ModelName id={personalModel} />
                <small>{t("botClient.lynxce.source")}</small>
              </span>
              <ChevronRight size={14} />
            </button>
          ) : models?.length === 0 && canConfigure && !modelValue ? (
            <button type="button" className={styles.row} onClick={goToSettings}>
              {t("botClient.connectModel")}
              <ChevronRight size={14} />
            </button>
          ) : (
            <ModelSelect
              className={styles.select}
              aria-label={t("botClient.profile.model")}
              value={modelValue}
              loading={saving || (!models && !error)}
              disabled={saving || !models?.length || !agent}
              items={items}
              lead={[
                {
                  value: MODEL_AUTO_VALUE,
                  label: t("botClient.profile.autoModel"),
                },
              ]}
              onChange={changeModel}
            />
          )}
          {error && (
            <div className={styles.error} role="alert">
              {error}{" "}
              <button
                type="button"
                onClick={() =>
                  failedSelection === null
                    ? setRetry((n) => n + 1)
                    : void changeModel(failedSelection)
                }
              >
                {t("octopBot.retry")}
              </button>
            </div>
          )}
          {saved && !error && (
            <small className={styles.saved} role="status">
              {t("botDirectory.modelSaved")}
            </small>
          )}
        </section>
        {agent?.kind === "expert" &&
          !agent.is_shared &&
          canAccessPath(user, "/remote-desktop/desktop") && (
            <section className={styles.block}>
              <h4>
                <Monitor size={14} />
                {t("octopBot.computer.section")}
              </h4>
              <BotComputerCard key={bot.agent_id} botId={bot.agent_id} />
            </section>
          )}
        {cloud && agent && !agent.is_shared && (
          <section className={styles.block}>
            <h4>
              <Monitor size={14} />
              {t("cloudComputer.section")}
            </h4>
            <CloudComputerCard key={bot.agent_id} botId={bot.agent_id} />
          </section>
        )}
        <section className={styles.block}>
          <h4>{t("botClient.profile.actions")}</h4>
          {actions.map(({ icon: Icon, label, open }) => (
            <button
              className={styles.row}
              key={label}
              type="button"
              onClick={open}
            >
              <Icon size={16} />
              <span>{label}</span>
              <ChevronRight size={14} />
            </button>
          ))}
        </section>
        <button
          type="button"
          className={styles.edit}
          onClick={onEdit}
          disabled={!agent}
        >
          <Pencil size={14} />
          {t("botClient.profile.edit")}
        </button>
        {!bot.is_main && (
          <Button danger block type="text" onClick={onDelete}>
            {t("octopBot.deleteBot")}
          </Button>
        )}
      </div>
    </section>
  );
  const activityDialog =
    activity === "schedules" && canManageSchedules ? (
      <BotSchedulesDialog
        agentId={bot.agent_id}
        name={bot.name}
        threadId={threadId}
        edition={edition}
        onOpenCloud={
          canUseBotInCloud
            ? (job) =>
                navigate(BOT_CLOUD, {
                  state: {
                    from: location.pathname,
                    botId: bot.agent_id,
                    tab: "schedules",
                    pausedTimerId: job?.id,
                  },
                })
            : undefined
        }
        onClose={() => setActivity(null)}
      />
    ) : activity === "usage" && canViewUsage ? (
      <BotUsageDialog
        agentId={bot.agent_id}
        name={bot.name}
        onClose={() => setActivity(null)}
      />
    ) : null;
  if (!wide)
    return (
      <>
        <Drawer
          open
          placement="right"
          width="min(328px, 100vw)"
          closable={false}
          onClose={onClose}
          styles={{ body: { padding: 0 } }}
        >
          {contents}
        </Drawer>
        {activityDialog}
      </>
    );
  return (
    <>
      <aside
        className={styles.dock}
        onKeyDown={(event) => {
          if (
            event.key === "Escape" &&
            !event.defaultPrevented &&
            !(
              event.target instanceof Element &&
              event.target.closest('[role="combobox"][aria-expanded="true"]')
            )
          ) {
            event.stopPropagation();
            onClose();
          }
        }}
      >
        {contents}
      </aside>
      {activityDialog}
    </>
  );
}
