import { Menu, ArrowLeft } from "lucide-react";
import { useTranslation } from "react-i18next";
import styles from "./directory.module.less";

export default function RoomIdentity({
  children,
  onList,
  onToggle,
  expanded,
}: {
  children: React.ReactNode;
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
          <Menu size={18} />
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
        {expanded && <ArrowLeft size={13} />}
      </button>
    </header>
  );
}
