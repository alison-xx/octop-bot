import { useEffect, useState } from "react";
import { Button, Dropdown, type MenuProps } from "antd";
import {
  ArrowRight,
  Blocks,
  Coins,
  ExternalLink,
  IdCard,
  LockKeyhole,
  LogOut,
  Settings2,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  useLocation,
  useNavigate,
  type NavigateFunction,
} from "react-router-dom";
import { authApi } from "../../api/modules/auth";
import { preferencesApi } from "../../api/modules/preferences";
import { message } from "@/utils/antdMessage";
import { clearAuthToken } from "../../api/request";
import { holdDesktopLocalAutoLogin } from "../../api/desktopSession";
import { useCurrentUser } from "../../hooks/useCurrentUser";
import { applyGuestLocale, applyUserLocale } from "../../utils/locale";
import { isBotOnlyDesktop } from "../../utils/desktopBridge";
import { BOT_CAPABILITIES, BOT_SETTINGS } from "../../utils/botClientRoute";
import { accountInitials } from "../Chat/utils/accountDisplayName";
import { ProfileAvatar } from "../Admin/Users/ProfileAvatar";
import { botCloudApi } from "../../api/modules/botCloud";
import lynxceLogo from "../../assets/providers/lynxce.png";
import { BotCharacter, octopCharacter } from "./BotCharacter";
import styles from "./accountMenu.module.less";
import { CreditsAmount, useRecharge } from "./CreditsWidgets";
import { accountCenterUrl } from "./botWebsite";
import {
  formatCredits,
  resetCredits,
  useLynxceCredits,
} from "./useLynxceCredits";

const AVATAR_CACHE = "octop-bot:lynxce-avatar";

/** The last Lynxce avatar seen on this device, so the sidebar does not flash initials. */
function cachedAvatar(): string | null {
  try {
    return window.localStorage.getItem(AVATAR_CACHE);
  } catch {
    return null;
  }
}

function cacheAvatar(url: string | null) {
  try {
    if (url) window.localStorage.setItem(AVATAR_CACHE, url);
    else window.localStorage.removeItem(AVATAR_CACHE);
  } catch {
    // Private windows and blocked storage just show initials until the account loads.
  }
}

export async function signOutBotClient(
  username: string | undefined,
  navigate: NavigateFunction,
) {
  if (username === "local") holdDesktopLocalAutoLogin();
  // A shared computer must not show the last person's avatar after sign-out.
  cacheAvatar(null);
  resetCredits();
  await authApi.logout();
  clearAuthToken();
  await applyGuestLocale();
  navigate("/login", { replace: true });
}

/** A person's name for the Bot client: never an internal id such as ``sso_1a2b…``. */
export function botAccountName(
  user:
    | { display_name?: string | null; username?: string | null }
    | null
    | undefined,
  fallback: string,
): string {
  const named = user?.display_name?.trim();
  if (named) return named;
  const username = user?.username?.trim() ?? "";
  return /^sso_[0-9a-f]+$/i.test(username) ? fallback : username;
}

export const LANGUAGES = [
  ["zh", "简体中文"],
  ["en", "English"],
] as const;

/** The signed-in user's interface language, saved as their preference. */
export function useLanguage() {
  const { i18n, t } = useTranslation();
  const current = i18n?.language?.startsWith("zh") ? "zh" : "en";
  const change = async (lang: string) => {
    try {
      const prefs = await preferencesApi.setLocale(lang);
      await applyUserLocale(prefs.locale);
    } catch {
      message.error(
        t("language.saveFailed", "Failed to save language preference"),
      );
    }
  };
  return [current, change] as const;
}

