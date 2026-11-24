import { useEffect, useState } from "react";
import { Dropdown, type MenuProps } from "antd";
import { Blocks, Cloud, Coins, LogIn, LogOut, Settings2 } from "lucide-react";
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
import {
  BOT_CAPABILITIES,
  BOT_CLOUD,
  BOT_SETTINGS,
} from "../../utils/botClientRoute";
import { accountInitials } from "../Chat/utils/accountDisplayName";
import { ProfileAvatar } from "../Admin/Users/ProfileAvatar";
import { botCloudApi } from "../../api/modules/botCloud";
import lynxceLogo from "../../assets/providers/lynxce.png";
import { BotCharacter, octopCharacter } from "./BotCharacter";
import styles from "./accountMenu.module.less";
import { CreditsAmount } from "./CreditsWidgets";
import { resetCredits, useLynxceCredits } from "./useLynxceCredits";

export async function signOutBotClient(
  username: string | undefined,
  navigate: NavigateFunction,
) {
  if (username === "local") holdDesktopLocalAutoLogin();
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
  const { t } = useTranslation();
  const user = useCurrentUser();
  const navigate = useNavigate();
  const location = useLocation();
  // Signed in to Lynxce: that account's name, with the Lynxce mark. Otherwise
  // the local account ("local"), never a team or other borrowed name.
  const [lynxceName, setLynxceName] = useState<string | null>(null);
  const [lynxceAvatar, setLynxceAvatar] = useState<string | null>(null);
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
        setLynxceAvatar((a.connected && a.avatar_url) || null);
      },
      () => current && setLynxceName(null),
    );
    return () => {
      current = false;
    };
  }, [desktop]);
  const lynxce = desktop ? Boolean(lynxceName) : true;
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
    ...(isBotOnlyDesktop()
      ? [
          {
            key: "cloud",
            icon: <Cloud size={16} />,
            label: entry(t("botCloud.title"), t("botClient.menu.cloudHint")),
            onClick: () => navigate(BOT_CLOUD, from),
          },
        ]
      : []),
    { type: "divider" as const },
    // Desktop has two ways in, Lynxce or this computer; both leave through the start page.
    desktop && !lynxce
      ? {
          key: "lynxce",
          icon: <LogIn size={16} />,
          label: entry(
            t("botClient.menu.lynxceSignIn"),
            t("botClient.menu.lynxceSignInHint"),
          ),
          onClick: () => void signOutBotClient(user?.username, navigate),
        }
      : {
          key: "logout",
          icon: <LogOut size={16} />,
          label: t(desktop ? "botClient.menu.lynxceSignOut" : "auth.logout"),
          onClick: async () => {
            if (desktop && lynxceAccount) {
              try {
                await botCloudApi.logout(lynxceAccount);
              } catch {
                message.error(t("octopBot.failed"));
                return;
              }
            }
            await signOutBotClient(user?.username, navigate);
          },
        },
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
  return (
    <>
      <Dropdown
        trigger={["click"]}
        placement="topLeft"
        menu={{
          items,
          className: styles.menu,
        }}
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
            {lynxce && <img className={styles.badge} src={lynxceLogo} alt="" />}
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
    </>
  );
}
