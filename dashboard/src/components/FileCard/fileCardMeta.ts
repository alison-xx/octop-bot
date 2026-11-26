/**
 * Pure helpers for chat file cards: type → icon color, middle-ellipsized
 * names that keep the extension, and human-readable sizes.
 */

export type FileTypeKind =
  | "pdf"
  | "word"
  | "excel"
  | "ppt"
  | "archive"
  | "image"
  | "other";

/** Bottom band of the document glyph. Everything that is not one of the office/PDF/archive families is gray. */
export const FILE_TYPE_COLORS: Record<FileTypeKind, string> = {
  pdf: "#E5484D",
  word: "#2F6FEB",
  excel: "#1F9D55",
  ppt: "#F2711C",
  archive: "#8E4EC6",
  image: "#8B8D98",
  other: "#8B8D98",
};

const EXTENSIONS: Record<Exclude<FileTypeKind, "other">, string[]> = {
  pdf: ["pdf"],
  word: ["doc", "docx", "odt", "rtf", "pages"],
  excel: ["xls", "xlsx", "csv", "tsv", "ods", "numbers"],
  ppt: ["ppt", "pptx", "odp", "key"],
  archive: ["zip", "rar", "7z", "tar", "gz", "tgz", "bz2", "xz"],
  image: ["png", "jpg", "jpeg", "gif", "webp", "bmp", "svg", "heic"],
};

const MIME_HINTS: Array<[RegExp, FileTypeKind]> = [
  [/^application\/pdf$/, "pdf"],
  [/wordprocessingml|msword|opendocument\.text|rtf/, "word"],
  [/spreadsheetml|ms-excel|opendocument\.spreadsheet|text\/csv/, "excel"],
  [/presentationml|ms-powerpoint|opendocument\.presentation/, "ppt"],
  [/zip|x-rar|x-7z|x-tar|gzip|x-bzip|x-xz/, "archive"],
  [/^image\//, "image"],
];

/** Lower-case extension without the dot ("" when the name has none). */
export function fileExtension(name: string): string {
  const base = name.split(/[\\/]/).pop() ?? "";
  const dot = base.lastIndexOf(".");
  if (dot <= 0 || dot === base.length - 1) return "";
  const ext = base.slice(dot + 1).toLowerCase();
  return /^[a-z0-9]{1,8}$/.test(ext) ? ext : "";
}

export function fileTypeOf(name: string, mime?: string | null): FileTypeKind {
  const ext = fileExtension(name);
  if (ext) {
    for (const [kind, list] of Object.entries(EXTENSIONS)) {
      if (list.includes(ext)) return kind as FileTypeKind;
    }
  }
  const m = (mime || "").toLowerCase();
  if (m) {
    for (const [re, kind] of MIME_HINTS) if (re.test(m)) return kind;
  }
  return "other";
}

/** Short label printed on the icon band ("PDF", "XLSX"); "" when unknown. */
export function fileTypeLabel(name: string): string {
  const ext = fileExtension(name);
  return ext && ext.length <= 4 ? ext.toUpperCase() : "";
}

/**
 * Shorten a long file name in the middle and keep its extension:
 * "Octop-quarterly-report-final.pdf" → "Octop-quarterl…inal.pdf".
 */
export function middleEllipsis(name: string, max = 28): string {
  const chars = Array.from(name);
  if (chars.length <= max) return name;
  const ext = fileExtension(name);
  const suffix = ext ? Array.from(`.${ext}`) : [];
  const stem = chars.slice(0, chars.length - suffix.length);
  const budget = Math.max(2, max - suffix.length - 1);
  const tail = Math.min(4, Math.floor(budget / 3));
  const head = budget - tail;
  return [
    ...stem.slice(0, head),
    "…",
    ...(tail ? stem.slice(stem.length - tail) : []),
    ...suffix,
  ].join("");
}

/** 512 B · 1.5 KB · 2 MB · 12 MB (1024 base; one decimal only under 10). */
export function formatFileSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  if (unit === 0) return `${bytes} B`;
  let rounded = value < 10 ? Math.round(value * 10) / 10 : Math.round(value);
  // 1023.7 KB rounds to 1024 KB: say 1 MB instead.
  if (rounded >= 1024 && unit < units.length - 1) {
    rounded = 1;
    unit += 1;
  }
  return `${rounded} ${units[unit]}`;
}

export type FilePreviewKind = "image" | "pdf" | "csv" | "text" | "html";

const TEXT_EXTENSIONS = ["txt", "md", "markdown", "log", "json", "yaml", "yml"];

/** What a large preview card can show for this file in the browser, if anything. */
export function filePreviewKind(
  name: string,
  mime?: string | null,
): FilePreviewKind | null {
  const ext = fileExtension(name);
  const kind = fileTypeOf(name, mime);
  if (kind === "image" && ext !== "heic") return "image";
  if (kind === "pdf") return "pdf";
  if (ext === "csv" || ext === "tsv") return "csv";
  if (ext === "html" || ext === "htm") return "html";
  if (TEXT_EXTENSIONS.includes(ext)) return "text";
  return null;
}

/** Largest file each preview kind will fetch for a thumbnail. */
export const PREVIEW_MAX_BYTES: Record<FilePreviewKind, number> = {
  image: 15 * 1024 * 1024,
  pdf: 20 * 1024 * 1024,
  csv: 1024 * 1024,
  html: 1024 * 1024,
  text: 1024 * 1024,
};

/** First rows of a CSV/TSV for the excerpt table (quotes respected, no multi-line cells). */
export function csvExcerpt(
  text: string,
  delimiter: string,
  rows = 5,
  columns = 4,
): string[][] {
  const out: string[][] = [];
  for (const line of text.split(/\r?\n/)) {
    if (out.length >= rows) break;
    if (!line.trim()) continue;
    const cells: string[] = [];
    let cell = "";
    let quoted = false;
    for (let i = 0; i < line.length; i += 1) {
      const ch = line[i];
      if (quoted) {
        if (ch === '"' && line[i + 1] === '"') {
          cell += '"';
          i += 1;
        } else if (ch === '"') quoted = false;
        else cell += ch;
      } else if (ch === '"') quoted = true;
      else if (ch === delimiter) {
        cells.push(cell);
        cell = "";
      } else cell += ch;
    }
    cells.push(cell);
    out.push(cells.slice(0, columns).map((c) => c.trim()));
  }
  return out;
}
