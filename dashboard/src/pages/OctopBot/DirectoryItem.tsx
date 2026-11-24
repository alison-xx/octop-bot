import { memo, useMemo } from "react";
import { Button, Dropdown, type DropdownProps, type MenuProps } from "antd";
import { Ellipsis, Pin } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { BotGroup, WorkspaceBot } from "../../api/modules/octopBot";
import { BotCharacter, GroupCharacter, type BotMotion } from "./BotCharacter";
import type { DirectoryMenuEvents } from "./useDirectoryContextMenu";
import directory from "./directory.module.less";
import sectionStyles from "./sections.module.less";
import styles from "./index.module.less";

export type DirectoryEntry = {
  key: string;
  name: string;
  bot?: WorkspaceBot;
  group?: BotGroup;
};
export const DIRECTORY_DRAG_TYPE = "application/x-octop-bot-sidebar-item";

/**
 * One contact row of the Bot directory. Memoized so streaming motion, previews
 * or menus elsewhere in the sidebar do not rebuild every row and its menu; the
 * parent passes stable callbacks and primitive props.
 */
export const DirectoryItem = memo(function DirectoryItem({
  item,
  chief,
  fresh = false,
  pinned,
  selected,
  compact,
  standalone,
  disabled,
  unread,
  subtitle,
  motion,
  members,
  sectionNames,
  assignedTo,
  bulkDisabled,
  menuEvents,
  overflowProps,
  onAction,
  onPick,
  onDragging,
}: {
  item: DirectoryEntry;
  chief: boolean;
  /** Just built by Chief during onboarding: highlighted with a "new" badge. */
  fresh?: boolean;
  pinned: boolean;
  selected: boolean;
  compact: boolean;
  standalone: boolean;
  disabled: boolean;
  unread: number;
  subtitle: string;
  motion: BotMotion;
  members?: WorkspaceBot[];
  sectionNames: string[];
  assignedTo?: string;
  /** Whether "move many" is unavailable from this row's menu. */
  bulkDisabled: boolean;
  menuEvents: DirectoryMenuEvents;
  overflowProps: (id: string) => Pick<DropdownProps, "open" | "onOpenChange">;
  onAction: (item: DirectoryEntry, key: string) => void;
  onPick: (item: DirectoryEntry) => void;
  onDragging: (dragging: boolean) => void;
}) {
  const { t } = useTranslation();
  const menu = useMemo<MenuProps>(() => {
    const conversationAction = {
      key: "newChat",
      label: t(
        item.bot
          ? "botDirectory.newPrivateChat"
          : "botDirectory.newGroupWithMembers",
      ),
    };
    const bulk = {
      key: "bulk",
      label: t("octopBot.sectionUI.moveMany"),
      disabled: bulkDisabled,
    };
    return {
      items: chief
        ? [
            conversationAction,
            { key: "create", label: t("octopBot.newSection") },
            bulk,
          ]
        : [
            conversationAction,
            { key: "create", label: t("octopBot.newSection") },
            {
              key: "pin",
              label: t(pinned ? "octopBot.unpin" : "octopBot.pin"),
            },
            {
              key: "move",
              label: t("octopBot.move"),
              children: [
                {
                  key: "none",
                  label: t("octopBot.ungrouped"),
                  disabled: assignedTo === undefined,
                },
                ...sectionNames.map((name, i) => ({
                  key: "s" + i,
                  label: name,
                  disabled: assignedTo === name,
                })),
              ],
            },
            bulk,
            ...(item.bot && !item.bot.is_main
              ? [
                  {
                    key: "deleteBot",
                    label: t("octopBot.deleteBot"),
                    danger: true,
                  },
                ]
              : []),
            ...(item.group
              ? [
                  {
                    key: "deleteGroup",
                    label: t("octopBot.deleteGroup"),
                    danger: true,
                  },
                ]
              : []),
          ],
      onClick: ({ key }) => onAction(item, key),
    };
  }, [
    t,
    item,
    chief,
    pinned,
    assignedTo,
    sectionNames,
    bulkDisabled,
    onAction,
  ]);
  const size = compact
    ? chief
      ? 39
      : 33
    : chief
    ? standalone
      ? 58
      : 37
    : standalone
    ? 35
    : 29;
  return (
    <div
      data-directory-item
      {...(disabled ? {} : menuEvents(menu))}
      className={
        standalone
          ? directory.contact + " " + sectionStyles.contactActions
          : styles.item
      }
      data-selected={selected}
      data-chief={chief}
      data-unread={unread > 0 || undefined}
      data-onboarding-new={fresh || undefined}
      draggable={!chief && !disabled}
      onDragEnd={() => onDragging(false)}
      onDragStart={(e) => {
        onDragging(true);
        e.dataTransfer.setData(DIRECTORY_DRAG_TYPE, item.key);
        e.dataTransfer.effectAllowed = "move";
      }}
    >
      <button
        className={standalone ? directory.contactButton : styles.itemMain}
        type="button"
        onClick={() => onPick(item)}
        aria-label={standalone ? item.name : undefined}
        title={compact ? item.name : undefined}
        aria-current={selected ? "page" : undefined}
      >
        {item.bot ? (
          <BotCharacter bot={item.bot} state={motion} size={size} />
        ) : (
          <GroupCharacter members={members ?? []} size={size} />
        )}
        {standalone ? (
          <span className={directory.contactText}>
            <strong>{item.name}</strong>
            <small>{subtitle}</small>
          </span>
        ) : (
          <span>{item.name}</span>
        )}
        {unread > 0 && (
          <b
            className={styles.unread}
            aria-label={t("botNotify.unreadCount", { count: unread })}
          >
            {unread > 99 ? "99+" : unread}
          </b>
        )}
        {fresh && !compact && (
          <span className={directory.freshBadge}>
            {t("botOnboarding.guide.new")}
          </span>
        )}
        {pinned && !chief && !compact && <Pin size={12} />}
      </button>
      {!compact && (
        <Dropdown trigger={["click"]} menu={menu} {...overflowProps(item.key)}>
          <Button
            type="text"
            size="small"
            disabled={disabled}
            icon={<Ellipsis size={15} />}
            aria-label={t("octopBot.itemActions", { name: item.name })}
          />
        </Dropdown>
      )}
    </div>
  );
});
