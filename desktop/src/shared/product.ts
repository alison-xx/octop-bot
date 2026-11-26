/** The same flag selects the development product and identifies its sandboxed renderer. */
export const BOT_CLIENT_FLAG = "--octop-bot";
export const BOT_PRODUCT_NAME = "Octop Bot";
export const BOT_HOME_PATH = "/octop-bot";

export function isBotProduct(argv: readonly string[], appName: string, packageInfo: unknown): boolean {
  if (argv.includes(BOT_CLIENT_FLAG) || /^octop[ -]bot$/i.test(appName)) return true;
  return typeof packageInfo === "object" && packageInfo !== null &&
    "octopBotClient" in packageInfo && packageInfo.octopBotClient === true;
}

/** Absolute document paths supported by the dedicated shell, including login redirects. */
export function botDocumentPath(path: string): boolean {
  return path === BOT_HOME_PATH || path.startsWith(BOT_HOME_PATH + "/") ||
    path === "/login" || path === "/login/workspaces" || path === "/login/local" || path === "/login/oidc/complete" || path === "/setup" || path === "/setup/local" ||
    /^\/chat(?:\/[^/]+){0,2}\/?$/.test(path) || /^\/share\/[^/]+\/?$/.test(path);
}
