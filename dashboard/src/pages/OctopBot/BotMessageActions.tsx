import { Dropdown, type MenuProps } from "antd";
import { MoreHorizontal } from "lucide-react";
import { useTranslation } from "react-i18next";
import { CopyButton, QuoteButton } from "../Chat/components/MessageTextActions";
import styles from "./botConversation.module.less";

type Action = { key: string; label: string; run: () => void };

/**
 * Icons that appear beside a bubble on hover: reply (quote), copy and a
 * "more" menu for the rarer actions.
 */
export default function BotMessageActions({
  text,
  onQuote,
  more,
}: {
  text: string;
  onQuote?: ((quote: string) => void) | null;
  more: Array<Action | false | undefined>;
}) {
  const { t } = useTranslation();
  const actions = more.filter(Boolean) as Action[];
  const items: MenuProps["items"] = actions.map(({ key, label }) => ({
    key,
    label,
  }));
  if (!text && !actions.length) return null;
  return (
    <div className={styles.actions} role="group">
      {onQuote && text ? <QuoteButton text={text} onQuote={onQuote} /> : null}
      {text ? <CopyButton text={text} /> : null}
      {actions.length ? (
        <Dropdown
          trigger={["click"]}
          menu={{
            items,
            onClick: ({ key }) => actions.find((a) => a.key === key)?.run(),
          }}
        >
          <button
            type="button"
            title={t("common.more")}
            aria-label={t("common.more")}
          >
            <MoreHorizontal size={15} />
          </button>
        </Dropdown>
      ) : null}
    </div>
  );
}
