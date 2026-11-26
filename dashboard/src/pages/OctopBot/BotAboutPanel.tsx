import { Button } from "antd";
import { ArrowLeftRight } from "lucide-react";
import { useTranslation } from "react-i18next";
import { getDesktopBridge } from "../../utils/desktopBridge";
import { BotCharacter, octopCharacter } from "./BotCharacter";
import BotUpdatePanel from "./BotUpdatePanel";
import { useBotServerInfo } from "./useBotServerInfo";
import { OCTOP_BOT_SITE } from "./botWebsite";
import settings from "./BotClientSettings.module.less";

/** Settings → About & updates: version, the desktop updater, which server, and links. */
export default function BotAboutPanel() {
  const { t } = useTranslation();
  const info = useBotServerInfo();
  const bridge = getDesktopBridge();
  // The desktop app: its own service has the shell bridge; a remote server's window has none.
  const inDesktopApp =
    !!bridge ||
    (typeof navigator !== "undefined" &&
      /Electron\//.test(navigator.userAgent));
  const serverName = bridge
    ? t("botAbout.serverLocal")
    : info?.edition === "cloud"
    ? t("botAbout.serverCloud")
    : window.location.host;
  return (
    <div className={settings.page}>
      <h2>{t("botAbout.title")}</h2>
      <p className={settings.description}>
        {t("botClient.settingsDescriptions.about")}
      </p>
      <div className={settings.group}>
        <div className={settings.row}>
          <span className={settings.who}>
            <BotCharacter
              look={{ ...octopCharacter, source: "character" }}
              size={44}
              badges={false}
            />
            <span>
              <strong>Octop Bot</strong>
              <small>
                {info?.version
                  ? t("botAbout.version", { version: info.version })
                  : " "}
              </small>
            </span>
          </span>
        </div>
      </div>
      <BotUpdatePanel />
      {inDesktopApp && (
        <>
          <h3>{t("botAbout.server")}</h3>
          <div className={settings.group}>
            <div className={settings.row}>
              <span>
                {serverName}
                <small>
                  {t(
                    bridge
                      ? "botAbout.serverLocalHint"
                      : "botAbout.serverRemoteHint",
                  )}
                </small>
              </span>
              {bridge?.openServerPicker ? (
                <Button
                  icon={<ArrowLeftRight size={15} />}
                  onClick={() => bridge.openServerPicker?.()}
                >
                  {t("botAbout.switchServer")}
                </Button>
              ) : (
                <small>{t("botAbout.switchFromMenu")}</small>
              )}
            </div>
          </div>
        </>
      )}
      <nav className={settings.links} aria-label={t("botAbout.links")}>
        <a href={OCTOP_BOT_SITE} target="_blank" rel="noopener noreferrer">
          {t("botAbout.site")}
        </a>
      </nav>
    </div>
  );
}