/** Sidebar footer: who is signed in, with settings and account actions. */
export default function AccountMenu({
  compact = false,
}: {
  compact?: boolean;
}) {
  const { t, i18n } = useTranslation();
  const user = useCurrentUser();
  const navigate = useNavigate();
  const location = useLocation();
  // Signed in to Lynxce: that account's name, with the Lynxce mark. Otherwise
  // the local account ("local"), never a team or other borrowed name.
  const [lynxceName, setLynxceName] = useState<string | null>(null);
  const [lynxceAvatar, setLynxceAvatar] = useState<string | null>(() =>
    isBotOnlyDesktop() ? cachedAvatar() : null,
  );
  const [lynxceAccount, setLynxceAccount] = useState<string | null>(null);
  const desktop = isBotOnlyDesktop();
  useEffect(() => {
    if (!desktop) return;
    let current = true;
    botCloudApi.account().then(
      (a) => {
        if (!current) return;
        setLynxceName(a.connected ? a.display_name || a.account_id : null);
        setLynxceAccount(a.connected ? a.account_id : null);
        const avatar = (a.connected && a.avatar_url) || null;
        setLynxceAvatar(avatar);
        cacheAvatar(avatar);
      },
      () => current && setLynxceName(null),
    );
    return () => {
      current = false;
    };
  }, [desktop]);
  const lynxce = desktop ? Boolean(lynxceName) : true;
  const [open, setOpen] = useState(false);
  const { recharge, opening } = useRecharge();
  const name = desktop
    ? lynxceName || user?.username || ""
    : botAccountName(user, t("botClient.account.lynxceUser"));
  const source = t(
    lynxce ? "botClient.account.lynxce" : "botClient.account.local",
  );
  const from = { state: { from: location.pathname } };
  const credits = useLynxceCredits();
  const billed = credits.status !== "none" && credits.status !== "idle";
  const entry = (label: string, hint: string) => (
    <span className={styles.entry}>
      {label}
      <small>{hint}</small>
    </span>
  );
  // Appearance, language, the floating orb and private folders live in
  // Settings > General; the menu only points at the main places.
  const items: MenuProps["items"] = [
    {
      key: "settings",
      icon: <Settings2 size={16} />,
      label: entry(
        t("botClient.menu.settings"),
        t("botClient.menu.settingsHint"),
      ),
      onClick: () => navigate(BOT_SETTINGS, from),
    },
    {
      key: "capabilities",
      icon: <Blocks size={16} />,
      label: entry(
        t("botCapabilities.title"),
        t("botClient.menu.capabilitiesHint"),
      ),
      onClick: () => navigate(BOT_CAPABILITIES, from),
    },
    ...(billed
      ? [
          {
            key: "credits",
            icon: <Coins size={16} />,
            label: entry(t("botCredits.menu"), t("botCredits.menuHint")),
            onClick: () =>
              navigate(BOT_SETTINGS, {
                state: { from: location.pathname, tab: "account" },
              }),
          },
        ]
      : []),
    // Orders, plans and invoices live on the website, opened in the system browser.
    ...(lynxce
      ? [
          {
            key: "account",
            icon: <IdCard size={16} />,
            label: entry(
              t("botClient.menu.accountCenter"),
              t("botClient.menu.accountCenterHint"),
            ),
            extra: <ExternalLink size={13} aria-hidden="true" />,
            onClick: () =>
              void window.open(accountCenterUrl(), "_blank", "noopener"),
          },
        ]
      : []),
    // Desktop without Lynxce signs in from the card above; there is nothing to sign out of.
    ...(desktop && !lynxce
      ? []
      : [
          { type: "divider" as const },
          {
            key: "logout",
            danger: true,
            icon: <LogOut size={16} />,
            label: t(desktop ? "botClient.menu.lynxceSignOut" : "auth.logout"),
            onClick: async () => {
              if (desktop && lynxceAccount) {
                try {
                  await botCloudApi.logout(lynxceAccount);
                  window.dispatchEvent(new Event("octop-bot-account-changed"));
                } catch {
                  message.error(t("octopBot.failed"));
                  return;
                }
              }
              await signOutBotClient(user?.username, navigate);
            },
          },
        ]),
  ];
  const avatar =
    desktop && lynxce && lynxceAvatar ? (
      <span className={styles.avatar}>
        <img src={lynxceAvatar} alt="" onError={() => setLynxceAvatar(null)} />
      </span>
    ) : lynxce && (user?.avatar_url || user?.avatar_icon) ? (
      <ProfileAvatar
        className={styles.avatar}
        url={user.avatar_url}
        icon={user.avatar_icon}
      />
    ) : lynxce ? (
      <span className={styles.avatar}>{accountInitials(name)}</span>
    ) : (
      <span className={styles.avatar} data-chief>
        <BotCharacter
          look={{ ...octopCharacter, source: "character" }}
          size={26}
          badges={false}
        />
      </span>
    );
  const badge = lynxce && (
    <img className={styles.badge} src={lynxceLogo} alt="" />
  );
  // Top of the menu: who is signed in and what the account can spend.
  const card = lynxce ? (
    <div className={styles.card}>
      <div className={styles.cardWho}>
        <span className={styles.avatarWrap} data-size="large">
          {avatar}
          {badge}
        </span>
        <span className={styles.who}>
          <strong className={styles.name}>{name}</strong>
          <small>{source}</small>
        </span>
      </div>
      {credits.wallet && (
        <div className={styles.balance}>
          <strong>
            {formatCredits(credits.wallet.credits, i18n.language)}
            <small>{t("botClient.menu.credits")}</small>
          </strong>
        </div>
      )}
      {credits.wallet && (
        <div className={styles.cardActions}>
          <Button
            type="primary"
            loading={opening}
            onClick={() => {
              setOpen(false);
              void recharge();
            }}
          >
            {t("botCredits.recharge")}
          </Button>
          <Button
            onClick={() => {
              setOpen(false);
              navigate(BOT_SETTINGS, {
                state: { from: location.pathname, tab: "account" },
              });
            }}
          >
            {t("botClient.menu.usage")}
          </Button>
        </div>
      )}
    </div>
  ) : (
    <div className={styles.card} data-local>
      <div className={styles.cardWho}>
        <span className={styles.avatarWrap} data-size="large">
          {avatar}
        </span>
        <span className={styles.who}>
          <strong className={styles.name}>{name}</strong>
          <small>
            <LockKeyhole size={11} aria-hidden="true" />
            {source}
          </small>
        </span>
      </div>
      <p>{t("botClient.menu.localHint")}</p>
      <Button
        type="primary"
        onClick={() => {
          setOpen(false);
          void signOutBotClient(user?.username, navigate);
        }}
      >
        {t("botClient.menu.lynxceSignIn")}
        <ArrowRight size={15} aria-hidden="true" />
      </Button>
    </div>
  );
  return (
    <Dropdown
      trigger={["click"]}
      placement="topLeft"
      open={open}
      onOpenChange={setOpen}
      menu={{
        items,
        className: styles.menu,
        onClick: () => setOpen(false),
      }}
      popupRender={(menu) => (
        <div className={styles.panel}>
          {card}
          {menu}
        </div>
      )}
      overlayClassName={styles.overlay}
    >
      <button
        type="button"
        className={styles.trigger}
        data-compact={compact || undefined}
        aria-label={name + " · " + t("botClient.menu.settings")}
        title={compact ? name + " · " + source : undefined}
      >
        <span className={styles.avatarWrap}>
          {avatar}
          {badge}
        </span>
        {!compact && (
          <span className={styles.who}>
            <span className={styles.name}>{name}</span>
            <small>
              {credits.wallet ? <CreditsAmount credits={credits} /> : source}
            </small>
          </span>
        )}
      </button>
    </Dropdown>
  );
}
