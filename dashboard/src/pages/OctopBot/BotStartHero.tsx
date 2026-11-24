import { useEffect, useState } from "react";
import { Check, Cloud, MonitorSmartphone, UsersRound } from "lucide-react";
import { useTranslation } from "react-i18next";
import octopMascot from "../../assets/avatars/octop-mascot.webp";
import admin from "../../assets/avatars/admin.png";
import boss from "../../assets/avatars/boss.png";
import doctor from "../../assets/avatars/doctor.png";
import finance from "../../assets/avatars/finance.png";
import ops from "../../assets/avatars/ops.png";
import staff from "../../assets/avatars/staff.png";
import support from "../../assets/avatars/support.png";
import teacher from "../../assets/avatars/teacher.png";
import intro from "./BotClientSetup.module.less";

/** Team members the ticker walks through, each with something it just finished. */
const CREW = [
  ["finance", finance],
  ["ops", ops],
  ["admin", admin],
  ["support", support],
  ["teacher", teacher],
  ["doctor", doctor],
  ["boss", boss],
  ["staff", staff],
] as const;
const SHOWN = 4;
const STEP_MS = 2800;

function prefersStill(): boolean {
  // Test environments may stub matchMedia without a result.
  return (
    typeof window !== "undefined" &&
    window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches === true
  );
}

/**
 * The team at work: avatars slide in one by one, the newest is on duty, and the
 * line beside them scrolls to what it just finished. Still when motion is reduced.
 */
export function CrewTicker() {
  const { t } = useTranslation();
  // Index of the member on duty; the stack shows it and the few before it.
  const [step, setStep] = useState(SHOWN - 1);
  useEffect(() => {
    if (prefersStill()) return;
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") setStep((n) => n + 1);
    }, STEP_MS);
    return () => window.clearInterval(timer);
  }, []);
  const member = (n: number) => CREW[n % CREW.length];
  // One extra on the left is the member leaving the stack.
  const first = Math.max(0, step - SHOWN);
  const stack = Array.from({ length: step - first + 1 }, (_, i) => first + i);
  const line = (n: number, className: string) => {
    const [key] = member(n);
    return (
      <span key={n} className={className}>
        <Check size={14} aria-hidden="true" />
        <b>{t(`botStart.crew.${key}.role`)}</b>
        <span>{t(`botStart.crew.${key}.done`)}</span>
      </span>
    );
  };
  return (
    <div className={intro.crew}>
      <span className={intro.crewStack} aria-hidden="true">
        {stack.map((n) => (
          <span
            key={n}
            className={intro.crewMember}
            data-leaving={n < step - SHOWN + 1 || undefined}
            data-on-duty={n === step || undefined}
            data-entering={(n === step && step >= SHOWN) || undefined}
          >
            <img src={member(n)[1]} alt="" draggable={false} />
          </span>
        ))}
      </span>
      <span className={intro.crewLine} aria-live="off">
        {step >= SHOWN && line(step - 1, intro.crewLeaving)}
        {line(step, step >= SHOWN ? intro.crewEntering : "")}
      </span>
    </div>
  );
}

/** Left stage of the start and sign-in pages: Chief, what Octop Bot does, the team at work. */
export default function BotStartHero() {
  const { t } = useTranslation();
  const features = [
    [UsersRound, "botStart.featureChief"],
    [MonitorSmartphone, "botStart.featureDevices"],
    [Cloud, "botStart.featureComputer"],
  ] as const;
  return (
    <aside className={intro.identity}>
      <picture className={intro.chief}>
        <source
          media="(prefers-reduced-motion: no-preference)"
          srcSet={`${import.meta.env.BASE_URL}octop-mascot-peek.webp`}
        />
        <img src={octopMascot} alt="" draggable={false} />
      </picture>
      <p className={intro.heroTitle}>{t("botStart.heroTitle")}</p>
      <p className={intro.heroSub}>{t("botStart.heroSub")}</p>
      <ul className={intro.features}>
        {features.map(([Icon, key]) => (
          <li key={key}>
            <Icon size={17} aria-hidden="true" />
            {t(key)}
          </li>
        ))}
      </ul>
      <CrewTicker />
    </aside>
  );
}
