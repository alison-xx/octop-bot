/** Select the isolated browser only on a Bot chat or its browser workbench. */
export function currentBrowserBotId(): string | null {
  if (typeof window === "undefined") return null;
  const { pathname, search } = window.location;
  const match = /\/octop-bot\/bots\/([^/]+)(?:\/|$)/.exec(pathname);
  if (match) {
    try {
      return decodeURIComponent(match[1]);
    } catch {
      return null;
    }
  }
  return pathname.endsWith("/workbench/browser")
    ? new URLSearchParams(search).get("bot_id")
    : null;
}

export function scopedBrowserUrl(
  url: string,
  botId = currentBrowserBotId(),
): string {
  if (!botId) return url;
  const separator = url.includes("?") ? "&" : "?";
  return url + separator + new URLSearchParams({ bot_id: botId });
}

export function resolveBrowserProfile(
  userId?: number | null,
  botId = currentBrowserBotId(),
): string | null {
  if (userId == null || userId <= 0) return null;
  if (!botId) return `user-${userId}`;
  const bytes = new TextEncoder().encode(botId);
  const id = Array.from(bytes, (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
  return `user-${userId}-bot-${id}`;
}
