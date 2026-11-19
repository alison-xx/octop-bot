import { isBotOnlyDesktop } from "./desktopBridge";

export const BOT_HOME = "/octop-bot";
export const BOT_SETTINGS = BOT_HOME + "/settings";
export const BOT_CLOUD = BOT_HOME + "/cloud";
export const BOT_GUIDE = BOT_HOME + "/guide";

export function botGuideSeenKey(userId: number) {
  return `octop.bot.guide.seen.${userId}`;
}

export function botClientDestination(path: string): string {
  if (
    /^\/octop-bot(?:\/settings|\/cloud|\/guide|\/bots\/[^/?#\\]+(?:\/[^/?#\\]+)?|\/groups\/[^/?#\\]+)?\/?$/.test(
      path,
    )
  )
    return path;
  const chat = /^\/chat\/([^/?#\\]+)(?:\/([^/?#\\]+))?\/?$/.exec(path);
  if (chat)
    return BOT_HOME + "/bots/" + chat[1] + (chat[2] ? "/" + chat[2] : "");
  return BOT_HOME;
}

const RETURN_KEY = "octop.bot.login-return";
export function rememberBotLoginPath(path: string) {
  if (isBotOnlyDesktop())
    sessionStorage.setItem(RETURN_KEY, botClientDestination(path));
}
export function loginDestination(fallback = "/chat", consume = true): string {
  if (!isBotOnlyDesktop()) return fallback;
  const saved = sessionStorage.getItem(RETURN_KEY);
  if (consume) sessionStorage.removeItem(RETURN_KEY);
  return botClientDestination(saved ?? fallback);
}
