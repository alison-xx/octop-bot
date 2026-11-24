/** `octop-bot://` links from the website, e.g. "Import into Octop Bot" on the Bot market. */

export const DEEP_LINK_SCHEME = "octop-bot";

const SLUG = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

/** The Bot client path a link opens, or null for anything we don't handle. */
export function deepLinkPath(url: string): string | null {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return null;
  }
  if (parsed.protocol !== `${DEEP_LINK_SCHEME}:`) return null;
  // octop-bot://market/<slug>: host "market", path "/<slug>".
  const [kind, slug, ...rest] = [parsed.host, ...parsed.pathname.split("/")].filter(Boolean);
  if (kind === "market" && slug && !rest.length && SLUG.test(slug) && slug.length <= 48)
    return `/octop-bot/market/${slug}/import`;
  return null;
}

/** Windows and Linux pass the link as a launch argument. */
export function deepLinkPathFromArgv(argv: readonly string[]): string | null {
  const link = argv.find((arg) => arg.startsWith(`${DEEP_LINK_SCHEME}://`));
  return link ? deepLinkPath(link) : null;
}
