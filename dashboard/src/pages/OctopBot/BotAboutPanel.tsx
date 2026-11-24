import { Button } from "antd";
import { ArrowLeftRight } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { getDesktopBridge, isBotWebClient } from "../../utils/desktopBridge";
import { BOT_GUIDE } from "../../utils/botClientRoute";
import { BotCharacter, octopCharacter } from "./BotCharacter";
import BotUpdatePanel from "./BotUpdatePanel";
import { useBotServerInfo } from "./useBotServerInfo";
import settings from "./BotClientSettings.module.less";

const SITE = "https://ai.lynxce.cn";

/** Settings → About & updates: version, the desktop updater, which server, and links. */
export default function BotAboutPanel({ returnTo }: { returnTo: string }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const info = useBotServerInfo();
  const bridge = getDesktopBridge();
  const web = isBotWebClient();
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
        {!web && (
          <button
            type="button"
            onClick={() => navigate(BOT_GUIDE, { state: { returnTo } })}
          >
            {t("botGuide.title")}
          </button>
        )}
        <a href={SITE} target="_blank" rel="noopener noreferrer">
          {t("botAbout.site")}
        </a>
      </nav>
    </div>
  );
}
