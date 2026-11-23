import { Fragment, useMemo } from "react";
import {
  ASK_USER_TOOL_NAME,
  extractAskQuestions,
  isAskHitl,
  questionsFromUnknown,
  type HitlDecisionHandler,
} from "../../api/types/hitl";
import type { ChatMessage } from "../Chat/hooks/useChat";
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
import { isResumableHitl } from "../Chat/utils/pendingHitl";
import { collectTurnToolMedia } from "../../utils/collectTurnToolMedia";
import { collectTurnKnowledgeCitations } from "../../utils/collectTurnKnowledgeCitations";
import { isPinnedToolUiMessage } from "../../plugins/toolRenderers/isPinnedToolUi";
import { useAgent } from "../../context/AgentContext";
import BotCreationEvents from "./BotCreationEvents";
import { separateCreations } from "./creationEvents";
import BotAskCard, { parseAskAnswers } from "./BotAskCard";
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
}

/**
 * One assistant turn in the Bot client: every text segment is its own
 * bubble, questions sit in the flow, and tool steps stay out of sight (the
 * working line at the bottom of the list reports progress instead).
 */
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
      return (
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
      );
    }
    const tool = message.toolData;
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
    if (message.status === "error") return bubble(message);
    return lead(message);
  };

  const items = remaining.map((message) => (
    <Fragment key={message.id}>
      {(message.hitlData || message.toolData) && lead(message)}
      {block(message)}
    </Fragment>
  ));

  if (
    !remaining.some(
      (m) =>
        m.hitlData ||
        m.toolData?.name === ASK_USER_TOOL_NAME ||
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
        />
      )}
      {created.length > 0 && <BotCreationEvents items={created} />}
      {citations.length > 0 && (
        <KnowledgeCitationsStrip citations={citations} />
      )}
    </div>
  );
}
