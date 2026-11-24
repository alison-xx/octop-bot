import { isBotClient } from "./desktopBridge";

export const BOT_HOME = "/octop-bot";
export const BOT_SETTINGS = BOT_HOME + "/settings";
export const BOT_CLOUD = BOT_HOME + "/cloud";
export const BOT_GUIDE = BOT_HOME + "/guide";
export const BOT_CAPABILITIES = BOT_HOME + "/capabilities";
export const BOT_MARKET = BOT_HOME + "/market";

/** A market template page; ``importNow`` opens its import dialog on arrival. */
export function botMarketPath(slug: string, importNow = false): string {
  return (
    BOT_MARKET + "/" + encodeURIComponent(slug) + (importNow ? "/import" : "")
  );
}

/** Capability sections of the standalone client, in navigation order. */
export const BOT_CAPABILITY_SECTIONS = [
  "connectors",
  "skills",
  "skill-packages",
  "knowledge",
  "memory",
  "channels",
  "plugins",
  "acp",
  "tasks",
] as const;
export type BotCapabilitySection = (typeof BOT_CAPABILITY_SECTIONS)[number];

/** Upstream dashboard page each section embeds; also its permission path. */
export const BOT_CAPABILITY_UPSTREAM: Record<BotCapabilitySection, string> = {
  connectors: "/connectors",
  skills: "/personalization/skills",
  "skill-packages": "/skill-packages",
  knowledge: "/knowledge-bases",
  memory: "/personalization/memory",
  channels: "/personalization/channels",
  plugins: "/admin/plugins",
  acp: "/acp",
  tasks: "/tasks",
};

const UPSTREAM_ALIASES: Record<string, BotCapabilitySection> = {
  ...Object.fromEntries(
    BOT_CAPABILITY_SECTIONS.map(
      (section) => [BOT_CAPABILITY_UPSTREAM[section], section] as const,
    ),
  ),
  "/skills": "skills",
  "/memory": "memory",
  "/channels": "channels",
  "/plugins": "plugins",
  "/personalization/acp": "acp",
  "/cron-jobs": "tasks",
};

export function botCapabilityPath(section?: BotCapabilitySection): string {
  return section ? BOT_CAPABILITIES + "/" + section : BOT_CAPABILITIES;
}

/** The capability section an upstream dashboard path opens, if any. */
export function botCapabilityForPath(
  path: string,
): BotCapabilitySection | null {
  return UPSTREAM_ALIASES[path.replace(/(.)\/$/, "$1")] ?? null;
}

const CAPABILITY_PATH = new RegExp(
  `^${BOT_CAPABILITIES}(?:/(?:${BOT_CAPABILITY_SECTIONS.join("|")}))?/?$`,
);

export function botGuideSeenKey(userId: number) {
  return `octop.bot.guide.seen.${userId}`;
}

export function botClientDestination(path: string): string {
  if (CAPABILITY_PATH.test(path)) return path;
  const capability = botCapabilityForPath(path);
  if (capability) return botCapabilityPath(capability);
  if (path.replace(/\/$/, "") === "/admin/models") return BOT_SETTINGS;
  if (
    /^\/octop-bot(?:\/settings|\/cloud|\/guide|\/market(?:\/[a-z0-9-]+(?:\/import)?)?|\/bots\/[^/?#\\]+(?:\/[^/?#\\]+)?|\/groups\/[^/?#\\]+)?\/?$/.test(
      path,
    )
  )
    return path;
  const chat = /^\/chat\/([^/?#\\]+)(?:\/([^/?#\\]+))?\/?$/.exec(path);
  if (chat)
    return BOT_HOME + "/bots/" + chat[1] + (chat[2] ? "/" + chat[2] : "");
  return BOT_HOME;
}

/**
 * Where an upstream page embedded in the capabilities area should go. A plain
 * ``/chat`` opens the Bot the page is scoped to rather than the Chief.
 */
export function botCapabilityLink(path: string, botId: string | null): string {
  if (path.replace(/(.)\/$/, "$1") === "/chat")
    return botId ? BOT_HOME + "/bots/" + encodeURIComponent(botId) : BOT_HOME;
  return botClientDestination(path);
}

const RETURN_KEY = "octop.bot.login-return";
export function rememberBotLoginPath(path: string) {
  if (isBotClient())
    sessionStorage.setItem(RETURN_KEY, botClientDestination(path));
}
export function loginDestination(fallback = "/chat", consume = true): string {
  if (!isBotClient()) return fallback;
  const saved = sessionStorage.getItem(RETURN_KEY);
  if (consume) sessionStorage.removeItem(RETURN_KEY);
  return botClientDestination(saved ?? fallback);
}
