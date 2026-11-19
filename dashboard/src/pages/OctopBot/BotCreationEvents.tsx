import { Bot, Folder, UsersRound } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { useEmbeddedChat } from "../Chat/ChatRouteContext";
import type { WorkspaceChange } from "./creationEvents";
import styles from "./botConversation.module.less";

export default function BotCreationEvents({
  items,
}: {
  items: WorkspaceChange[];
}) {
  const host = useEmbeddedChat();
  const { t } = useTranslation();
  return items.map((item) => {
    if (item.kind === "section") {
      const label =
        item.action === "move" && !item.name ? "ungroup" : item.action;
      return (
        <div className={styles.creation} key={item.kind + item.id}>
          <Folder size={14} aria-hidden />
          <span>
            {t("botClient.sectionReceipt." + label, { name: item.name })}
          </span>
        </div>
      );
    }
    const group = item.kind === "group";
    const avatars = item.memberIds
      .slice(0, group ? 3 : 1)
      .map((id) => host?.renderAvatar?.(id, 17, false))
      .filter(Boolean);
    return (
      <div className={styles.creation} key={item.kind + item.id}>
        <span>
          {t(group ? "botClient.createdGroup" : "botClient.createdBot")}
        </span>
        <Link
          to={`/octop-bot/${group ? "groups" : "bots"}/${encodeURIComponent(
            item.id,
          )}`}
        >
          <span className={styles.creationAvatars} aria-hidden>
            {avatars.length ? (
              avatars.map((avatar, i) => (
                <span key={item.memberIds[i]}>{avatar}</span>
              ))
            ) : group ? (
              <UsersRound size={14} />
            ) : (
              <Bot size={14} />
            )}
          </span>
          {item.name}
        </Link>
      </div>
    );
  });
}
