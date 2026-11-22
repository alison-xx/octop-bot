import { App } from "antd";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  botActivityApi,
  type BotActivitySnapshot,
} from "@/api/modules/botActivity";
import { octopAgentsApi } from "@/api/modules/octopAgents";
import {
  advanceSeen,
  badgedTitle,
  botTarget,
  groupTarget,
  newArrivals,
  parseTarget,
  previewText,
  totalUnread,
  unreadByTarget,
  type ActivityTarget,
  type SeenCursors,
} from "@/utils/botActivity";
import { getDesktopBridge } from "@/utils/desktopBridge";

const SEEN_KEY = "octop-bot:activity-seen:v1";
const PREFS_KEY = "octop-bot:notify-prefs:v1";
const VISIBLE_POLL_MS = 5_000;
const HIDDEN_POLL_MS = 15_000;

export interface BotNotifyPrefs {
  /** OS / browser notifications while the window is in the background. */
  system: boolean;
  /** A short chime when a new reply arrives. */
  sound: boolean;
}

const DEFAULT_PREFS: BotNotifyPrefs = { system: true, sound: true };

function readJson<T>(key: string, fallback: T): T {
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? { ...fallback, ...(JSON.parse(raw) as T) } : fallback;
  } catch {
    return fallback;
  }
}

function writeJson(key: string, value: unknown): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Private windows and blocked storage only lose this convenience.
  }
}

export function readBotNotifyPrefs(): BotNotifyPrefs {
  return readJson(PREFS_KEY, DEFAULT_PREFS);
}

export function saveBotNotifyPrefs(
  patch: Partial<BotNotifyPrefs>,
): BotNotifyPrefs {
  const next = { ...readBotNotifyPrefs(), ...patch };
  writeJson(PREFS_KEY, next);
  return next;
}

let audio: AudioContext | null = null;

/** Two soft sine notes; no asset to ship and quiet enough for an office. */
function playChime(): void {
  try {
    const Ctor =
      window.AudioContext ??
      (window as unknown as { webkitAudioContext?: typeof AudioContext })
        .webkitAudioContext;
    if (!Ctor) return;
    audio ??= new Ctor();
    if (audio.state === "suspended") void audio.resume();
    const start = audio.currentTime + 0.01;
    [880, 1318.5].forEach((frequency, index) => {
      const osc = audio!.createOscillator();
      const gain = audio!.createGain();
      const at = start + index * 0.11;
      osc.type = "sine";
      osc.frequency.value = frequency;
      gain.gain.setValueAtTime(0.0001, at);
      gain.gain.exponentialRampToValueAtTime(0.08, at + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, at + 0.28);
      osc.connect(gain).connect(audio!.destination);
      osc.start(at);
      osc.stop(at + 0.3);
    });
  } catch {
    // Autoplay policy or no audio device: the visual notice still shows.
  }
}

function sameRecord<T>(a: Record<string, T>, b: Record<string, T>): boolean {
  const keys = Object.keys(a);
  return (
    keys.length === Object.keys(b).length && keys.every((k) => a[k] === b[k])
  );
}

function windowInBackground(): boolean {
  return document.hidden || !document.hasFocus();
}

export interface BotActivityOptions {
  enabled: boolean;
  /** Conversation on screen now; it never counts as unread. */
  openTarget: ActivityTarget | null;
  /** Display name of a bot or group, or null when it is not in the workspace. */
  nameOf: (kind: "bot" | "group", id: string) => string | null;
  /** Open a conversation from a notification. */
  onOpen: (target: ActivityTarget) => void;
}

export interface BotActivityState {
  /** Unread count per ``bot:<id>`` / ``group:<id>``. */
  unread: Record<ActivityTarget, number>;
  /** Latest activity time (seconds) per target, for recency ordering. */
  recent: Record<ActivityTarget, number>;
  /** Latest group message as one plain line, per ``group:<id>``. */
  groupPreview: Record<ActivityTarget, string>;
  total: number;
  /** Poll now, e.g. after sending or when the window regains focus. */
  refresh: () => void;
}

/**
 * Unread badges, the app badge, the window title count and new-message
 * notifications for the Octop Bot client.
 */
