import { useEffect, useState } from "react";
import { Dropdown, type MenuProps } from "antd";
import {
  Blocks,
  BookOpen,
  Check,
  Cloud,
  FolderLock,
  Languages,
  LogOut,
  Monitor,
  Moon,
  Settings2,
  Sun,
  SunMoon,
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
import { useTheme } from "../../context/ThemeContext";
import { useCurrentUser } from "../../hooks/useCurrentUser";
import { applyGuestLocale, applyUserLocale } from "../../utils/locale";
import {
  getDesktopBridge,
  isBotOnlyDesktop,
  isBotWebClient,
} from "../../utils/desktopBridge";
import {
  BOT_CAPABILITIES,
  BOT_CLOUD,
  BOT_GUIDE,
  BOT_SETTINGS,
} from "../../utils/botClientRoute";
import {
  accountDisplayName,
  accountInitials,
} from "../Chat/utils/accountDisplayName";
import { ProfileAvatar } from "../Admin/Users/ProfileAvatar";
import { botCloudApi } from "../../api/modules/botCloud";
import lynxceLogo from "../../assets/providers/lynxce.png";
import { BotCharacter, octopCharacter } from "./BotCharacter";
import RetainedFolders from "./RetainedFolders";
import styles from "./accountMenu.module.less";

export async function signOutBotClient(
  username: string | undefined,
  navigate: NavigateFunction,
) {
  if (username === "local") holdDesktopLocalAutoLogin();
  await authApi.logout();
  clearAuthToken();
  await applyGuestLocale();
  navigate("/login", { replace: true });
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
  const { preference, setPreference } = useTheme();
  const [foldersOpen, setFoldersOpen] = useState(false);
  const [language, setLanguage] = useLanguage();
  // Signed in to Lynxce: that account's name, with the Lynxce mark. Otherwise
  // the local account ("local"), never a team or other borrowed name.
  const [lynxceName, setLynxceName] = useState<string | null>(null);
  const desktop = isBotOnlyDesktop();
  useEffect(() => {
    if (!desktop) return;
    let current = true;
    botCloudApi.account().then(
      (a) =>
        current &&
        setLynxceName(a.connected ? a.display_name || a.account_id : null),
      () => current && setLynxceName(null),
    );
    return () => {
      current = false;
    };
  }, [desktop]);
  const lynxce = desktop ? Boolean(lynxceName) : true;
  const name = desktop
    ? lynxceName || user?.username || ""
    : accountDisplayName(user);
  const source = t(
    lynxce ? "botClient.account.lynxce" : "botClient.account.local",
  );
  const from = { state: { from: location.pathname } };
  const web = isBotWebClient();
  const bridge = getDesktopBridge();
  const themes = [
    ["system", "theme.system", Monitor],
    ["light", "theme.light", Sun],
    ["dark", "theme.dark", Moon],
  ] as const;
  const items: MenuProps["items"] = [
    {
      key: "settings",
      icon: <Settings2 size={16} />,
      label: t("botClient.menu.settings"),
      onClick: () => navigate(BOT_SETTINGS, from),
    },
    {
      key: "capabilities",
      icon: <Blocks size={16} />,
      label: t("botCapabilities.title"),
      onClick: () => navigate(BOT_CAPABILITIES, from),
    },
    ...(isBotOnlyDesktop()
      ? [
          {
            key: "cloud",
            icon: <Cloud size={16} />,
            label: t("botCloud.title"),
            onClick: () => navigate(BOT_CLOUD, from),
          },
        ]
      : []),
    { type: "divider" as const },
    {
      key: "theme",
      icon: <SunMoon size={16} />,
      label: t("theme.title"),
      children: themes.map(([value, label, Icon]) => ({
        key: "theme:" + value,
        icon: <Icon size={15} />,
        label: t(label),
        extra: preference === value ? <Check size={14} /> : undefined,
        onClick: () => setPreference(value),
      })),
    },
    {
      key: "language",
      icon: <Languages size={16} />,
      label: t("botClient.nav.language"),
      children: LANGUAGES.map(([value, label]) => ({
        key: "language:" + value,
        label,
        extra: language === value ? <Check size={14} /> : undefined,
        onClick: () => void setLanguage(value),
      })),
    },
    {
      key: "folders",
      icon: <FolderLock size={16} />,
      label: t("octopBot.retainedFolders"),
      onClick: () => setFoldersOpen(true),
    },
    ...(bridge?.showBotOrb
      ? [
          {
            key: "orb",
            icon: <span className={styles.orbDot} />,
            label: t("botClient.showOrb"),
            onClick: () => bridge.showBotOrb?.(),
          },
        ]
      : []),
    ...(!web
      ? [
          {
            key: "guide",
            icon: <BookOpen size={16} />,
            label: t("botGuide.title"),
            onClick: () =>
              navigate(BOT_GUIDE, { state: { returnTo: location.pathname } }),
          },
        ]
      : []),
    { type: "divider" as const },
    {
      key: "logout",
      icon: <LogOut size={16} />,
      label: t("auth.logout"),
      onClick: () => void signOutBotClient(user?.username, navigate),
    },
  ];
  const avatar =
    lynxce && (user?.avatar_url || user?.avatar_icon) ? (
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
          selectable: true,
          selectedKeys: ["theme:" + preference, "language:" + language],
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
              <small>{source}</small>
            </span>
          )}
        </button>
      </Dropdown>
      {foldersOpen && <RetainedFolders onClose={() => setFoldersOpen(false)} />}
    </>
  );
}
