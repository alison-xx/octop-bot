import { useEffect, useRef, useState } from "react";
import { Button, Radio } from "antd";
import {
  ArrowLeft,
  ArrowRight,
  Cloud,
  Folder,
  MessageCircle,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router-dom";
import {
  BOT_GUIDE,
  BOT_HOME,
  BOT_SETTINGS,
  botClientDestination,
  botGuideSeenKey,
} from "../../utils/botClientRoute";
import { useCurrentUser } from "../../hooks/useCurrentUser";
import { BotCharacter, octopCharacter } from "./BotCharacter";
import LynxceRegistration from "./LynxceRegistration";
import styles from "./BotGettingStarted.module.less";

const steps = ["model", "team", "draft"] as const;
const prompts = ["team", "plan", "assign"] as const;

export default function BotGettingStarted() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const user = useCurrentUser();
  const [step, setStep] = useState<(typeof steps)[number]>(
    location.state?.step === "team" ? "team" : "model",
  );
  const [prompt, setPrompt] = useState<(typeof prompts)[number]>("team");
  const title = useRef<HTMLHeadingElement>(null);
  const returnTo = botClientDestination(location.state?.returnTo ?? BOT_HOME);
  const draft = t(`botClient.${prompt}Prompt`);
  useEffect(() => title.current?.focus(), [step]);
  const configure = () =>
    navigate(BOT_SETTINGS, {
      state: { source: "lynxce", from: BOT_GUIDE, guideReturnTo: returnTo },
    });
  const finish = (withDraft: boolean) => {
    if (user) localStorage.setItem(botGuideSeenKey(user.id), "1");
    navigate(withDraft ? BOT_HOME : returnTo, {
      replace: true,
      state: withDraft ? { prefillInput: draft } : null,
    });
  };
  return (
    <main className={styles.guide} aria-label={t("botGuide.title")}>
      <header
        className={`${styles.toolbar} octop-desktop-drag`}
        data-octop-chrome-end-pad
      >
        <strong>Octop Bot</strong>
        <Button type="text" onClick={() => finish(false)}>
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
          <nav aria-label={t("botGuide.title")}>
            <ol>
              {steps.map((key, index) => (
                <li key={key}>
                  <button
                    type="button"
                    aria-current={key === step ? "step" : undefined}
                    onClick={() => setStep(key)}
                  >
                    <span aria-hidden>{index + 1}</span>
                    {t(`botGuide.${key}.label`)}
                  </button>
                </li>
              ))}
            </ol>
          </nav>
        </aside>
        <section className={styles.page}>
          <h1 tabIndex={-1} ref={title}>
            {t(`botGuide.${step}.title`)}
          </h1>
          <p>{t(`botGuide.${step}.description`)}</p>
          {step === "model" && (
            <div className={styles.options}>
              <Button size="large" onClick={configure}>
                {t("botClient.connectModel")}
              </Button>
              <LynxceRegistration />
            </div>
          )}
          {step === "team" && (
            <ul className={styles.features}>
              {(
                [
                  ["chat", MessageCircle],
                  ["groups", Folder],
                  ["cloud", Cloud],
                ] as const
              ).map(([key, Icon]) => (
                <li key={key}>
                  <Icon size={19} aria-hidden />
                  <div>
                    <strong>{t(`botGuide.team.${key}`)}</strong>
                    <p>{t(`botGuide.team.${key}Hint`)}</p>
                  </div>
                </li>
              ))}
            </ul>
          )}
          {step === "draft" && (
            <div className={styles.options}>
              <Radio.Group
                value={prompt}
                aria-label={t("botGuide.draft.label")}
                onChange={(event) => setPrompt(event.target.value)}
              >
                {prompts.map((key) => (
                  <Radio.Button key={key} value={key}>
                    {t(`botClient.${key}Label`)}
                  </Radio.Button>
                ))}
              </Radio.Group>
              <blockquote aria-live="polite">{draft}</blockquote>
            </div>
          )}
          <footer className={styles.actions}>
            {step !== "model" && (
              <Button
                type="text"
                icon={<ArrowLeft size={16} />}
                onClick={() => setStep(step === "draft" ? "team" : "model")}
              >
                {t("botGuide.previous")}
              </Button>
            )}
            <Button
              type="primary"
              onClick={() => {
                if (step === "draft") {
                  finish(true);
                } else {
                  setStep(step === "model" ? "team" : "draft");
                }
              }}
            >
              {t(step === "draft" ? "botGuide.openDraft" : "botGuide.next")}
              <ArrowRight size={16} aria-hidden />
            </Button>
          </footer>
        </section>
      </div>
    </main>
  );
}
