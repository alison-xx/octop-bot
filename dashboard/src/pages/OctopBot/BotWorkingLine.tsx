import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { ASK_USER_TOOL_NAME } from "../../api/types/hitl";
import type { ChatMessage } from "../Chat/hooks/useChat";
import { useEmbeddedChat } from "../Chat/ChatRouteContext";
import { useToolDisplayNames } from "../Chat/hooks/toolDisplayNames";
import { hasPendingHitl, isPausedAskTool } from "../Chat/utils/pendingHitl";
import { useElapsedSince } from "../../hooks/useElapsedSeconds";
import {
  collectWriteTodosFromMessages,
  countCompletedTodos,
} from "../../utils/parseWriteTodos";
import { isMediaTool } from "./MediaTaskStatus";
import styles from "./botConversation.module.less";

/**
 * The one status line under a working Bot: its animated avatar and a short
 * title for what it is doing now (the current plan step, else the tool it is
 * running, else "thinking").
 */
export default function BotWorkingLine({
  messages,
  agentId,
  startedAt,
}: {
  messages: ChatMessage[];
  agentId?: string | null;
  startedAt?: number | null;
}) {
  const { t } = useTranslation();
  const embedded = useEmbeddedChat();
  const toolName = useToolDisplayNames();
  const [mountedAt] = useState(Date.now);
  const elapsed = useElapsedSince(startedAt ?? mountedAt);
  const title = useMemo(() => {
    let start = messages.length;
    while (start > 0 && messages[start - 1].role !== "user") start -= 1;
    const turn = messages.slice(start);
    if (
      turn.some(
        (m) =>
          isMediaTool(m.toolData?.name) &&
          !m.toolData?.output &&
          m.status !== "error",
      )
    )
      return null;
    if (
      hasPendingHitl(turn) ||
      (turn.length && isPausedAskTool(turn[turn.length - 1]))
    )
      return t("octopBot.waitingForInput");
    const plan = collectWriteTodosFromMessages(turn);
    const step = plan.find((item) => item.status === "in_progress");
    const parts = [];
    if (plan.length)
      parts.push(
        t("octopBot.planProgress", {
          done: countCompletedTodos(plan),
          total: plan.length,
        }),
      );
    if (step) parts.push(step.content);
    const tool = [...turn]
      .reverse()
      .find(
        (m) =>
          m.toolData &&
          m.toolData.output === undefined &&
          m.toolData.name !== ASK_USER_TOOL_NAME,
      );
    if (tool?.toolData)
      parts.push(
        t("chat.processRunningTool", {
          name: tool.toolData.displayName || toolName(tool.toolData.name),
        }),
      );
    else if (!parts.length) {
      const count = turn.filter(
        (item) => item.toolData?.output !== undefined,
      ).length;
      parts.push(
        count
          ? t("chat.processSummaryToolsOnly", { tools: count })
          : t("octopBot.thinking"),
      );
    }
    return parts.join(" · ");
  }, [messages, t, toolName]);
  if (!title) return null;
  return (
    <div className={styles.working}>
      <span className={styles.workingAvatar} aria-hidden>
        {embedded?.renderAvatar?.(agentId, 26, true)}
      </span>
      <span role="status" className={styles.workingTitle}>
        {title}
      </span>
      <small role="timer" className={styles.workingTime}>
        {t("octopBot.workingElapsed", { seconds: elapsed })}
      </small>
    </div>
  );
}
