import { useState, type ReactNode } from "react";
import {
  Button,
  Dropdown,
  Modal,
  type MenuProps,
  type DropdownProps,
} from "antd";
import { ChevronDown, ChevronRight, Ellipsis, Plus } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { BotSection, SectionColor } from "../../api/modules/octopBot";
import type { DirectoryMenuEvents } from "./useDirectoryContextMenu";
import sectionStyles from "./sections.module.less";
import styles from "./index.module.less";

const colors: Record<SectionColor, string> = {
  blue: "#3879d9",
  orange: "#d98032",
  green: "#28865d",
  purple: "#8e57c9",
  pink: "#cd5988",
};
export default function SectionHeader({
  section,
  count,
  unread,
  first,
  last,
  disabled,
  menuEvents,
  overflow,
  portraits,
  onManage,
  onNewBot,
  onNewGroup,
  onStartGroup,
  onEdit,
  onRename,
  onMove,
  onRemove,
}: {
  section: BotSection;
  count: number;
  unread: number;
  first: boolean;
  last: boolean;
  disabled: boolean;
  menuEvents: DirectoryMenuEvents;
  overflow: Pick<DropdownProps, "open" | "onOpenChange">;
  portraits?: ReactNode[];
  onManage: () => void;
  onNewBot?: () => void;
  onNewGroup: () => void;
  onStartGroup?: () => void;
  onEdit: (patch: Partial<BotSection>) => void;
  onRename: () => void;
  onMove: (direction: number) => void;
  onRemove: () => void;
}) {
  const { t } = useTranslation();
  const [confirmRemove, setConfirmRemove] = useState(false);
  const menu: MenuProps = {
    items: [
      { key: "manage", label: t("octopBot.sectionUI.edit") },
      ...(onStartGroup
        ? [{ key: "startGroup", label: t("octopBot.sectionUI.startChat") }]
        : []),
      ...(onNewBot
        ? [{ key: "newBot", label: t("octopBot.sectionUI.newBot") }]
        : []),
      { key: "newGroup", label: t("octopBot.sectionUI.newGroup") },
      { type: "divider" },
      { key: "rename", label: t("common.rename") },
      {
        key: "color",
        label: t("octopBot.sectionColor"),
        children: [
          { key: "clear", label: t("octopBot.noColor") },
          ...Object.entries(colors).map(([key, color]) => ({
            key: "color-" + key,
            label: (
              <span className={styles.colorChoice}>
                <span
                  className={styles.colorDot}
                  style={{ backgroundColor: color }}
                />
                {t("octopBot.colors." + key)}
              </span>
            ),
          })),
        ],
      },
      { key: "up", label: t("octopBot.moveUp"), disabled: first },
      { key: "down", label: t("octopBot.moveDown"), disabled: last },
      { type: "divider" },
      { key: "remove", label: t("octopBot.dissolveSection") },
    ],
    onClick: ({ key }) => {
      if (key === "manage") onManage();
      else if (key === "startGroup") onStartGroup?.();
      else if (key === "newBot") onNewBot?.();
      else if (key === "newGroup") onNewGroup();
      else if (key === "rename") onRename();
      else if (key === "up" || key === "down") onMove(key === "up" ? -1 : 1);
      else if (key === "remove") setConfirmRemove(true);
      else if (key === "clear") onEdit({ color: null });
      else if (key.startsWith("color-"))
        onEdit({ color: key.slice(6) as SectionColor });
    },
  };
  return (
    <div
      className={styles.sectionHeader}
      data-section-header
      {...(disabled ? {} : menuEvents(menu))}
    >
      <button
        type="button"
        className={styles.sectionTitle}
        disabled={disabled}
        aria-expanded={!section.collapsed}
        onClick={() => onEdit({ collapsed: !section.collapsed })}
      >
        {section.collapsed ? (
          <ChevronRight size={14} />
        ) : (
          <ChevronDown size={14} />
        )}
        {section.color && (
          <span
            className={styles.colorDot}
            style={{ backgroundColor: colors[section.color] }}
          />
        )}
        <span>{section.name}</span>
        {section.collapsed && Boolean(portraits?.length) && (
          <span className={sectionStyles.cluster} aria-hidden>
            {portraits}
          </span>
        )}
        <small>{count}</small>
        {section.collapsed && unread > 0 && (
          <b className={styles.unread}>{unread > 99 ? "99+" : unread}</b>
        )}
      </button>
      <Button
        type="text"
        size="small"
        disabled={disabled}
        icon={<Plus size={14} />}
        title={t("octopBot.sectionUI.manageEntries", { name: section.name })}
        aria-label={t("octopBot.sectionUI.manageEntries", {
          name: section.name,
        })}
        onClick={onManage}
      />
      <Dropdown trigger={["click"]} menu={menu} {...overflow}>
        <Button
          type="text"
          size="small"
          disabled={disabled}
          aria-label={t("octopBot.itemActions", { name: section.name })}
          icon={<Ellipsis size={14} />}
        />
      </Dropdown>
      {confirmRemove && (
        <Modal
          open
          centered
          title={t("octopBot.dissolveSection")}
          onCancel={() => setConfirmRemove(false)}
          onOk={() => {
            setConfirmRemove(false);
            onRemove();
          }}
          okText={t("octopBot.dissolveSection")}
        >
          {t("octopBot.sectionUI.removeHint", { name: section.name })}
        </Modal>
      )}
    </div>
  );
}