export function useBotActivity({
  enabled,
  openTarget,
  nameOf,
  onOpen,
}: BotActivityOptions): BotActivityState {
  const { t } = useTranslation();
  const { notification } = App.useApp();
  const [unread, setUnread] = useState<Record<ActivityTarget, number>>({});
  const [recent, setRecent] = useState<Record<ActivityTarget, number>>({});
  const [groupPreview, setGroupPreview] = useState<
    Record<ActivityTarget, string>
  >({});
  const snapshotRef = useRef<BotActivitySnapshot | null>(null);
  const seenRef = useRef<SeenCursors>(readJson<SeenCursors>(SEEN_KEY, {}));
  const countsRef = useRef<Record<ActivityTarget, number> | null>(null);
  const openRef = useRef(openTarget);
  const nameRef = useRef(nameOf);
  const openHandlerRef = useRef(onOpen);
  const tRef = useRef(t);
  const pollRef = useRef<() => void>(() => undefined);
  const baseTitle = useRef(document.title.replace(/^\(\d+\+?\) /, ""));
  openRef.current = openTarget;
  nameRef.current = nameOf;
  openHandlerRef.current = onOpen;
  tRef.current = t;

  const announce = useCallback(
    (target: ActivityTarget, snapshot: BotActivitySnapshot, count: number) => {
      const parsed = parseTarget(target);
      if (!parsed) return;
      const tr = tRef.current;
      const title = nameRef.current(parsed.kind, parsed.id);
      if (!title) return;
      let body = tr("botNotify.botReplied");
      if (parsed.kind === "group") {
        const last = snapshot.groups.find((g) => g.group_id === parsed.id)
          ?.last_message;
        const speaker = last?.agent_id
          ? nameRef.current("bot", last.agent_id)
          : null;
        const text = last ? previewText(last.text) : "";
        body = text
          ? speaker
            ? `${speaker}: ${text}`
            : text
          : tr("botNotify.groupFallback");
      }
      if (count > 1)
        body = `${tr("botNotify.newMessages", { count })} · ${body}`;
      const prefs = readBotNotifyPrefs();
      const bridge = getDesktopBridge();
      if (windowInBackground() && prefs.system) {
        if (bridge?.notify) {
          bridge.notify({ title, body, target, silent: !prefs.sound });
          return;
        }
        if (
          typeof Notification !== "undefined" &&
          Notification.permission === "granted"
        ) {
          try {
            const notice = new Notification(title, {
              body,
              tag: target,
              silent: !prefs.sound,
            });
            notice.onclick = () => {
              window.focus();
              notice.close();
              openHandlerRef.current(target);
            };
            return;
          } catch {
            // Fall through to the in-app notice.
          }
        }
      }
      if (prefs.sound) playChime();
      notification.open({
        key: `bot-activity-${target}`,
        placement: "topRight",
        message: title,
        description: body,
        duration: 5,
        onClick: () => {
          notification.destroy(`bot-activity-${target}`);
          openHandlerRef.current(target);
        },
      });
    },
    [notification],
  );

  const apply = useCallback(
    (snapshot: BotActivitySnapshot) => {
      const first = countsRef.current === null;
      const open = openRef.current;
      const seen = advanceSeen(snapshot, seenRef.current, open, first);
      seenRef.current = seen;
      writeJson(SEEN_KEY, seen);
      const counts = unreadByTarget(snapshot, seen, open);
      if (!first) {
        for (const target of newArrivals(countsRef.current ?? {}, counts)) {
          announce(target, snapshot, counts[target]);
        }
      }
      countsRef.current = counts;
      snapshotRef.current = snapshot;
      setUnread((prev) => (sameRecord(prev, counts) ? prev : counts));
      const times: Record<ActivityTarget, number> = {};
      const lines: Record<ActivityTarget, string> = {};
      for (const bot of snapshot.bots) {
        if (bot.last_active) times[botTarget(bot.agent_id)] = bot.last_active;
      }
      for (const group of snapshot.groups) {
        const last = group.last_message;
        if (!last) continue;
        const target = groupTarget(group.group_id);
        times[target] = last.created_at;
        const speaker = last.agent_id
          ? nameRef.current("bot", last.agent_id)
          : null;
        const text = previewText(last.text, 160);
        if (text) lines[target] = speaker ? `${speaker}: ${text}` : text;
      }
      setRecent((prev) => (sameRecord(prev, times) ? prev : times));
      setGroupPreview((prev) => (sameRecord(prev, lines) ? prev : lines));
      const parsed = open ? parseTarget(open) : null;
      if (parsed && !document.hidden) {
        if (parsed.kind === "group") {
          const group = snapshot.groups.find((g) => g.group_id === parsed.id);
          if (group && group.unread_count > 0) {
            group.unread_count = 0;
            void botActivityApi.markGroupRead(parsed.id).catch(() => undefined);
          }
        } else {
          const bot = snapshot.bots.find((b) => b.agent_id === parsed.id);
          if (bot && bot.unread_count > 0) {
            bot.unread_count = 0;
            void octopAgentsApi.markRead(parsed.id).catch(() => undefined);
          }
        }
      }
    },
    [announce],
  );

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let inFlight = false;
    const schedule = () => {
      clearTimeout(timer);
      timer = setTimeout(
        poll,
        document.hidden ? HIDDEN_POLL_MS : VISIBLE_POLL_MS,
      );
    };
    async function poll() {
      if (cancelled || inFlight) return;
      inFlight = true;
      try {
        const snapshot = await botActivityApi.read();
        if (!cancelled) apply(snapshot);
      } catch {
        // Offline or signed out: keep the last badges and try again later.
      } finally {
        inFlight = false;
        if (!cancelled) schedule();
      }
    }
    pollRef.current = () => void poll();
    const wake = () => void poll();
    void poll();
    document.addEventListener("visibilitychange", wake);
    window.addEventListener("focus", wake);
    const stopOpen = getDesktopBridge()?.onNotificationOpen?.((target) =>
      openHandlerRef.current(target),
    );
    return () => {
      cancelled = true;
      clearTimeout(timer);
      pollRef.current = () => undefined;
      document.removeEventListener("visibilitychange", wake);
      window.removeEventListener("focus", wake);
      stopOpen?.();
    };
  }, [enabled, apply]);

  // Opening a conversation clears it at once instead of on the next poll.
  useEffect(() => {
    const snapshot = snapshotRef.current;
    if (snapshot) apply(snapshot);
  }, [openTarget, apply]);

  const total = totalUnread(unread);
  useEffect(() => {
    if (!enabled) return;
    getDesktopBridge()?.setUnreadBadge?.(total);
    document.title = badgedTitle(baseTitle.current, total);
  }, [enabled, total]);
  useEffect(
    () => () => {
      getDesktopBridge()?.setUnreadBadge?.(0);
      document.title = baseTitle.current;
    },
    [],
  );

  const refresh = useCallback(() => pollRef.current(), []);
  return { unread, recent, groupPreview, total, refresh };
}

export { botTarget, groupTarget };
