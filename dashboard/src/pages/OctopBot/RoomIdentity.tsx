import { PanelLeftOpen, ChevronDown, ChevronUp } from "lucide-react";
import { useTranslation } from "react-i18next";
import styles from "./directory.module.less";

export default function RoomIdentity({
  children,
  onList,
  onToggle,
  expanded,
  actions,
}: {
  children: React.ReactNode;
  /** Pills pinned to the top-right corner, e.g. Share. */
  actions?: React.ReactNode;
  onList?: () => void;
  onToggle: () => void;
  expanded: boolean;
}) {
  const { t } = useTranslation();
  return (
    <header className={styles.roomHeader}>
      {onList && (
        <button
          className={styles.mobileList}
          type="button"
          onClick={onList}
          aria-label={t("octopBot.switchChat")}
        >
          <PanelLeftOpen size={17} />
        </button>
      )}
      <button
        className={styles.identity}
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        title={t("botDirectory.details")}
      >
        {children}
        {expanded ? (
          <ChevronUp size={14} aria-hidden />
        ) : (
          <ChevronDown size={14} aria-hidden />
        )}
      </button>
      {actions ? <span className={styles.roomActions}>{actions}</span> : null}
    </header>
  );
}
