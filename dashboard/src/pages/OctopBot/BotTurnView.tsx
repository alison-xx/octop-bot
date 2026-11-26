import { Fragment, useMemo } from "react";
import {
  ASK_USER_TOOL_NAME,
  extractAskQuestions,
  isAskHitl,
  parseActionArgs,
  questionsFromUnknown,
  type HitlDecisionHandler,
} from "../../api/types/hitl";
import type { ChatMessage } from "../Chat/hooks/useChat";
import { CreditsRequiredCard } from "./CreditsWidgets";
import { useLynxceCredits } from "./useLynxceCredits";
import { classifyChatStreamError } from "../../utils/chatStreamError";
import MessageBubble from "../Chat/components/MessageBubble";
import { ToolMediaStrip } from "../Chat/components/ToolMediaStrip";
import { KnowledgeCitationsStrip } from "../Chat/components/KnowledgeCitationsStrip";
import { ToolDetailsInline } from "../Chat/components/MessageBubble";
import {
  deriveMessageContent,
  splitAssistantTurn,
  toAnswerOnlyMessage,
} from "../Chat/utils/messageContent";
import { messageSpeakerId } from "../Chat/utils/messageGrouping";
import { repairedFileEdit } from "./repairedFileEdit";
import { isResumableHitl } from "../Chat/utils/pendingHitl";
import { collectTurnToolMedia } from "../../utils/collectTurnToolMedia";
import { collectTurnKnowledgeCitations } from "../../utils/collectTurnKnowledgeCitations";
import { isPinnedToolUiMessage } from "../../plugins/toolRenderers/isPinnedToolUi";
import { useAgent } from "../../context/AgentContext";
import MediaTaskStatus, { isMediaTool } from "./MediaTaskStatus";
import BotCreationEvents from "./BotCreationEvents";
import { separateCreations } from "./creationEvents";
import BotAskCard, { parseAskAnswers } from "./BotAskCard";
import CloudComputerHandoff from "./CloudComputerHandoff";
import BotApprovalCard from "./BotApprovalCard";
import BotTaskCard, { BotTaskReport } from "./BotTaskCard";
import { isTaskTool, parseTaskOutput, type BotTaskIndex } from "./botTasks";
import styles from "./botConversation.module.less";

interface BotTurnViewProps {
  messages: ChatMessage[];
  agentId?: string | null;
  onRegenerate?: (messageId: string) => void;
  onDisableStreamUsage?: () => Promise<boolean>;
  onForkAssistantMessage?: (messageId: string) => void;
  forkDisabled?: boolean;
  forkDisabledHint?: string;
  onAcpPermissionSelect?: (message: string) => void;
  onHitlDecision?: HitlDecisionHandler;
  /** Every task in the conversation, at its newest state. */
  tasks?: BotTaskIndex;
  /** The Bot is replying in this conversation right now. */
  live?: boolean;
}

/**
 * One assistant turn in the Bot client: every text segment is its own
 * bubble, questions sit in the flow, and tool steps stay out of sight (the
 * working line at the bottom of the list reports progress instead).
 */
/** The server's code for a turn that ran out of Lynxce credits. */
const CREDITS_REQUIRED = "BOT_CLOUD_CREDITS_REQUIRED";
/** …and for one that hit the account key's daily cap (credits are still there). */
const DAILY_LIMIT = "BOT_LYNXCE_DAILY_LIMIT";

