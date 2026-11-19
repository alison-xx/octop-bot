import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Button, Popconfirm, Spin } from "antd";
import { Trash2, Upload } from "lucide-react";
import { useTranslation } from "react-i18next";
import { botAppearanceApi, type AvatarPhoto } from "../../api/modules/octopBot";
import { apiErrorMessage } from "../../utils/apiError";
import styles from "./characters.module.less";

async function squarePhoto(file: File, invalid: string): Promise<File> {
  if (
    !/^image\/(png|jpeg|webp|gif)$/.test(file.type) ||
    file.size > 25 * 1024 * 1024
  )
    throw new Error(invalid);
  const bmp = await createImageBitmap(file);
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 160;
  const ctx = canvas.getContext("2d");
  if (!ctx) {
    bmp.close();
    throw new Error(invalid);
  }
  const side = Math.min(bmp.width, bmp.height);
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(
    bmp,
    (bmp.width - side) / 2,
    (bmp.height - side) / 2,
    side,
    side,
    0,
    0,
    160,
    160,
  );
  bmp.close();
  const blob = await new Promise<Blob | null>((resolve) =>
    canvas.toBlob(resolve, "image/webp", 0.9),
  );
  if (!blob || blob.size > 119982) throw new Error(invalid);
  // Preserve the chosen filename for library labels. The server identifies the image by its bytes.
  return new File([blob], file.name, { type: blob.type });
}

export default function PhotoLibrary({
  selected,
  onPick,
  onDelete,
}: {
  selected?: string;
  onPick: (photo: AvatarPhoto) => void;
  onDelete: (id: string) => void;
}) {
  const { t } = useTranslation();
  const [items, setItems] = useState<AvatarPhoto[]>([]),
    [next, setNext] = useState<number | null>(null),
    [busy, setBusy] = useState(true),
    [error, setError] = useState("");
  const input = useRef<HTMLInputElement>(null),
    live = useRef(true);
  const load = useCallback(async (offset = 0) => {
    const page = await botAppearanceApi.photos(offset);
    if (live.current) {
      setItems((prev) => (offset ? [...prev, ...page.items] : page.items));
      setNext(page.next);
    }
  }, []);
  const run = useCallback(
    async (action: () => Promise<void>) => {
      setBusy(true);
      setError("");
      try {
        await action();
      } catch (e) {
        if (live.current) setError(apiErrorMessage(e, t("octopBot.failed"), t));
      } finally {
        if (live.current) setBusy(false);
      }
    },
    [t],
  );
  useEffect(() => {
    live.current = true;
    void run(() => load());
    return () => {
      live.current = false;
    };
  }, [load, run]);
  const upload = async (files: File[]) => {
    const failures: string[] = [];
    let firstId: string | undefined;
    for (let i = 0; i < files.length; i += 20) {
      const converted: File[] = [];
      for (const file of files.slice(i, i + 20)) {
        try {
          converted.push(
            await squarePhoto(file, t("octopBot.avatar.invalidImage")),
          );
        } catch (e) {
          failures.push(
            file.name +
              " — " +
              apiErrorMessage(e, t("octopBot.avatar.invalidImage"), t),
          );
        }
      }
      if (!converted.length) continue;
      const result = await botAppearanceApi.import(converted);
      firstId ??= result.imported[0]?.id ?? result.duplicates[0]?.id;
      failures.push(...result.failed.map((f) => f.name + " — " + f.message));
    }
    const page = await botAppearanceApi.photos();
    if (!live.current) return;
    setItems(page.items);
    setNext(page.next);
    let photo = page.items.find((item) => item.id === firstId);
    // An imported duplicate can already be on an older library page.
    let offset = page.next;
    while (firstId && !photo && offset != null && live.current) {
      const older = await botAppearanceApi.photos(offset);
      photo = older.items.find((item) => item.id === firstId);
      offset = older.next;
    }
    if (!live.current) return;
    if (photo) onPick(photo);
    if (failures.length) setError(failures.join("\n"));
  };
  return (
    <div>
      <Button
        icon={<Upload size={15} />}
        disabled={busy}
        onClick={() => input.current?.click()}
      >
        {t("octopBot.avatar.importPhotos")}
      </Button>
      <input
        hidden
        ref={input}
        type="file"
        multiple
        accept="image/png,image/jpeg,image/webp,image/gif"
        onChange={(e) => {
          const files = Array.from(e.currentTarget.files ?? []);
          e.currentTarget.value = "";
          if (files.length) void run(() => upload(files));
        }}
      />
      {error && <Alert type="error" message={error} />}
      {busy && <Spin size="small" />}
      <div className={styles.library}>
        {items.map((photo) => (
          <div className={styles.libraryItem} key={photo.id}>
            <button
              type="button"
              aria-label={photo.name}
              aria-pressed={selected === photo.id}
              className={styles.photoChoice}
              onClick={() => onPick(photo)}
            >
              <img src={photo.image} alt="" />
              <span>{photo.name}</span>
            </button>
            <Popconfirm
              title={t("octopBot.avatar.removeConfirm")}
              onConfirm={() =>
                void run(async () => {
                  await botAppearanceApi.remove(photo.id);
                  onDelete(photo.id);
                  await load();
                })
              }
            >
              <Button
                type="text"
                size="small"
                aria-label={t("octopBot.avatar.removePhoto", {
                  name: photo.name,
                })}
                icon={<Trash2 size={13} />}
              />
            </Popconfirm>
          </div>
        ))}
      </div>
      {!busy && !items.length && <p>{t("octopBot.avatar.emptyPhotos")}</p>}
      {next != null && (
        <Button disabled={busy} onClick={() => void run(() => load(next))}>
          {t("octopBot.more")}
        </Button>
      )}
    </div>
  );
}
