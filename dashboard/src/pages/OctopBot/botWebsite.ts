import { lynxceWalletApi } from "../../api/modules/lynxceWallet";

export const OCTOP_BOT_SITE = "https://octop-bot.lynxce.cn";

export async function openAccountWebsite(
  scope: "account" | "recharge",
  accountId: string,
) {
  // In Electron the shell opens external URLs in the system browser. A normal
  // browser must reserve its tab during the click, before requesting the code.
  const desktop = /Electron\//.test(navigator.userAgent);
  const tab = desktop ? null : window.open("about:blank", "_blank");
  if (tab) tab.opener = null;
  try {
    const { code } = await lynxceWalletApi.websiteCode(scope, accountId);
    if (!/^[A-Za-z0-9_-]{43}$/.test(code))
      throw new Error("Invalid website code");
    const url = new URL(
      scope === "account" ? "/account.html" : "/pricing.html",
      OCTOP_BOT_SITE,
    );
    url.searchParams.set("from", desktop ? "desktop" : "web");
    url.hash = (scope === "account" ? "code=" : "ticket=") + code;
    if (tab) tab.location.replace(url.href);
    else if (desktop) window.open(url.href, "_blank", "noopener,noreferrer");
    else window.location.assign(url.href);
  } catch (error) {
    tab?.close();
    throw error;
  }
}
