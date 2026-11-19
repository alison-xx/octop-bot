import { useState, type ReactNode } from "react";
import { Alert, Spin } from "antd";
import { ArrowUpRight, Plug } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { octopAgentsApi } from "../../api/modules/octopAgents";
import type { OctopAgent } from "../../context/AgentContext";
import { useServerTimezone } from "../../hooks/useServerTimezone";
import { apiErrorMessage } from "../../utils/apiError";
import { BOT_SETTINGS } from "../../utils/botClientRoute";
import {
  formatServerHourMinute,
  formatServerYmd,
} from "../../utils/formatMessageTime";
import type { WelcomeQuickCard } from "../Chat/components/WelcomeScreen";
import styles from "./botConversation.module.less";

export function BotConversationIntro({
  avatar,
  name,
  text,
  timestamp,
  children,
}: {
  avatar: ReactNode;
  name?: string;
  text?: string | null;
  timestamp?: number;
  children?: ReactNode;
}) {
  const { t } = useTranslation();
  const timezone = useServerTimezone();
  const [openedAt] = useState(Date.now);
  const when = timestamp || openedAt;
  const day = formatServerYmd(when, timezone);
  const today = day === formatServerYmd(Date.now(), timezone);
  return (
    <div className={styles.introduction}>
      <time className={styles.date} dateTime={new Date(when).toISOString()}>
        {today ? t("botClient.today") : day}{" "}
        {formatServerHourMinute(when, timezone)}
      </time>
      {(text || children) && (
        <div className={styles.greetingRow}>
          <div className={styles.greetingAvatar} title={name}>
            {avatar}
          </div>
          <div className={styles.greetingContent}>
            {text && <div className={styles.incoming}>{text}</div>}
            {children}
          </div>
        </div>
      )}
    </div>
  );
}

export default function BotClientWelcome({
  avatar,
  agent,
  isChief,
  welcome,
  prompts,
  loading,
  needsModel,
  ready,
  canConfigure,
  onRefresh,
  onPick,
}: {
  avatar: ReactNode;
  agent: OctopAgent | null;
  isChief: boolean;
  welcome: string | null;
  prompts: WelcomeQuickCard[];
  loading: boolean;
  needsModel: boolean;
  ready: boolean;
  canConfigure: boolean;
  onRefresh: () => Promise<unknown>;
  onPick: (text: string) => void;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");
  const start = async () => {
    if (!agent) return;
    setError("");
    setStarting(true);
    try {
      await octopAgentsApi.start(agent.agent_id);
      await onRefresh();
    } catch (e) {
      setError(apiErrorMessage(e, t("octopBot.failed"), t));
    } finally {
      setStarting(false);
    }
  };
  const configure = (prefillInput?: string) => {
    navigate(BOT_SETTINGS, {
      state: { from: location.pathname, prefillInput },
    });
  };
  const choices = isChief
    ? [
        { title: t("botClient.teamLabel"), prompt: t("botClient.teamPrompt") },
        {
          title: t("botClient.assignLabel"),
          prompt: t("botClient.assignPrompt"),
        },
        { title: t("botClient.planLabel"), prompt: t("botClient.planPrompt") },
      ]
    : prompts.slice(0, 3);
  return (
    <div className={styles.firstConversation}>
      <BotConversationIntro
        avatar={avatar}
        name={agent?.name}
        text={welcome || agent?.description}
      >
        {loading ? (
          <Spin size="small" />
        ) : (
          <>
            {error && <Alert type="error" message={error} />}
            {needsModel && (
              <div className={styles.connect}>
                <span>
                  {t(
                    canConfigure
                      ? "botClient.needsModel"
                      : "modelConfig.promptMessageNoPermission",
                  )}
                </span>
                {canConfigure && (
                  <button type="button" onClick={() => configure()}>
                    <Plug size={14} />
                    {t("botClient.connectModel")}
                  </button>
                )}
              </div>
            )}
            {!ready && !needsModel && (
              <button
                className={styles.start}
                type="button"
                disabled={
                  starting ||
                  agent?.state === "starting" ||
                  !agent ||
                  agent.bridge_disconnected
                }
                onClick={() => void start()}
              >
                {agent?.bridge_disconnected
                  ? t("chat.remoteExpert.disconnectedTitle")
                  : t(
                      starting || agent?.state === "starting"
                        ? "common.agentState.starting"
                        : "experts.startAgent",
                    )}
              </button>
            )}
            {(ready || (needsModel && canConfigure)) && choices.length > 0 && (
              <div className={styles.suggestions}>
                {choices.map(({ title, prompt }) => (
                  <button
                    key={prompt}
                    type="button"
                    onClick={() =>
                      needsModel ? configure(prompt) : onPick(prompt)
                    }
                  >
                    {title}
                    <ArrowUpRight size={13} aria-hidden />
                  </button>
                ))}
              </div>
            )}
          </>
        )}
      </BotConversationIntro>
    </div>
  );
}
