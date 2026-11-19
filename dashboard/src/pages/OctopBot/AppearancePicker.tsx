import { useState } from "react";
import { Alert, Button, Modal, Segmented } from "antd";
import { useTranslation } from "react-i18next";
import {
  botAppearanceApi,
  type AvatarPhoto,
  type WorkspaceBot,
} from "../../api/modules/octopBot";
import { apiErrorMessage } from "../../utils/apiError";
import {
  BotCharacter,
  appearanceOf,
  colorStyle,
  inkIds,
  octopCharacter,
  shapeIds,
} from "./BotCharacter";
import PhotoLibrary from "./PhotoLibrary";
import styles from "./characters.module.less";

export type AppearanceChoice =
  | { kind: "character"; shape: string; color: string }
  | { kind: "photo"; photo: AvatarPhoto }
  | { kind: "reset" };
export async function saveAppearance(id: string, choice: AppearanceChoice) {
  if (choice.kind === "character")
    await botAppearanceApi.set(id, choice.shape, choice.color);
  else if (choice.kind === "photo")
    await botAppearanceApi.photo(id, choice.photo.id);
  else await botAppearanceApi.reset(id);
}
export function AppearancePicker({
  bot,
  value,
  onChange,
}: {
  bot?: WorkspaceBot;
  value: AppearanceChoice | null;
  onChange: (choice: AppearanceChoice) => void;
}) {
  const { t } = useTranslation();
  const initial = appearanceOf(bot);
  const [tab, setTab] = useState("character");
  const look =
    value?.kind === "character"
      ? { source: "character" as const, shape: value.shape, color: value.color }
      : value?.kind === "reset" && bot?.is_main
      ? { ...octopCharacter, source: "character" as const }
      : initial;
  const source =
    value?.kind === "photo"
      ? "photo"
      : value?.kind === "reset"
      ? "character"
      : look.source;
  const gradient = "linear-gradient(135deg,#A4FFB0,#00F0E4,#2E9EF7)";
  return (
    <div className={styles.picker}>
      <div className={styles.preview}>
        {(value?.kind === "reset" && !bot?.is_main) || (!bot && !value) ? (
          <span>{t("octopBot.avatar.auto")}</span>
        ) : (
          <BotCharacter
            bot={bot}
            size={55}
            look={{ ...look, source }}
            photo={value?.kind === "photo" ? value.photo.image : bot?.icon_url}
            badges={false}
          />
        )}
        <div>
          <Segmented
            value={tab}
            options={[
              { value: "character", label: t("octopBot.avatar.characters") },
              { value: "photo", label: t("octopBot.avatar.photos") },
            ]}
            onChange={(v) => setTab(String(v))}
          />
        </div>
        <Button type="link" onClick={() => onChange({ kind: "reset" })}>
          {t("common.reset")}
        </Button>
      </div>
      {tab === "photo" ? (
        <PhotoLibrary
          selected={
            value?.kind === "photo"
              ? value.photo.id
              : !value && bot?.avatar?.source === "photo"
              ? new URLSearchParams(bot.icon_url?.split("?")[1]).get("photo") ??
                undefined
              : undefined
          }
          onPick={(photo) => onChange({ kind: "photo", photo })}
          onDelete={(id) => {
            if (value?.kind === "photo" && value.photo.id === id)
              onChange({ kind: "reset" });
          }}
        />
      ) : (
        <>
          <div className={styles.shapeGrid}>
            {shapeIds.map((shape) => (
              <button
                key={shape}
                type="button"
                className={styles.choice}
                aria-label={t("octopBot.avatar.shapes." + shape)}
                title={t("octopBot.avatar.shapes." + shape)}
                aria-pressed={
                  look.shape === shape &&
                  source === "character" &&
                  value?.kind !== "reset"
                }
                onClick={() =>
                  onChange({
                    kind: "character",
                    shape,
                    color:
                      shape === octopCharacter.shape
                        ? octopCharacter.color
                        : look.color,
                  })
                }
              >
                <BotCharacter
                  look={{ shape, color: look.color, source: "character" }}
                  size={32}
                  badges={false}
                />
              </button>
            ))}
          </div>
          {look.shape !== octopCharacter.shape && (
            <div className={styles.colors}>
              {inkIds.map((color) => (
                <button
                  type="button"
                  key={color}
                  className={styles.swatch}
                  style={{
                    ...colorStyle(color),
                    background: color === "aurora" ? gradient : undefined,
                  }}
                  aria-label={t("octopBot.avatar.inks." + color)}
                  title={t("octopBot.avatar.inks." + color)}
                  aria-pressed={
                    look.color === color &&
                    source === "character" &&
                    value?.kind !== "reset"
                  }
                  onClick={() =>
                    onChange({ kind: "character", shape: look.shape, color })
                  }
                />
              ))}
              <input
                className={styles.customColor}
                type="color"
                aria-label={t("octopBot.avatar.customColor")}
                value={
                  /^#[\da-f]{6}$/i.test(look.color) ? look.color : "#2563eb"
                }
                onChange={(e) =>
                  onChange({
                    kind: "character",
                    shape: look.shape,
                    color: e.target.value,
                  })
                }
              />
            </div>
          )}
        </>
      )}
    </div>
  );
}
export default function AppearanceModal({
  bot,
  onClose,
  onSaved,
  initial = null,
}: {
  bot: WorkspaceBot;
  onClose: () => void;
  onSaved: () => void;
  initial?: AppearanceChoice | null;
}) {
  const { t } = useTranslation();
  const [value, setValue] = useState<AppearanceChoice | null>(initial),
    [saving, setSaving] = useState(false),
    [error, setError] = useState("");
  const save = async () => {
    if (!value) return;
    setSaving(true);
    setError("");
    try {
      await saveAppearance(bot.agent_id, value);
      onSaved();
    } catch (e) {
      setError(apiErrorMessage(e, t("octopBot.failed"), t));
    } finally {
      setSaving(false);
    }
  };
  return (
    <Modal
      open
      title={t("octopBot.avatar.title")}
      onCancel={onClose}
      okText={t("common.save")}
      okButtonProps={{ disabled: !value }}
      confirmLoading={saving}
      onOk={() => void save()}
    >
      <AppearancePicker bot={bot} value={value} onChange={setValue} />
      {error && <Alert type="error" message={error} />}
    </Modal>
  );
}
