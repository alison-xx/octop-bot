import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import { downloadAuthFile } from "../../../components/AuthFileDownloadLink";
import FileCard from "../../../components/FileCard/FileCard";
import { useAttachmentSize } from "../../../components/FileCard/attachmentData";
import { saveBlobAsFile } from "../../../utils/saveBlobAsFile";
import { isDesktopShell } from "../../../utils/desktopBridge";
import {
  isDataUrl,
  needsAuthBlobFetch,
  workspacePathFromAccessUrl,
} from "../../../utils/toolMediaBlocks";
import { getDocKind } from "../../Agent/Workspace/utils/docKind";
import { getMediaKind } from "../../Agent/Workspace/utils/mediaKind";
import { isProbablyText } from "../../Agent/Workspace/utils/fileKind";
import { useChatFilePreview } from "../ChatFilePreviewContext";

import { message as antMessage } from "@/utils/antdMessage";

/** Files the browser can render inline (vs. pure binary blobs). */
function isPreviewable(name: string): boolean {
  return (
    isProbablyText(name) ||
    getMediaKind(name) !== null ||
    getDocKind(name) !== null
  );
}

function nameFromUrl(url: string): string | undefined {
  const path = workspacePathFromAccessUrl(url);
  return path?.split(/[\\/]/).filter(Boolean).pop();
}

/**
 * Authenticated file card for chat / tool-result non-image files: click opens
 * the preview panel (or downloads), the button downloads. ``rich`` adds a
 * visual preview (image, PDF first page, text excerpt) when the file is small.
 */
export function MessageFileCard({
  url,
  filename,
  agentId,
  workspacePath,
  mediaType,
  rich,
}: {
  url: string;
  filename?: string;
  agentId?: string | null;
  workspacePath?: string;
  mediaType?: string;
  rich?: boolean;
}) {
  const { t } = useTranslation();
  const filePreview = useChatFilePreview();
  const [loading, setLoading] = useState(false);
  const needsAuth = needsAuthBlobFetch(url) || isDataUrl(url);
  const label = filename || nameFromUrl(url) || url;
  const size = useAttachmentSize(url);

  const resolvedPath = workspacePath || workspacePathFromAccessUrl(url) || "";
  const previewable = Boolean(
    resolvedPath && agentId && isPreviewable(label) && filePreview,
  );

  const handleDownload = useCallback(async () => {
    if (!needsAuth) {
      if (isDesktopShell()) {
        setLoading(true);
        try {
          const res = await fetch(url);
          if (!res.ok) throw new Error("download failed");
          const blob = await res.blob();
          await saveBlobAsFile(blob, filename || "download");
        } catch {
          antMessage.error(t("chat.downloadFailed", "下载失败，请重试"));
        } finally {
          setLoading(false);
        }
        return;
      }
      const a = document.createElement("a");
      a.href = url;
      a.download = filename || "download";
      a.target = "_blank";
      a.rel = "noreferrer";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      return;
    }
    setLoading(true);
    try {
      await downloadAuthFile(url, { filename });
    } catch {
      antMessage.error(t("chat.downloadFailed", "下载失败，请重试"));
    } finally {
      setLoading(false);
    }
  }, [url, filename, needsAuth, t]);

  const openPreview = useCallback(() => {
    if (previewable && resolvedPath && filePreview) {
      filePreview.openFilePreview(resolvedPath, agentId);
    }
  }, [previewable, resolvedPath, filePreview, agentId]);

  return (
    <FileCard
      name={label}
      mime={mediaType}
      size={size}
      previewUrl={rich ? url : undefined}
      onOpen={previewable ? openPreview : undefined}
      onDownload={() => void handleDownload()}
      downloading={loading}
    />
  );
}
