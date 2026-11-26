import { useCallback, useEffect, useState } from "react";
import {
  botOnboardingApi,
  type OnboardingChange,
  type OnboardingState,
} from "../../../api/modules/botOnboarding";
import { onStreamEvent, onToolEvent } from "../../Chat/hooks/chatStore";
import { botGuideSeenKey } from "../../../utils/botClientRoute";

function stored(storage: () => Storage, key: string): string | null {
  try {
    return storage().getItem(key);
  } catch {
    return null;
  }
}

export interface Onboarding {
  state: OnboardingState | null;
  change: (change: OnboardingChange) => Promise<OnboardingState | null>;
}

/**
 * The owner's new-user onboarding, read once the workspace is open and again after each
 * reply (Chief may have just built the team). Failures leave the guide hidden.
 */
export function useOnboarding(
  enabled: boolean,
  userId: number | null,
): Onboarding {
  const [state, setState] = useState<OnboardingState | null>(null);
  useEffect(() => {
    if (!enabled || userId === null) return;
    let current = true;
    void (async () => {
      let next = await botOnboardingApi.read().catch(() => null);
      // The older desktop guide was already seen here: do not guide this owner again.
      if (
        next?.status === "pending" &&
        stored(() => localStorage, botGuideSeenKey(userId))
      )
        next = await botOnboardingApi
          .change({ action: "skip", reason: "legacy" })
          .catch(() => null);
      if (current && next) setState(next);
    })();
    return () => {
      current = false;
    };
  }, [enabled, userId]);
  const watching =
    state?.show && state.status === "active" && state.step === "ask";
  useEffect(() => {
    if (!enabled || userId === null || !watching) return;
    let current = true;
    let reading = false;
    const refresh = async () => {
      if (reading) return;
      reading = true;
      const next = await botOnboardingApi.read().catch(() => null);
      reading = false;
      if (current && next) {
        setState((prev) =>
          prev?.show && prev.status === "active" && prev.step === "ask"
            ? next
            : prev,
        );
      }
    };
    const stopTools = onToolEvent((event) => {
      if (
        event.kind === "toolDone" &&
        event.toolName === "octop_bot_create_team"
      )
        void refresh();
    });
    const stopStream = onStreamEvent((event) => {
      if (event.kind === "streamEnd") void refresh();
    });
    // The committed team remains available even if the socket missed its tool event.
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void refresh();
    }, 3000);
    return () => {
      current = false;
      window.clearInterval(timer);
      stopTools();
      stopStream();
    };
  }, [enabled, userId, watching]);
  const change = useCallback(async (next: OnboardingChange) => {
    try {
      const updated = await botOnboardingApi.change(next);
      setState(updated);
      return updated;
    } catch {
      // Keep going on screen; a later step sends the state again.
      if (next.action === "skip" || next.action === "complete")
        setState((prev) => prev && { ...prev, show: false });
      return null;
    }
  }, []);
  return { state, change };
}
