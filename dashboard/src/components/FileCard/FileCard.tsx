import { useState } from "react";
import cx from "classnames";
import { Download, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import FilePreview from "./FilePreview";
import FileTypeIcon from "./FileTypeIcon";
import {
  filePreviewKind,
  fileTypeLabel,
  fileTypeOf,
  formatFileSize,
  middleEllipsis,
  PREVIEW_MAX_BYTES,
} from "./fileCardMeta";
import styles from "./FileCard.module.less";

export interface FileCardProps {
  name: string;
  mime?: string | null;
  /** Bytes; ``undefined`` while loading, ``null`` when unknown. */
  size?: number | null;
  /** URL of the bytes for a large preview (image / PDF page / text excerpt). */
  previewUrl?: string;
  /** Authenticated first-page image of the exact delivered Office revision. */
  thumbnailUrl?: string;
  onOpen?: () => void;
  onDownload?: () => void;
  downloading?: boolean;
}

/** Whether a large preview may be fetched for this file at this size. */
export function canPreview(
  name: string,
  mime: string | null | undefined,
  size: number | null | undefined,
): boolean {
  const kind = filePreviewKind(name, mime);
  if (!kind || size === undefined) return false;
  // Images can come from preview URLs without a known size; text and PDFs need one.
  if (size === null) return kind === "image";
  return size <= PREVIEW_MAX_BYTES[kind];
}

/**
 * Grok-style file card: a document glyph colored by type, the name
 * (middle-ellipsized, extension kept) and its size. With ``previewUrl`` it
 * grows a visual preview on top; images become the card themselves.
 */
export default function FileCard({
  name,
  mime,
  size,
  previewUrl,
  thumbnailUrl,
  onOpen,
  onDownload,
  downloading,
}: FileCardProps) {
  const { t } = useTranslation();
  const [previewFailed, setPreviewFailed] = useState(false);
  const kind = fileTypeOf(name, mime);
  const label = fileTypeLabel(name);
  const previewKind = filePreviewKind(name, mime);
  const showPreview = Boolean(
    previewUrl && previewKind && !previewFailed && canPreview(name, mime, size),
  );
  const open = onOpen ?? onDownload;
  const meta =
    typeof size === "number"
      ? formatFileSize(size)
      : label || t("chat.fileCardGeneric");

  const download = onDownload && (
    <button
      type="button"
      className={styles.download}
      onClick={(e) => {
        e.stopPropagation();
        onDownload();
      }}
      disabled={downloading}
      title={t("chat.fileCardDownload", { name })}
      aria-label={t("chat.fileCardDownload", { name })}
    >
      {downloading ? (
        <Loader2 size={16} className={styles.spin} />
      ) : (
        <Download size={16} strokeWidth={2} />
      )}
    </button>
  );

  const preview =
    thumbnailUrl && !previewFailed ? (
      <FilePreview
        url={thumbnailUrl}
        name={name}
        kind="image"
        onUnavailable={() => setPreviewFailed(true)}
      />
    ) : showPreview && previewUrl && previewKind ? (
      <FilePreview
        url={previewUrl}
        name={name}
        kind={previewKind}
        onUnavailable={() => setPreviewFailed(true)}
      />
    ) : null;

  if (preview && previewKind === "image")
    return (
      <div className={cx(styles.card, styles.imageCard)} data-kind="image">
        <button
          type="button"
          className={styles.imageButton}
          onClick={open}
          title={name}
          aria-label={t("chat.fileCardOpen", { name })}
        >
          {preview}
        </button>
        {download && <div className={styles.imageActions}>{download}</div>}
      </div>
    );

  return (
    <div
      className={cx(styles.card, preview && styles.richCard)}
      data-kind={kind}
    >
      {preview && (
        <button
          type="button"
          className={styles.previewButton}
          onClick={open}
          tabIndex={-1}
          aria-hidden
        >
          {preview}
        </button>
      )}
      <div className={styles.row}>
        <button
          type="button"
          className={styles.main}
          onClick={open}
          title={name}
          aria-label={t("chat.fileCardOpen", { name })}
        >
          <FileTypeIcon kind={kind} label={label} />
          <span className={styles.text}>
            <span className={styles.name}>{middleEllipsis(name)}</span>
            <span className={styles.meta}>{meta}</span>
          </span>
        </button>
        {download}
      </div>
    </div>
  );
}
