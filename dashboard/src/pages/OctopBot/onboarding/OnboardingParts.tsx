import { useEffect, useState, type ReactNode } from "react";
import { Button, Input, Modal, Segmented, Spin } from "antd";
import { ArrowRight } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  botOnboardingApi,
  type OnboardingKind,
  type OnboardingOptions,
  type OnboardingPick,
} from "../../../api/modules/botOnboarding";
import { BotCharacter, octopCharacter } from "../BotCharacter";
import styles from "./onboarding.module.less";

/** The "something else" entry each tab ends with. */
const OTHER = "";

function Chief({ size }: { size: number }) {
  return (
    <BotCharacter
      look={{ ...octopCharacter, source: "character" }}
      size={size}
      badges={false}
    />
  );
}

/** The owner's pick plus the name to say it with in Chief's chat. */
export type OnboardingStart = OnboardingPick & { label: string };

/**
 * First screen over Chief's chat: an industry or a job (or your own words) on two tabs,
 * an optional line, then let Chief build the team, or skip the guide.
 */
export function OnboardingWelcome({
  busy,
  onStart,
  onSkip,
}: {
  busy: boolean;
  onStart: (pick: OnboardingStart) => void;
  onSkip: () => void;
}) {
  const { t } = useTranslation();
  const [options, setOptions] = useState<OnboardingOptions | null>(null);
  const [kind, setKind] = useState<OnboardingKind>("industry");
  const [picked, setPicked] = useState<string | null>(null);
  const [custom, setCustom] = useState("");
  const [note, setNote] = useState("");
  useEffect(() => {
    let current = true;
    // Without the lists the owner can still write their own.
    botOnboardingApi.options().then(
      (value) => current && setOptions(value),
      () => current && setOptions({ industries: [], roles: [] }),
    );
    return () => {
      current = false;
    };
  }, []);
  const listed = options
    ? kind === "industry"
      ? options.industries
      : options.roles
    : [];
  const option = listed.find((item) => item.id === picked);
  const label = picked === OTHER ? custom.trim() : option?.name ?? "";
  const switchTab = (next: OnboardingKind) => {
    setKind(next);
    setPicked(null);
  };
  const start = () => {
    if (!label) return;
    onStart({
      kind,
      ...(option ? { option: option.id } : { custom: label }),
      note: note.trim() || undefined,
      label,
    });
  };
  return (
    <Modal
      open
      centered
      closable={false}
      maskClosable={false}
      keyboard={false}
      footer={null}
      width={600}
      className={styles.welcome}
      aria-labelledby="bot-onboarding-title"
    >
      <div className={styles.welcomeBody}>
        <Chief size={64} />
        <h2 id="bot-onboarding-title">
          {t("botOnboarding.guide.welcomeTitle")}
        </h2>
        <p className={styles.lead}>{t("botOnboarding.guide.welcomeLead")}</p>
        <Segmented<OnboardingKind>
          className={styles.tabs}
          value={kind}
          onChange={switchTab}
          options={[
            { value: "industry", label: t("botOnboarding.guide.industries") },
            { value: "role", label: t("botOnboarding.guide.roles") },
          ]}
        />
        {options === null ? (
          <Spin />
        ) : (
          <div
            className={styles.choices}
            role="group"
            aria-label={t(
              kind === "industry"
                ? "botOnboarding.guide.industries"
                : "botOnboarding.guide.roles",
            )}
          >
            {[
              ...listed,
              { id: OTHER, name: t("botOnboarding.guide.other"), hint: "" },
            ].map((item) => (
              <button
                key={item.id || "other"}
                type="button"
                title={item.hint || undefined}
                aria-pressed={picked === item.id}
                data-other={item.id === OTHER || undefined}
                onClick={() => setPicked(item.id)}
              >
                {item.name}
              </button>
            ))}
          </div>
        )}
        {picked === OTHER && (
          <label className={styles.field}>
            <span>
              {t(
                kind === "industry"
                  ? "botOnboarding.guide.customIndustry"
                  : "botOnboarding.guide.customRole",
              )}
            </span>
            <Input
              autoFocus
              maxLength={60}
              value={custom}
              placeholder={t(
                kind === "industry"
                  ? "botOnboarding.guide.customIndustryPlaceholder"
                  : "botOnboarding.guide.customRolePlaceholder",
              )}
              onChange={(event) => setCustom(event.target.value)}
              onPressEnter={start}
            />
          </label>
        )}
        <label className={styles.field}>
          <span>{t("botOnboarding.guide.noteLabel")}</span>
          <Input.TextArea
            autoSize={{ minRows: 1, maxRows: 3 }}
            maxLength={300}
            value={note}
            placeholder={t("botOnboarding.guide.notePlaceholder")}
            onChange={(event) => setNote(event.target.value)}
          />
        </label>
        <div className={styles.actions}>
          <Button
            size="large"
            disabled={busy}
            autoInsertSpace={false}
            onClick={onSkip}
          >
            {t("botOnboarding.guide.skip")}
          </Button>
          <Button
            type="primary"
            size="large"
            loading={busy}
            disabled={!label}
            autoInsertSpace={false}
            onClick={start}
          >
            {t("botOnboarding.guide.startTeam")}
          </Button>
        </div>
        <small className={styles.reopen}>
          {t("botOnboarding.guide.reopenHint")}
        </small>
      </div>
    </Modal>
  );
}

