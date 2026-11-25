import { useEffect, useRef } from "react";
import { Button } from "antd";
import { ArrowRight } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router-dom";
import { botOnboardingApi } from "../../api/modules/botOnboarding";
import {
  BOT_GUIDE,
  BOT_HOME,
  BOT_SETTINGS,
  botClientDestination,
} from "../../utils/botClientRoute";
import { BotCharacter, octopCharacter } from "./BotCharacter";
import LynxceRegistration from "./LynxceRegistration";
import styles from "./BotGettingStarted.module.less";

/**
 * First run on this computer: pick a chat model before meeting Chief. The rest of the
 * onboarding (asking Chief for a team) happens in Chief's chat.
 */
export default function BotGettingStarted() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const title = useRef<HTMLHeadingElement>(null);
  const returnTo = botClientDestination(location.state?.returnTo ?? BOT_HOME);
  useEffect(() => title.current?.focus(), []);
  const configure = () =>
    navigate(BOT_SETTINGS, {
      state: { source: "lynxce", from: BOT_GUIDE, guideReturnTo: returnTo },
    });
  const skip = () => {
    void botOnboardingApi.change({ action: "skip" }).catch(() => null);
    navigate(returnTo, { replace: true });
  };
  return (
    <main className={styles.guide} aria-label={t("botGuide.title")}>
      <header
        className={`${styles.toolbar} octop-desktop-drag`}
        data-octop-chrome-end-pad
      >
        <strong>Octop Bot</strong>
        <Button type="text" onClick={skip}>
          {t("botGuide.skip")}
        </Button>
      </header>
      <div className={styles.sheet}>
        <aside className={styles.rail}>
          <BotCharacter
            look={{ ...octopCharacter, source: "character" }}
            size={88}
            badges={false}
          />
          <h2>{t("botGuide.title")}</h2>
        </aside>
        <section className={styles.page}>
          <h1 tabIndex={-1} ref={title}>
            {t("botGuide.model.title")}
          </h1>
          <p>{t("botGuide.model.description")}</p>
          <div className={styles.options}>
            <Button size="large" onClick={configure}>
              {t("botClient.connectModel")}
            </Button>
            <LynxceRegistration />
          </div>
          <footer className={styles.actions}>
            <Button
              type="primary"
              onClick={() => navigate(returnTo, { replace: true })}
            >
              {t("botGuide.next")}
              <ArrowRight size={16} aria-hidden />
            </Button>
          </footer>
        </section>
      </div>
    </main>
  );
}
