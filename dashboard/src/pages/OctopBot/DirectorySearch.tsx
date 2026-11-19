import { useEffect, useRef, useState } from "react";
import {
  Alert,
  Button,
  Input,
  Modal,
  Segmented,
  Spin,
  type InputRef,
} from "antd";
import { CornerDownLeft, MessageSquareText, Search, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { ChatReference } from "../../api/modules/octopBot";
import { useHistorySearch } from "./useHistorySearch";
import styles from "./directory.module.less";

export interface SearchContact {
  key: string;
  name: string;
  preview: string;
  keywords?: string;
  portrait: React.ReactNode;
}

function highlight(text: string, query: string) {
  const start = query ? text.toLowerCase().indexOf(query.toLowerCase()) : -1;
  if (start < 0) return text;
  return (
    <>
      {text.slice(0, start)}
      <mark>{text.slice(start, start + query.length)}</mark>
      {text.slice(start + query.length)}
    </>
  );
}

export default function DirectorySearch({
  items,
  onPick,
  onThread,
  onClose,
}: {
  items: SearchContact[];
  onPick: (key: string) => void;
  onThread: (ref: ChatReference) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState<"team" | "history">("team");
  const [hover, setHover] = useState(0);
  const input = useRef<InputRef>(null);
  const results = useRef<HTMLDivElement>(null);
  const needle = query.trim();
  const history = useHistorySearch(scope === "history" ? needle : "");
  const contacts = items.filter((item) =>
    [item.name, item.preview, item.keywords]
      .join(" ")
      .toLowerCase()
      .includes(needle.toLowerCase()),
  );
  const threads = new Map<string, ChatReference>();
  for (const hit of history.rows) {
    if (!threads.has(hit.thread_id)) threads.set(hit.thread_id, hit);
  }
  const choices =
    scope === "team"
      ? contacts.map((item) => ({ ...item, open: () => onPick(item.key) }))
      : Array.from(threads.values(), (hit) => {
          const bot = items.find((it) => it.key === "bot:" + hit.agent_id);
          return {
            key: hit.thread_id,
            name: hit.title || t("chatWelcome.newChat"),
            preview: [bot?.name, hit.excerpt].filter(Boolean).join(" · "),
            portrait: bot?.portrait ?? <MessageSquareText size={22} />,
            open: () => onThread(hit),
          };
        });
  const index = Math.min(hover, Math.max(0, choices.length - 1));
  const active = choices[index]?.key;
  useEffect(() => {
    results.current?.children[index]?.scrollIntoView?.({ block: "nearest" });
  }, [index, active]);
  return (
    <Modal
      open
      footer={null}
      closable={false}
      onCancel={onClose}
      afterOpenChange={(open) => {
        if (open) input.current?.focus();
      }}
      width={510}
      className={styles.searchModal}
      aria-label={t("botDirectory.find")}
    >
      <div className={styles.searchField}>
        <Search size={19} aria-hidden />
        <Input
          variant="borderless"
          allowClear
          ref={input}
          autoFocus
          role="combobox"
          aria-expanded
          aria-controls="bot-directory-matches"
          aria-activedescendant={active ? "bot-match-" + index : undefined}
          aria-label={t("botDirectory.find")}
          maxLength={160}
          placeholder={t(
            scope === "team"
              ? "botDirectory.contactHint"
              : "botDirectory.historyHint",
          )}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setHover(0);
          }}
          onKeyDown={(e) => {
            if (
              e.nativeEvent.isComposing ||
              e.nativeEvent.keyCode === 229 ||
              !choices.length
            )
              return;
            if (e.key === "ArrowDown" || e.key === "ArrowUp") {
              e.preventDefault();
              setHover(
                (index + (e.key === "ArrowDown" ? 1 : -1) + choices.length) %
                  choices.length,
              );
            } else if (e.key === "Enter") {
              e.preventDefault();
              choices[index].open();
            }
          }}
        />
        <Button
          type="text"
          size="small"
          aria-label={t("common.close")}
          title={t("common.close") + " (Esc)"}
          onClick={onClose}
          icon={<X size={16} />}
        />
      </div>
      <div className={styles.searchScopes}>
        <Segmented
          value={scope}
          options={[
            { value: "team", label: t("botDirectory.teamTab") },
            { value: "history", label: t("botDirectory.historyTab") },
          ]}
          onChange={(value) => {
            setScope(value as typeof scope);
            setHover(0);
            input.current?.focus();
          }}
        />
      </div>
      <div
        id="bot-directory-matches"
        role="listbox"
        aria-label={t("botDirectory.find")}
        ref={results}
        className={styles.searchResults}
      >
        {choices.map((it, i) => (
          <button
            type="button"
            role="option"
            aria-selected={i === index}
            id={"bot-match-" + i}
            key={it.key}
            onMouseMove={() => setHover(i)}
            onClick={it.open}
          >
            {it.portrait}
            <span className={styles.matchText}>
              <strong>{highlight(it.name, needle)}</strong>
              <small>{highlight(it.preview, needle)}</small>
            </span>
            {i === index && (
              <CornerDownLeft
                size={14}
                className={styles.returnIcon}
                aria-hidden
              />
            )}
          </button>
        ))}
      </div>
      {!choices.length && (
        <div className={styles.searchState} role="status">
          {scope === "history" && history.error ? (
            <Alert
              type="error"
              showIcon
              message={history.error}
              action={
                <Button size="small" onClick={history.retry}>
                  {t("octopBot.retry")}
                </Button>
              }
            />
          ) : scope === "history" && history.pending ? (
            <Spin size="small" />
          ) : (
            t(
              scope === "team"
                ? "botDirectory.noMatch"
                : needle
                ? "octopBot.noMatches"
                : "botDirectory.historyHint",
            )
          )}
        </div>
      )}
    </Modal>
  );
}
