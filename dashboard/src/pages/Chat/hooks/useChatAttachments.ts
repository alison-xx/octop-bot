import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import type { ChangeEvent, ClipboardEvent, DragEvent } from "react";
import { useTranslation } from "react-i18next";
import { uploadFile } from "../../../api/modules/upload";
import { agentAttachmentAccessUrl } from "../../../utils/toolMediaBlocks";
import type { ChatAttachment } from "./useChat";
import { message as antMessage } from "@/utils/antdMessage";
import { apiErrorMessage } from "../../../utils/apiError";

import { inferAttachmentKind } from "../utils/chatAttachments";
import {
  DESKTOP_FILE_DROP_EVENT,
  filesFromDesktopDrop,
  type DesktopFileDropDetail,
} from "../../../utils/desktopFileDrop";
import {
  dragHasFiles,
  filesFromSnapshot,
  MAX_CHAT_UPLOAD_FILES,
  snapshotDroppedEntries,
  type CollectedDrop,
} from "../utils/droppedFiles";
import { useServerUploadLimit } from "../../../hooks/useServerUploadLimit";

export function useChatAttachments(
  agentId: string | null | undefined,
  threadId?: string | null,
) {
  const { t } = useTranslation();
  const { maxUploadBytes, maxUploadMb } = useServerUploadLimit();
  const [attachments, setAttachments] = useState<ChatAttachment[]>([]);
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const current = useRef({ batches: 0 });
  useLayoutEffect(() => {
    current.current = { batches: 0 };
    setUploading(false);
    return () => {
      current.current = { batches: 0 };
    };
  }, [agentId, threadId]);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);

  const processFiles = useCallback(
    async (files: FileList | File[]) => {
      const incoming = Array.from(files);
      const capped =
        incoming.length > MAX_CHAT_UPLOAD_FILES
          ? incoming.slice(0, MAX_CHAT_UPLOAD_FILES)
          : incoming;
      if (incoming.length > MAX_CHAT_UPLOAD_FILES) {
        antMessage.warning(
          t(
            "upload.tooMany",
            "Only the first {{max}} files can be uploaded at once",
            { max: MAX_CHAT_UPLOAD_FILES },
          ),
        );
      }
      const fileArr = capped.filter((f) => {
        if (f.size > maxUploadBytes) {
          antMessage.error(
            t("upload.tooLarge", "File too large (max {{maxMb}}MB): {{name}}", {
              name: f.name,
              maxMb: maxUploadMb,
            }),
          );
          return false;
        }
        return true;
      });

      if (fileArr.length === 0) return;

      if (!agentId) {
        antMessage.error(t("upload.failed", "Upload failed"));
        return;
      }

      const scope = current.current;
      scope.batches++;
      setUploading(true);
      const results: ChatAttachment[] = [];
      const errors: string[] = [];
      const pending = fileArr.entries();
      async function uploadNext(owner: string) {
        for (const [index, file] of pending) {
          if (current.current !== scope) return;
          try {
            const res = await uploadFile(owner, file);
            const workspacePath = res.path || res.workspace_path;
            results[index] = {
              url:
                res.access_url ||
                res.url ||
                agentAttachmentAccessUrl(owner, workspacePath, res.media_type),
              filename: res.filename,
              mediaType: res.media_type,
              size: file.size,
              workspacePath,
              kind: inferAttachmentKind(file, res.media_type),
            };
          } catch (err) {
            errors.push(
              file.name +
                " — " +
                apiErrorMessage(err, t("upload.failed", "Upload failed"), t),
            );
          }
        }
      }
      try {
        await Promise.all(
          Array.from({ length: Math.min(3, fileArr.length) }, () =>
            uploadNext(agentId),
          ),
        );
        if (current.current !== scope) return;
        setAttachments((prev) => [...prev, ...results.filter(Boolean)]);
        if (errors.length) antMessage.error(errors.join("\n"));
      } finally {
        scope.batches--;
        if (current.current === scope) setUploading(scope.batches > 0);
      }
    },
    [agentId, maxUploadBytes, maxUploadMb, t],
  );

  const handleFileSelect = useCallback(() => {
    fileInputRef.current?.click();
  }, []);

  const handleFolderSelect = useCallback(() => {
    const input = folderInputRef.current;
    if (!input) return;
    input.setAttribute("webkitdirectory", "");
    input.click();
  }, []);

  const handleFileChange = useCallback(
    (e: ChangeEvent<HTMLInputElement>) => {
      if (e.target.files && e.target.files.length > 0) {
        void processFiles(e.target.files);
      }
      e.target.value = "";
    },
    [processFiles],
  );

  const removeAttachment = useCallback((index: number) => {
    setAttachments((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const clearAttachments = useCallback(() => {
    setAttachments([]);
  }, []);

  const restoreAttachments = useCallback((next: ChatAttachment[]) => {
    setAttachments(next.map((a) => ({ ...a })));
  }, []);

  const handlePaste = useCallback(
    (e: ClipboardEvent) => {
      const items = e.clipboardData?.items;
      if (!items) return;
      const pastedFiles: File[] = [];
      for (let i = 0; i < items.length; i++) {
        const item = items[i];
        if (item.kind === "file") {
          const file = item.getAsFile();
          if (file) pastedFiles.push(file);
        }
      }
      if (pastedFiles.length > 0) {
        e.preventDefault();
        void processFiles(pastedFiles);
      }
    },
    [processFiles],
  );

  const handleDragEnter = useCallback((e: DragEvent) => {
    if (!dragHasFiles(e.dataTransfer)) return;
    e.preventDefault();
    e.stopPropagation();
    setDragOver(true);
  }, []);

  const handleDragLeave = useCallback((e: DragEvent<HTMLElement>) => {
    const next = e.relatedTarget;
    if (next instanceof Node && e.currentTarget.contains(next)) return;
    e.preventDefault();
    e.stopPropagation();
    setDragOver(false);
  }, []);

  const handleDragOver = useCallback((e: DragEvent) => {
    if (!dragHasFiles(e.dataTransfer)) return;
    e.preventDefault();
    e.stopPropagation();
    e.dataTransfer.dropEffect = "copy";
    setDragOver(true);
  }, []);

  const handleDrop = useCallback(
    (e: DragEvent) => {
      const scope = current.current;
      const snapshot = snapshotDroppedEntries(e.dataTransfer);
      if (!snapshot.hadFileItems) return;
      e.preventDefault();
      e.stopPropagation();
      setDragOver(false);
      return (async () => {
        let collected: CollectedDrop;
        try {
          collected = await filesFromSnapshot(snapshot);
        } catch {
          antMessage.error(t("upload.failed", "Upload failed"));
          return;
        }
        if (current.current !== scope) return;
        if (collected.truncated) {
          antMessage.warning(
            t(
              "upload.tooMany",
              "Only the first {{max}} files can be uploaded at once",
              { max: MAX_CHAT_UPLOAD_FILES },
            ),
          );
        }
        if (collected.files.length === 0) {
          antMessage.warning(t("upload.emptyDrop", "No files to upload"));
          return;
        }
        await processFiles(collected.files);
      })();
    },
    [processFiles, t],
  );

  useEffect(() => {
    const onDesktopDrop = (event: Event) => {
      const scope = current.current;
      const detail = (event as CustomEvent<DesktopFileDropDetail>).detail;
      setDragOver(false);
      void (async () => {
        if (detail?.truncated) {
          antMessage.warning(
            t(
              "upload.tooMany",
              "Only the first {{max}} files can be uploaded at once",
              { max: detail.max ?? 500 },
            ),
          );
        }
        try {
          const files = await filesFromDesktopDrop(detail);
          if (current.current !== scope) return;
          if (files.length === 0) {
            antMessage.warning(t("upload.emptyDrop", "No files to upload"));
            return;
          }
          await processFiles(files);
        } catch {
          antMessage.error(t("upload.failed", "Upload failed"));
        }
      })();
    };
    window.addEventListener(DESKTOP_FILE_DROP_EVENT, onDesktopDrop);
    return () =>
      window.removeEventListener(DESKTOP_FILE_DROP_EVENT, onDesktopDrop);
  }, [processFiles, t]);

  return {
    attachments,
    uploading,
    dragOver,
    fileInputRef,
    folderInputRef,
    processFiles,
    handleFileSelect,
    handleFolderSelect,
    handleFileChange,
    removeAttachment,
    clearAttachments,
    restoreAttachments,
    handlePaste,
    handleDragEnter,
    handleDragLeave,
    handleDragOver,
    handleDrop,
  };
}
