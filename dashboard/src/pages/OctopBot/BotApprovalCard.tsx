import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { ShieldAlert } from "lucide-react";
import styles from "./botApprovalCard.module.less";

/**
 * "Needs your OK" for an action with consequences (request_approval, or a guarded click on
 * the cloud computer). The server words the question and the three choices; no choice is the
 * default, so Enter never approves, and Escape answers with the last one (deny).
 */
export default function BotApprovalCard({
  title,
  question,
  options,
  onAnswer,
}: {
  title: string;
  question: string;
  options: string[];
  onAnswer?: (label: string) => void;
}) {
  const { t } = useTranslation();
  const deny = options[options.length - 1];
  useEffect(() => {
    if (!onAnswer || !deny) return undefined;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onAnswer(deny);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [deny, onAnswer]);
  return (
    <section className={styles.card} role="group" aria-label={title}>
      <header className={styles.title}>
        <ShieldAlert size={16} aria-hidden />
        <span>{title || t("botApproval.title")}</span>
      </header>
      <p className={styles.question}>{question}</p>
      <div className={styles.actions}>
        {options.map((label) => (
          <button
            key={label}
            type="button"
            className={styles.action}
            disabled={!onAnswer}
            onClick={() => onAnswer?.(label)}
          >
            {label}
          </button>
        ))}
      </div>
    </section>
  );
}
