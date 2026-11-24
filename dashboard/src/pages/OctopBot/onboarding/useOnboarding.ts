import { useCallback, useEffect, useState } from "react";
import { botCloudApi } from "../../../api/modules/botCloud";
import {
  botOnboardingApi,
  type OnboardingChange,
  type OnboardingState,
} from "../../../api/modules/botOnboarding";
import { onStreamEvent } from "../../Chat/hooks/chatStore";
import { botGuideSeenKey } from "../../../utils/botClientRoute";
import { getDesktopBridge } from "../../../utils/desktopBridge";

/** CloudMove's "later" choice; while it is unset the desktop is about to move to the cloud. */
const CLOUD_MOVE_LATER_KEY = "octop.bot.cloud-move.later";

function stored(storage: () => Storage, key: string): string | null {
  try {
    return storage().getItem(key);
  } catch {
    return null;
  }
}

/**
 * A desktop signed in to a Lynxce account moves its team to the cloud and is guided there,
 * so this computer's page stays quiet until the owner chooses to stay here for now.
 */
async function guidedElsewhere(): Promise<boolean> {
  const bridge = getDesktopBridge();
  if (!bridge?.botOnly || !("useLynxceCloud" in bridge)) return false;
  if (stored(() => sessionStorage, CLOUD_MOVE_LATER_KEY)) return false;
  const account = await botCloudApi.account().catch(() => null);
  return Boolean(account?.connected);
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
  const reload = useCallback(async () => {
    const next = await botOnboardingApi.read().catch(() => null);
    if (next) setState(next);
    return next;
  }, []);
  useEffect(() => {
    if (!enabled || userId === null) return;
    let current = true;
    void (async () => {
      if (await guidedElsewhere()) return;
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
  const watching = state?.status === "active" && state.step === "ask";
  useEffect(() => {
    if (!watching) return;
    return onStreamEvent((event) => {
      if (event.kind === "streamEnd") void reload();
    });
  }, [watching, reload]);
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
