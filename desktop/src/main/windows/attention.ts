/**
 * New-message attention for the Octop Bot client: OS notification, unread app
 * badge and a dock bounce / taskbar flash. The page decides *what* is new; the
 * shell only validates the payload and talks to the OS.
 */

import type { BotNotification } from "../../shared/ipc-contract";

const MAX_TITLE = 120;
const MAX_BODY = 280;
const MAX_TARGET = 200;

function clip(value: unknown, max: number): string {
  if (typeof value !== "string") return "";
  const flat = value.replace(/\s+/g, " ").trim();
  return flat.length > max ? `${flat.slice(0, max - 1)}…` : flat;
}

/** Reject anything that is not a short, plain notification from the page. */
export function sanitizeNotification(input: unknown): BotNotification | null {
  if (!input || typeof input !== "object") return null;
  const raw = input as Record<string, unknown>;
  const title = clip(raw.title, MAX_TITLE);
  const target = clip(raw.target, MAX_TARGET);
  if (!title || !/^(bot|group):[\w-]+$/.test(target)) return null;
  return { title, body: clip(raw.body, MAX_BODY), target, silent: raw.silent === true };
}

/** Whole, non-negative count; macOS and Linux show it on the app icon. */
export function sanitizeBadgeCount(input: unknown): number {
  if (typeof input !== "number" || !Number.isFinite(input)) return 0;
  return Math.min(Math.max(Math.floor(input), 0), 9999);
}

/** Tray tooltip that carries the unread total where the OS has no app badge. */
export function trayTooltip(product: string, count: number, locale: string): string {
  if (count <= 0) return product;
  return locale.startsWith("zh") ? `${product} · ${count} 条未读` : `${product} · ${count} unread`;
}
