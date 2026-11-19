import { useCallback, useSyncExternalStore } from "react";
import { getSnapshot, subscribe } from "../Chat/hooks/chatStore";
import { hasPendingHitl } from "../Chat/utils/pendingHitl";
import type { BotMotion } from "./BotCharacter";
export function useBotMotion(thread?: string): BotMotion {
  const listen = useCallback(
    (fn: () => void) => (thread ? subscribe(thread, fn) : () => {}),
    [thread],
  );
  const current = useCallback((): BotMotion => {
    if (!thread) return "idle";
    const { messages, isStreaming, thinkingStartedAt } = getSnapshot(thread);
    if (hasPendingHitl(messages)) return "waiting";
    if (!isStreaming) return "idle";
    const action = messages.at(-1)?.toolData;
    if (
      action &&
      action.output === undefined &&
      /search|fetch|browse|read|grep|glob|list|recall/i.test(action.name ?? "")
    )
      return "searching";
    return thinkingStartedAt ? "thinking" : "working";
  }, [thread]);
  return useSyncExternalStore(listen, current, current);
}
