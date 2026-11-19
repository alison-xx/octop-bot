import { useRef, useState, type ReactNode } from "react";
import { Alert, Checkbox, Input, Modal, Select, type InputRef } from "antd";
import { Search } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { BotSection } from "../../api/modules/octopBot";
import styles from "./sections.module.less";

export type SectionAction =
  | { kind: "create"; entry?: string }
  | { kind: "edit"; name: string; focusName?: boolean }
  | { kind: "move" };
export type SectionContact = {
  key: string;
  name: string;
  detail: string;
  avatar: ReactNode;
};
const UNGROUPED = "ungrouped";

export function moveEntries(
  sections: BotSection[],
  keys: string[],
  target?: string,
): BotSection[] {
  const moved = new Set(keys);
  return sections.map((section) => {
    if (section.name === target) {
      const existing = new Set(section.items);
      return {
        ...section,
        items: [...section.items, ...keys.filter((k) => !existing.has(k))],
      };
    }
    return { ...section, items: section.items.filter((k) => !moved.has(k)) };
  });
}

export default function SectionEditor({
  action,
  sections,
  contacts,
  saving,
  error,
  onSave,
  onClose,
}: {
  action: SectionAction;
  sections: BotSection[];
  contacts: SectionContact[];
  saving: boolean;
  error: string;
  onSave: (sections: BotSection[], reveal?: string) => Promise<boolean>;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const originalName = action.kind === "edit" ? action.name : "";
  const editing = sections.find(
    (s) => action.kind === "edit" && s.name === action.name,
  );
  const [name, setName] = useState(originalName);
  const [target, setTarget] = useState<string>();
  const [query, setQuery] = useState("");
  // A draft contains just the user's changes. A workspace refresh can then
  // bring in other new members without the next save undoing their edits.
  const [changes, setChanges] = useState<Map<string, boolean>>(
    () =>
      new Map(
        action.kind === "create" && action.entry ? [[action.entry, true]] : [],
      ),
  );
  const nameInput = useRef<InputRef>(null);
  const searchInput = useRef<InputRef>(null);
  const needle = query.trim().toLowerCase();
  const owner = new Map(
    sections.flatMap((s) => s.items.map((k) => [k, s.name] as const)),
  );
  const matches = contacts.filter((it) =>
    [it.name, it.key, it.detail, owner.get(it.key)]
      .join(" ")
      .toLowerCase()
      .includes(needle),
  );
  const selected = (key: string) =>
    changes.get(key) ?? Boolean(editing?.items.includes(key));
  const chosen = contacts.filter((it) => selected(it.key)).map((it) => it.key);
  const visibleSelected = matches.filter((it) => selected(it.key)).length;
  const trimmed = name.trim();
  const duplicate = sections.some((s) => s !== editing && s.name === trimmed);
  const destination = target?.startsWith("section:")
    ? target.slice(8)
    : undefined;
  const validMove =
    target === UNGROUPED || sections.some((s) => s.name === destination);
  const missing = action.kind === "edit" && !editing;
  const valid =
    action.kind === "move"
      ? validMove && chosen.some((k) => owner.get(k) !== destination)
      : trimmed && !duplicate && !missing;
  const toggle = (keys: string[], check: boolean) => {
    setChanges((prev) => {
      const next = new Map(prev);
      for (const key of keys) {
        if (check === Boolean(editing?.items.includes(key))) next.delete(key);
        else next.set(key, check);
      }
      return next;
    });
  };
  const save = async () => {
    if (saving || !valid) return;
    let next: BotSection[];
    if (action.kind === "move")
      next = moveEntries(sections, chosen, destination);
    else {
      const visible = new Set(contacts.map((c) => c.key));
      const added: string[] = [],
        removed = new Set<string>();
      for (const [key, check] of changes) {
        if (!visible.has(key)) continue;
        if (check) added.push(key);
        else removed.add(key);
      }
      const renamed = editing
        ? sections.map((s) =>
            s === editing
              ? {
                  ...s,
                  name: trimmed,
                  items: s.items.filter((k) => !removed.has(k)),
                }
              : s,
          )
        : [...sections, { name: trimmed, items: [] }];
      next = moveEntries(renamed, added, trimmed);
    }
    if (await onSave(next, action.kind === "move" ? destination : trimmed))
      onClose();
  };
  const changing = action.kind === "move";
  return (
    <Modal
      open
      centered
      width={450}
      className={styles.modal}
      title={t(
        changing
          ? "octopBot.sectionUI.moveMany"
          : action.kind === "edit"
          ? "octopBot.sectionUI.edit"
          : "octopBot.newSection",
      )}
      onCancel={() => {
        if (!saving) onClose();
      }}
      onOk={() => void save()}
      okText={t(changing ? "octopBot.sectionUI.moveAction" : "octopBot.save")}
      okButtonProps={{ disabled: !valid }}
      confirmLoading={saving}
      cancelButtonProps={{ disabled: saving }}
      keyboard={!saving}
      maskClosable={!saving}
      afterOpenChange={(open) => {
        if (open)
          (action.kind === "create" ||
          (action.kind === "edit" && action.focusName)
            ? nameInput
            : searchInput
          ).current?.focus();
      }}
    >
      <div className={styles.editor} data-section-editor>
        <p>{t("octopBot.sectionUI.hint")}</p>
        {error && <Alert type="error" showIcon message={error} />}
        {missing && (
          <Alert type="warning" message={t("octopBot.sectionUI.missing")} />
        )}
        {changing ? (
          <div className={styles.field}>
            <label htmlFor="section-dest">
              {t("octopBot.sectionUI.destination")}
            </label>
            <Select
              id="section-dest"
              placeholder={t("octopBot.sectionUI.chooseDest")}
              value={target}
              disabled={saving}
              onChange={setTarget}
              options={[
                { value: UNGROUPED, label: t("octopBot.ungrouped") },
                ...sections.map((s) => ({
                  value: "section:" + s.name,
                  label: s.name,
                })),
              ]}
            />
          </div>
        ) : (
          <div className={styles.field}>
            <label htmlFor="section-name">{t("octopBot.sectionUI.name")}</label>
            <Input
              id="section-name"
              ref={nameInput}
              value={name}
              disabled={saving}
              maxLength={160}
              status={duplicate ? "error" : undefined}
              onChange={(e) => setName(e.target.value)}
              onPressEnter={(e) => {
                if (!e.nativeEvent.isComposing) void save();
              }}
            />
            {duplicate && (
              <small role="alert">{t("octopBot.sectionUI.duplicate")}</small>
            )}
          </div>
        )}
        {contacts.length > 0 ? (
          <>
            <div className={styles.filter}>
              <Input
                ref={searchInput}
                allowClear
                prefix={<Search size={14} />}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={t("octopBot.sectionUI.find")}
                aria-label={t("octopBot.sectionUI.find")}
              />
              <span>{t("botForms.selected", { count: chosen.length })}</span>
            </div>
            {matches.length > 0 && (
              <Checkbox
                disabled={saving}
                checked={visibleSelected === matches.length}
                indeterminate={
                  visibleSelected > 0 && visibleSelected < matches.length
                }
                onChange={(e) =>
                  toggle(
                    matches.map((it) => it.key),
                    e.target.checked,
                  )
                }
              >
                {t("octopBot.sectionUI.selectMatches")}
              </Checkbox>
            )}
            <div
              className={styles.choices}
              role="group"
              aria-label={t("octopBot.sectionUI.entries")}
            >
              {matches.map((it) => (
                <Checkbox
                  key={it.key}
                  checked={selected(it.key)}
                  disabled={saving}
                  onChange={(e) => toggle([it.key], e.target.checked)}
                >
                  {it.avatar}
                  <span className={styles.identity}>
                    <strong>{it.name}</strong>
                    <small>{it.detail}</small>
                  </span>
                  <span className={styles.owner}>
                    {owner.get(it.key) ?? t("octopBot.ungrouped")}
                  </span>
                </Checkbox>
              ))}
              {!matches.length && (
                <p role="status">{t("botDirectory.noMatch")}</p>
              )}
            </div>
          </>
        ) : (
          <p role="status">{t("octopBot.sectionUI.noEntries")}</p>
        )}
      </div>
    </Modal>
  );
}
