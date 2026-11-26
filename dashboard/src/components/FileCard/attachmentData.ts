/**
 * Size and preview bytes for chat file cards, fetched once per URL.
 *
 * Sizes come from ``HEAD …/workspace/download`` (headers only). Preview bytes
 * are fetched only for files small enough to thumbnail.
 */

import { useEffect, useState } from "react";
import { requestBlob, requestHead } from "../../api/request";
import { isDataUrl, needsAuthBlobFetch } from "../../utils/toolMediaBlocks";

const sizes = new Map<string, Promise<number | null>>();
const blobs = new Map<string, Promise<Blob>>();
/** Keep at most this many preview blobs in memory (oldest dropped first). */
const MAX_BLOBS = 24;

function apiPath(url: string): string {
  if (url.startsWith("http")) {
    const parsed = new URL(url);
    return parsed.pathname.replace(/^\/api/, "") + parsed.search;
  }
  return url.replace(/^\/api/, "");
}

function dataUrlSize(url: string): number | null {
  const comma = url.indexOf(",");
  if (comma < 0) return null;
  const body = url.slice(comma + 1);
  if (!/;base64$/i.test(url.slice(0, comma))) return body.length;
  const pad = body.endsWith("==") ? 2 : body.endsWith("=") ? 1 : 0;
  return Math.floor((body.length * 3) / 4) - pad;
}

/** File size in bytes, or ``null`` when the server cannot tell (older servers, plain links). */
export function loadAttachmentSize(url: string): Promise<number | null> {
  let pending = sizes.get(url);
  if (!pending) {
    if (isDataUrl(url)) pending = Promise.resolve(dataUrlSize(url));
    else if (!url.includes("/workspace/download"))
      pending = Promise.resolve(null);
    else
      pending = requestHead(apiPath(url))
        .then((headers) => {
          const raw = headers.get("content-length");
          if (!raw) return null;
          const n = Number(raw);
          return Number.isFinite(n) && n >= 0 ? n : null;
        })
        .catch(() => null);
    sizes.set(url, pending);
  }
  return pending;
}

/** The file's bytes for a thumbnail (authenticated when the URL needs it). */
export function loadAttachmentBlob(url: string): Promise<Blob> {
  let pending = blobs.get(url);
  if (!pending) {
    pending =
      needsAuthBlobFetch(url) && !isDataUrl(url)
        ? requestBlob(apiPath(url))
        : fetch(url).then((r) => {
            if (!r.ok) throw new Error(`Request failed: ${r.status}`);
            return r.blob();
          });
    pending.catch(() => blobs.delete(url));
    blobs.set(url, pending);
    if (blobs.size > MAX_BLOBS) {
      const oldest = blobs.keys().next().value;
      if (oldest !== undefined) blobs.delete(oldest);
    }
  }
  return pending;
}

/** ``undefined`` while loading, then the size in bytes or ``null`` when unknown. */
export function useAttachmentSize(
  url: string,
  knownSize?: number,
): number | null | undefined {
  const [size, setSize] = useState<number | null | undefined>(undefined);
  useEffect(() => {
    if (knownSize !== undefined) return;
    let live = true;
    setSize(undefined);
    void loadAttachmentSize(url).then((n) => {
      if (live) setSize(n);
    });
    return () => {
      live = false;
    };
  }, [url, knownSize]);
  return knownSize ?? size;
}

/** Test hook: forget cached sizes and bytes. */
export function resetAttachmentCache(): void {
  sizes.clear();
  blobs.clear();
}
