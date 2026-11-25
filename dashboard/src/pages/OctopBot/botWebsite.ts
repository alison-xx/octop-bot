/** The Octop Bot website, where plans, orders and invoices are managed. */
export const OCTOP_BOT_SITE = "https://octop-bot.lynxce.cn";

/** Lynxce's own account centre, used until the website's account page ships. */
const LYNXCE_ACCOUNT_CENTER = "https://admin.lynxce.cn";

/**
 * Where "Account center" goes. The website's account page is switched on at
 * build time (VITE_OCTOP_BOT_WEBSITE_ACCOUNT=1) once it is live; the person
 * signs in there themselves until one-time sign-in codes are available.
 */
export function accountCenterUrl(): string {
  return import.meta.env.VITE_OCTOP_BOT_WEBSITE_ACCOUNT === "1"
    ? `${OCTOP_BOT_SITE}/account.html`
    : LYNXCE_ACCOUNT_CENTER;
}
