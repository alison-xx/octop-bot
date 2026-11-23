import { useState } from "react";
import { Switch } from "antd";
import { useTranslation } from "react-i18next";

import {
  readBotNotifyPrefs,
  saveBotNotifyPrefs,
  type BotNotifyPrefs,
} from "../../hooks/useBotActivity";
import { getDesktopBridge } from "../../utils/desktopBridge";
import settings from "./BotClientSettings.module.less";

/** Settings → General: background notifications and the new-message chime. */
export default function BotNotifySettings() {
  const { t } = useTranslation();
  const [prefs, setPrefs] = useState<BotNotifyPrefs>(readBotNotifyPrefs);
  const browserBlocked =
    !getDesktopBridge()?.notify &&
    typeof Notification !== "undefined" &&
    Notification.permission === "denied";

  const toggleSystem = async (on: boolean) => {
    if (
      on &&
      !getDesktopBridge()?.notify &&
      typeof Notification !== "undefined" &&
      Notification.permission === "default"
    ) {
      await Notification.requestPermission().catch(() => "denied");
    }
    setPrefs(saveBotNotifyPrefs({ system: on }));
  };

  return (
    <>
      <h3>{t("botNotify.settingsTitle")}</h3>
      <div className={settings.group}>
        <div className={settings.row}>
          <span>
            {t("botNotify.systemLabel")}
            <small>
              {browserBlocked
                ? t("botNotify.systemBlocked")
                : t("botNotify.systemHint")}
            </small>
          </span>
          <Switch
            checked={prefs.system}
            aria-label={t("botNotify.systemLabel")}
            onChange={(on) => void toggleSystem(on)}
          />
        </div>
        <div className={settings.row}>
          <span>
            {t("botNotify.soundLabel")}
            <small>{t("botNotify.soundHint")}</small>
          </span>
          <Switch
            checked={prefs.sound}
            aria-label={t("botNotify.soundLabel")}
            onChange={(on) => setPrefs(saveBotNotifyPrefs({ sound: on }))}
          />
        </div>
      </div>
    </>
  );
}
