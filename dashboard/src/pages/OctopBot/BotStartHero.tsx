import { Layers, MonitorSmartphone, MonitorUp } from "lucide-react";
import { useTranslation } from "react-i18next";
import { BotCharacter, octopCharacter } from "./BotCharacter";
import intro from "./BotClientSetup.module.less";

/** Left pane of the start and sign-in pages: Chief and what Octop Bot does. */
export default function BotStartHero() {
  const { t } = useTranslation();
  const features = [
    [MonitorUp, "botStart.featureComputer"],
    [MonitorSmartphone, "botStart.featureDevices"],
    [Layers, "botStart.featureModels"],
  ] as const;
  return (
    <aside className={intro.identity}>
      <BotCharacter
        look={{ ...octopCharacter, source: "character" }}
        size={132}
        badges={false}
      />
      <strong>{t("botOnboarding.chiefName")}</strong>
      <span>{t("botClient.profile.chief")}</span>
      <p className={intro.heroTitle}>{t("botStart.heroTitle")}</p>
      <ul className={intro.features}>
        {features.map(([Icon, key]) => (
          <li key={key}>
            <Icon size={17} aria-hidden="true" />
            {t(key)}
          </li>
        ))}
      </ul>
    </aside>
  );
}
