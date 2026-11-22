/**
 * Pure unread bookkeeping for the Octop Bot client. Groups carry a server-side
 * read cursor. Bot chats only count proactive pushes on the server, so a reply
 * that finished while another conversation was open is detected here by
 * comparing the bot's latest turn time with the last one this viewer saw.
 */
import type { BotActivitySnapshot } from "@/api/modules/botActivity";

/** ``bot:<agent_id>`` or ``group:<group_id>`` */
export type ActivityTarget = string;
/** Per bot: the latest ``last_active`` this viewer has already seen. */
export type SeenCursors = Record<string, number>;

export const botTarget = (agentId: string): ActivityTarget => `bot:${agentId}`;
export const groupTarget = (groupId: string): ActivityTarget =>
  `group:${groupId}`;

export function parseTarget(
  target: string,
): { kind: "bot" | "group"; id: string } | null {
  const match = /^(bot|group):(.+)$/.exec(target);
  return match ? { kind: match[1] as "bot" | "group", id: match[2] } : null;
}

/**
 * Advance the seen cursors. Bots unknown on the first snapshot of a launch
 * start at their current time so an install never opens with a burst of
 * badges; bots that appear later start from zero so their first reply counts.
 */
export function advanceSeen(
  snapshot: BotActivitySnapshot,
  seen: SeenCursors,
  openTarget: ActivityTarget | null,
  firstSnapshot: boolean,
): SeenCursors {
  const next: SeenCursors = {};
  for (const bot of snapshot.bots) {
    const latest = bot.last_active ?? 0;
    const known = seen[bot.agent_id];
    let value = known ?? (firstSnapshot ? latest : 0);
    if (openTarget === botTarget(bot.agent_id)) value = latest;
    next[bot.agent_id] = value;
  }
  return next;
}

/** Unread count per target. The open conversation is always read. */
export function unreadByTarget(
  snapshot: BotActivitySnapshot,
  seen: SeenCursors,
  openTarget: ActivityTarget | null,
): Record<ActivityTarget, number> {
  const counts: Record<ActivityTarget, number> = {};
  for (const bot of snapshot.bots) {
    const target = botTarget(bot.agent_id);
    const fresh = (bot.last_active ?? 0) > (seen[bot.agent_id] ?? 0) ? 1 : 0;
    const count = target === openTarget ? 0 : Math.max(bot.unread_count, fresh);
    if (count > 0) counts[target] = count;
  }
  for (const group of snapshot.groups) {
    const target = groupTarget(group.group_id);
    if (target !== openTarget && group.unread_count > 0) {
      counts[target] = group.unread_count;
    }
  }
  return counts;
}

/** Targets whose unread count went up since the previous poll. */
export function newArrivals(
  previous: Record<ActivityTarget, number>,
  next: Record<ActivityTarget, number>,
): ActivityTarget[] {
  return Object.keys(next).filter(
    (target) => next[target] > (previous[target] ?? 0),
  );
}

export function totalUnread(counts: Record<ActivityTarget, number>): number {
  return Object.values(counts).reduce((sum, value) => sum + value, 0);
}

/** ``(3) Octop Bot`` style title; the base title comes back at zero. */
export function badgedTitle(base: string, total: number): string {
  if (total <= 0) return base;
  return `(${total > 99 ? "99+" : total}) ${base}`;
}

export function previewText(text: string, max = 120): string {
  const flat = text
    .replace(/[`*_>#~]+/g, "")
    .replace(/\s+/g, " ")
    .trim();
  return flat.length > max ? `${flat.slice(0, max - 1)}…` : flat;
}