export default function BotTurnView({
  messages,
  agentId: agentIdProp,
  onRegenerate,
  onDisableStreamUsage,
  onForkAssistantMessage,
  forkDisabled,
  forkDisabledHint,
  onAcpPermissionSelect,
  onHitlDecision,
  tasks,
  live = false,
}: BotTurnViewProps) {
  const { activeAgentId } = useAgent();
  const agentId = agentIdProp ?? activeAgentId;
  const speakerId =
    messages.map((item) => messageSpeakerId(item)).find(Boolean) || agentId;
  const { remaining, created } = useMemo(
    () => separateCreations(messages, true),
    [messages],
  );
  const full = useMemo(() => splitAssistantTurn(messages), [messages]);
  const media = useMemo(
    () => collectTurnToolMedia(full, speakerId),
    [full, speakerId],
  );
  const citations = useMemo(() => collectTurnKnowledgeCitations(full), [full]);
  const credits = useLynxceCredits();
  // Older servers (and history saved before the code existed) only say it in words.
  const billed = credits.status === "ready" || credits.status === "loading";
  const dailyLimit = (message: ChatMessage) => {
    if (message.errorInfo?.code === DAILY_LIMIT) return true;
    const text =
      message.errorInfo?.message || deriveMessageContent(message).textContent;
    return billed && /credit_limit_reached/.test(text);
  };
  const outOfCredits = (message: ChatMessage) =>
    dailyLimit(message) ||
    message.errorInfo?.code === CREDITS_REQUIRED ||
    (billed &&
      classifyChatStreamError(
        message.errorInfo?.message || deriveMessageContent(message).textContent,
      ) === "stream_errors.insufficient_balance");
  const bubble = (message: ChatMessage) => (
    <MessageBubble
      message={message}
      agentId={agentId}
      groupPosition="only"
      onRegenerate={onRegenerate}
      onDisableStreamUsage={onDisableStreamUsage}
      onForkAssistantMessage={onForkAssistantMessage}
      forkDisabled={forkDisabled}
      forkDisabledHint={forkDisabledHint}
    />
  );

  // A tool call often carries a line of text ("let me ask a few things").
  const lead = (message: ChatMessage) =>
    deriveMessageContent(message).textContent.trim()
      ? bubble({ ...toAnswerOnlyMessage(message), hitlData: undefined })
      : null;

  const block = (message: ChatMessage) => {
    const hitl = message.hitlData;
    if (hitl) {
      const actions = hitl.action_requests ?? [];
      if (!isAskHitl(actions))
        return (
          <MessageBubble
            message={message}
            agentId={agentId}
            onHitlDecision={onHitlDecision}
            groupPosition="only"
          />
        );
      const pending =
        (hitl.status ?? "pending") === "pending" && isResumableHitl(hitl);
      // `request_takeover`: the question also names the Bot's cloud computer to take over.
      const computer = actions
        .map((a) => parseActionArgs(a.args).cloud_computer)
        .find((v): v is string => typeof v === "string");
      // `request_approval` (or a guarded click): an approval card while it waits.
      const approval = actions
        .map((a) => parseActionArgs(a.args).approval)
        .find((v) => v && typeof v === "object");
      const asked = extractAskQuestions(actions)[0];
      if (pending && approval && asked) {
        const answer = (label: string) =>
          onHitlDecision?.(
            actions.map(() => ({ type: "respond", message: label })),
            undefined,
            hitl.pending_id,
          );
        return (
          <BotApprovalCard
            title={actions[0]?.description ?? ""}
            question={asked.question}
            options={(asked.options ?? []).map((o) => o.label)}
            onAnswer={onHitlDecision ? answer : undefined}
          />
        );
      }
      return (
        <>
          {pending && computer && <CloudComputerHandoff botId={computer} />}
          <BotAskCard
            questions={extractAskQuestions(actions)}
            onSubmit={
              pending && onHitlDecision
                ? (answer) =>
                    onHitlDecision(
                      actions.map(() => ({ type: "respond", message: answer })),
                      undefined,
                      hitl.pending_id,
                    )
                : undefined
            }
          />
        </>
      );
    }
    const tool = message.toolData;
    if (tool && isMediaTool(tool.name)) {
      return <MediaTaskStatus message={message} live={live} />;
    }
    if (isTaskTool(tool?.name)) {
      // The card sits where the task started; the report where it finished.
      const id = tasks?.byMessage.get(message.id);
      const entry = id ? tasks?.byId.get(id) : undefined;
      if (entry && entry.firstMessageId === message.id)
        return (
          <BotTaskCard entry={entry} live={live && tasks?.latest === id} />
        );
      const finished =
        tool?.name === "task_finish" ? parseTaskOutput(tool.output) : null;
      return finished && finished.status !== "running" ? (
        <BotTaskReport task={finished} agentId={speakerId} />
      ) : null;
    }
    if (tool?.name === ASK_USER_TOOL_NAME) {
      const questions = questionsFromUnknown(tool.arguments);
      return (
        <BotAskCard
          questions={questions}
          answers={parseAskAnswers(
            questions,
            tool.output === undefined ? undefined : String(tool.output),
          )}
        />
      );
    }
    if (tool) {
      return isPinnedToolUiMessage(message) ? (
        <div className={styles.pinnedTool}>
          <ToolDetailsInline
            toolData={tool}
            isStreaming={message.status === "streaming"}
            onAcpPermissionSelect={onAcpPermissionSelect}
            hideMediaPreview
            agentId={speakerId}
          />
        </div>
      ) : null;
    }
    if (message.status === "error")
      return outOfCredits(message) ? (
        <CreditsRequiredCard
          kind={dailyLimit(message) ? "limit" : "credits"}
          onContinue={onRegenerate ? () => onRegenerate(message.id) : undefined}
        />
      ) : (
        bubble(message)
      );
    return lead(message);
  };

  const items = remaining.map((message, index) => {
    const edit = message.toolData;
    if (
      edit?.name === "edit_file" &&
      message.status === "error" &&
      classifyChatStreamError(
        message.errorInfo?.message || String(edit.output ?? ""),
      ) === "stream_errors.ambiguous_edit"
    ) {
      if (
        remaining
          .slice(index + 1)
          .some((next) => repairedFileEdit(message, next))
      )
        return null;
      return <Fragment key={message.id}>{bubble(message)}</Fragment>;
    }
    return (
      <Fragment key={message.id}>
        {(message.hitlData || message.toolData) && lead(message)}
        {block(message)}
      </Fragment>
    );
  });

  if (
    !remaining.some(
      (m) =>
        m.hitlData ||
        isMediaTool(m.toolData?.name) ||
        m.toolData?.name === ASK_USER_TOOL_NAME ||
        (isTaskTool(m.toolData?.name) && parseTaskOutput(m.toolData?.output)) ||
        (m.toolData && isPinnedToolUiMessage(m)) ||
        m.status === "error" ||
        deriveMessageContent(m).textContent.trim(),
    ) &&
    !created.length &&
    !media.images.length &&
    !media.videos.length &&
    !media.files.length
  )
    return null;

  return (
    <div className={styles.turn}>
      {items}
      {media.images.length + media.videos.length + media.files.length > 0 && (
        <ToolMediaStrip
          images={media.images}
          videos={media.videos}
          files={media.files}
          agentId={speakerId}
          rich
        />
      )}
      {created.length > 0 && <BotCreationEvents items={created} />}
      {citations.length > 0 && (
        <KnowledgeCitationsStrip citations={citations} />
      )}
    </div>
  );
}
