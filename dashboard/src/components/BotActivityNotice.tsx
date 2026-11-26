import { X } from "lucide-react";
import type { WorkspaceBot } from "@/api/modules/octopBot";
import { BotCharacter, GroupCharacter } from "@/pages/OctopBot/BotCharacter";
import styles from "./BotActivityNotice.module.less";

export { styles as activityNoticeStyles };

export default function BotActivityNotice({
  sender,
  groupMembers,
  title,
  preview,
  count,
  countLabel,
  closeLabel,
  onOpen,
  onClose,
}: {
  sender?: WorkspaceBot;
  groupMembers?: WorkspaceBot[];
  title: string;
  preview: string;
  count: number;
  countLabel: string;
  closeLabel: string;
  onOpen: () => void;
  onClose: () => void;
}) {
  return (
    <div className={styles.row}>
      <button type="button" className={styles.open} onClick={onOpen}>
        <span className={styles.icon} aria-hidden="true">
          {groupMembers ? (
            <GroupCharacter members={groupMembers} size={34} />
          ) : (
            <BotCharacter bot={sender} size={34} badges={false} />
          )}
        </span>
        <span className={styles.copy}>
          <span className={styles.heading}>
            <strong>{title}</strong>
            {count > 1 && (
              <span className={styles.count} aria-label={countLabel}>
                {count > 99 ? "99+" : count}
              </span>
            )}
          </span>
          <span className={styles.preview}>{preview}</span>
        </span>
      </button>
      <button
        type="button"
        className={styles.close}
        aria-label={closeLabel}
        onClick={onClose}
      >
        <X size={14} />
      </button>
    </div>
  );
}
