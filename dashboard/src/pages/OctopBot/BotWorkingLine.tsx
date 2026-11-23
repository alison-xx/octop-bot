import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import type { ChatMessage } from "../Chat/hooks/useChat";
import { useEmbeddedChat } from "../Chat/ChatRouteContext";
import { useToolDisplayNames } from "../Chat/hooks/toolDisplayNames";
import { collectWriteTodosFromMessages } from "../../utils/parseWriteTodos";
import styles from "./botConversation.module.less";

/**
 * The one status line under a working Bot: its animated avatar and a short
 * title for what it is doing now (the current plan step, else the tool it is
 * running, else "thinking").
 */
export default function BotWorkingLine({
  messages,
  agentId,
}: {
  messages: ChatMessage[];
  agentId?: string | null;
}) {
  const { t } = useTranslation();
  const embedded = useEmbeddedChat();
  const toolName = useToolDisplayNames();
  const title = useMemo(() => {
    let start = messages.length;
    while (start > 0 && messages[start - 1].role !== "user") start -= 1;
    const turn = messages.slice(start);
    const step = collectWriteTodosFromMessages(turn).find(
      (item) => item.status === "in_progress",
    );
    if (step) return step.content;
    const tool = [...turn]
      .reverse()
      .find((m) => m.toolData && m.toolData.output === undefined);
    if (tool?.toolData)
      return t("chat.processRunningTool", {
        name: tool.toolData.displayName || toolName(tool.toolData.name),
      });
    return t("octopBot.thinking");
  }, [messages, t, toolName]);
  return (
    <div className={styles.working} role="status" aria-live="polite">
      <span className={styles.workingAvatar} aria-hidden>
        {embedded?.renderAvatar?.(agentId, 26, true)}
      </span>
      <span className={styles.workingTitle}>{title}</span>
    </div>
  );
}
