import { lazy, Suspense, useEffect, useState } from "react";
import BotHtmlView from "../../plugins/toolRenderers/builtin/BotHtmlView";
import { loadAttachmentBlob } from "./attachmentData";
import { csvExcerpt, type FilePreviewKind } from "./fileCardMeta";
import styles from "./FileCard.module.less";

const PdfFirstPage = lazy(() => import("./PdfFirstPage"));

/** Width the thumbnail is drawn at (the card is at most this wide). */
const PREVIEW_WIDTH = 320;

type Loaded =
  | { kind: "image"; src: string }
  | { kind: "pdf"; blob: Blob }
  | { kind: "csv"; rows: string[][] }
  | { kind: "html"; html: string }
  | { kind: "text"; lines: string[] };

function readText(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(reader.error);
    reader.readAsText(blob);
  });
}

/**
 * The visual part of a large file card: the image itself, a PDF's first page,
 * or the first lines of a CSV / text file. Renders nothing until the bytes
 * load, and calls ``onUnavailable`` when they cannot be shown.
 */
export default function FilePreview({
  url,
  name,
  kind,
  onUnavailable,
}: {
  url: string;
  name: string;
  kind: FilePreviewKind;
  onUnavailable: () => void;
}) {
  const [loaded, setLoaded] = useState<Loaded | null>(null);

  useEffect(() => {
    let live = true;
    let objectUrl: string | undefined;
    setLoaded(null);
    loadAttachmentBlob(url)
      .then(async (blob) => {
        if (!live) return;
        if (kind === "image") {
          objectUrl = URL.createObjectURL(blob);
          setLoaded({ kind, src: objectUrl });
        } else if (kind === "pdf") {
          setLoaded({ kind, blob });
        } else {
          const text = (
            await readText(kind === "html" ? blob : blob.slice(0, 64 * 1024))
          ).replace(/^\uFEFF/, "");
          if (!live) return;
          if (!text.trim()) return onUnavailable();
          if (kind === "html") {
            setLoaded({ kind, html: text });
          } else if (kind === "csv") {
            const tsv = name.toLowerCase().endsWith(".tsv");
            setLoaded({ kind, rows: csvExcerpt(text, tsv ? "\t" : ",") });
          } else {
            setLoaded({ kind, lines: text.split(/\r?\n/).slice(0, 8) });
          }
        }
      })
      .catch(() => {
        if (live) onUnavailable();
      });
    return () => {
      live = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
    // onUnavailable only flips the parent back to the plain card.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, kind, name]);

  if (!loaded) return <div className={styles.previewPlaceholder} />;

  if (loaded.kind === "image")
    return (
      <img
        className={styles.previewImage}
        src={loaded.src}
        alt={name}
        onError={onUnavailable}
      />
    );

  if (loaded.kind === "html")
    return (
      <div className={styles.previewHtml}>
        <BotHtmlView html={loaded.html} title={name} thumbnail />
      </div>
    );

  if (loaded.kind === "pdf")
    return (
      <div className={styles.previewPdf}>
        <Suspense fallback={<div className={styles.previewPlaceholder} />}>
          <PdfFirstPage
            blob={loaded.blob}
            width={PREVIEW_WIDTH}
            onError={onUnavailable}
          />
        </Suspense>
      </div>
    );

  if (loaded.kind === "csv")
    return (
      <div className={styles.previewSheet}>
        <table>
          <tbody>
            {loaded.rows.map((row, r) => (
              <tr key={r}>
                {row.map((cell, c) =>
                  r === 0 ? <th key={c}>{cell}</th> : <td key={c}>{cell}</td>,
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );

  return <pre className={styles.previewText}>{loaded.lines.join("\n")}</pre>;
}
