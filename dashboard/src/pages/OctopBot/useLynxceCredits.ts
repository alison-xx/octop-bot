import { useEffect, useSyncExternalStore } from "react";
import {
  lynxceWalletApi,
  type LynxceWallet,
  type WalletSource,
} from "../../api/modules/lynxceWallet";
import { botCloudApi } from "../../api/modules/botCloud";
import { botCloudComputerApi } from "../../api/modules/botCloudComputer";
import { lynxceBotApi } from "../../api/modules/lynxceBot";
import { isBotOnlyDesktop } from "../../utils/desktopBridge";

/** Below this many credits every client warns and offers a recharge (plan §7.4). */
export const LOW_CREDITS = 100;

export type CreditsState = {
  /** none: this account is not billed in Lynxce credits (e.g. a self-hosted provider). */
  status: "idle" | "none" | "loading" | "ready" | "error";
  wallet: LynxceWallet | null;
};

let state: CreditsState = { status: "idle", wallet: null };
let inflight: Promise<void> | null = null;
let generation = 0;
const listeners = new Set<() => void>();

function set(next: CreditsState) {
  state = next;
  listeners.forEach((listener) => listener());
}

/** Which wallet pays for this signed-in user's chats, if any. */
async function walletSource(): Promise<WalletSource | null> {
  if (isBotOnlyDesktop()) {
    const account = await botCloudApi.account().catch(() => null);
    if (account?.connected) return "cloud";
    const oauth = await lynxceBotApi.status().catch(() => null);
    return oauth?.connected ? "model" : null;
  }
  const info = await botCloudComputerApi.serverInfo().catch(() => null);
  return info?.edition === "cloud" ? "cloud" : null;
}

/** Reload the balance; concurrent callers share one request. */
export function refreshCredits(): Promise<void> {
  if (inflight) return inflight;
  const run = ++generation;
  set({
    status: state.wallet ? state.status : "loading",
    wallet: state.wallet,
  });
  inflight = (async () => {
    try {
      const source = await walletSource();
      if (run !== generation) return;
      if (!source) {
        set({ status: "none", wallet: null });
        return;
      }
      const wallet = await lynxceWalletApi.balance(source);
      if (run !== generation) return;
      set(
        wallet.status === "available" && Number.isFinite(wallet.credits)
          ? { status: "ready", wallet }
          : { status: "error", wallet: state.wallet },
      );
    } catch {
      if (run === generation) set({ status: "error", wallet: state.wallet });
    } finally {
      inflight = null;
    }
  })();
  return inflight;
}

/** Forget the balance (sign-out, account switch). */
export function resetCredits() {
  generation += 1;
  inflight = null;
  set({ status: "idle", wallet: null });
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

let watchers = 0;
function onFocus() {
  void refreshCredits();
}
function onVisible() {
  if (document.visibilityState === "visible") void refreshCredits();
}

/**
 * The signed-in account's Lynxce credits, shared by every surface that shows them.
 * Loads once, then refreshes whenever the window regains focus (e.g. back from checkout).
 */
export function useLynxceCredits(): CreditsState {
  const current = useSyncExternalStore(subscribe, () => state);
  useEffect(() => {
    if (state.status === "idle") void refreshCredits();
    if (watchers++ === 0) {
      window.addEventListener("focus", onFocus);
      document.addEventListener("visibilitychange", onVisible);
    }
    return () => {
      if (--watchers === 0) {
        window.removeEventListener("focus", onFocus);
        document.removeEventListener("visibilitychange", onVisible);
      }
    };
  }, []);
  return current;
}

/** 4,454,029 · 1,280 · 12.50 — decimals only for small balances. */
export function formatCredits(value: number, language?: string): string {
  const small = Math.abs(value) < 1000 && !Number.isInteger(value);
  return new Intl.NumberFormat(language, {
    minimumFractionDigits: small ? 2 : 0,
    maximumFractionDigits: small ? 2 : 0,
  }).format(value);
}

export function isLowCredits(credits: CreditsState): boolean {
  return credits.status === "ready" && !!credits.wallet
    ? credits.wallet.credits < LOW_CREDITS
    : false;
}