/** The card above a composer while onboarding: which step, what to do, skip. */
export function OnboardingStrip({
  step,
  title,
  hint,
  onSkip,
  children,
  wide = false,
}: {
  step: 1 | 2 | 3;
  title: string;
  hint?: string;
  onSkip: () => void;
  children?: ReactNode;
  /** Above a group's composer, which is wider than a Bot chat's. */
  wide?: boolean;
}) {
  const { t } = useTranslation();
  return (
    <section
      className={wide ? `${styles.strip} ${styles.wide}` : styles.strip}
      aria-label={title}
    >
      <header>
        <Chief size={24} />
        <strong>{title}</strong>
        <span className={styles.step}>
          {t("botOnboarding.guide.step", { step, total: 3 })}
        </span>
        <button type="button" className={styles.skip} onClick={onSkip}>
          {t("botOnboarding.guide.skip")}
        </button>
      </header>
      {hint && <p>{hint}</p>}
      {children}
    </section>
  );
}

/** After the first screen: Chief is building, or its turn ended without a team. */
export function OnboardingAsk({
  building,
  onRetry,
  onSkip,
}: {
  building: boolean;
  onRetry?: () => void;
  onSkip: () => void;
}) {
  const { t } = useTranslation();
  if (building)
    return (
      <OnboardingStrip
        step={2}
        title={t("botOnboarding.guide.buildingTitle")}
        hint={t("botOnboarding.guide.buildingHint")}
        onSkip={onSkip}
      />
    );
  return (
    <OnboardingStrip
      step={2}
      title={t("botOnboarding.guide.askTitle")}
      hint={t(
        onRetry
          ? "botOnboarding.guide.askHintRetry"
          : "botOnboarding.guide.askHint",
      )}
      onSkip={onSkip}
    >
      {onRetry && (
        <div className={styles.retry}>
          <Button size="small" onClick={onRetry}>
            {t("botOnboarding.guide.retry")}
          </Button>
        </div>
      )}
    </OnboardingStrip>
  );
}

/** Step 2 done: the team exists; open its group. */
export function OnboardingTeamReady({
  name,
  members,
  portraits,
  onOpen,
  onSkip,
}: {
  name: string;
  members: string[];
  portraits: ReactNode;
  onOpen: () => void;
  onSkip: () => void;
}) {
  const { t } = useTranslation();
  return (
    <OnboardingStrip
      step={2}
      title={t("botOnboarding.guide.teamTitle", { name })}
      hint={t("botOnboarding.guide.teamHint")}
      onSkip={onSkip}
    >
      <div className={styles.team}>
        <span className={styles.portraits}>{portraits}</span>
        <span className={styles.teamText}>
          <strong>{name}</strong>
          <small>{members.join(" · ")}</small>
        </span>
        <Button type="primary" onClick={onOpen}>
          {t("botOnboarding.guide.openGroup")}
          <ArrowRight size={15} aria-hidden />
        </Button>
      </div>
    </OnboardingStrip>
  );
}

/** Pointer next to the new group in the sidebar. */
export function OnboardingCoach({ onOpen }: { onOpen: () => void }) {
  const { t } = useTranslation();
  return (
    <div className={styles.coach}>
      <strong>{t("botOnboarding.guide.coachTitle")}</strong>
      <p>{t("botOnboarding.guide.coachBody")}</p>
      <Button size="small" type="primary" onClick={onOpen}>
        {t("botOnboarding.guide.openGroup")}
      </Button>
    </div>
  );
}
