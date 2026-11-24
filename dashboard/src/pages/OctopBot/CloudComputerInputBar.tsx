import { useRef, useState, type KeyboardEvent } from "react";
import { Button, Input } from "antd";
import type { TextAreaRef } from "antd/es/input/TextArea";
import { useTranslation } from "react-i18next";
import { botCloudComputerApi } from "../../api/modules/botCloudComputer";
import { apiErrorMessage } from "../../utils/apiError";
import styles from "./cloudComputerScreen.module.less";
import { copyToThisDevice, isMacDesktop } from "./macShortcuts";

/**
 * Under a taken-over cloud computer screen: type with this device's own input method (Chinese
 * included) or paste here, and send it to the desktop's cursor; or bring the desktop's
 * clipboard back to this device. VNC keys cannot carry either, so both go through Octop.
 */
export default function CloudComputerInputBar({
  session,
  note,
  onNote: setNote,
}: {
  session: string;
  /** Last result to show, shared with the screen's ⌘ shortcuts. */
  note: string;
  onNote: (note: string) => void;
}) {
  const { t } = useTranslation();
  const field = useRef<TextAreaRef>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState<"type" | "clipboard" | null>(null);

  const send = async () => {
    if (!text || busy) return;
    setBusy("type");
    try {
      await botCloudComputerApi.typeText(session, text);
      setText("");
      setNote(t("cloudComputer.typed"));
    } catch (e) {
      setNote(apiErrorMessage(e, t("cloudComputer.inputFailed"), t));
    } finally {
      setBusy(null);
    }
  };

  const fetchClipboard = async () => {
    if (busy) return;
    setBusy("clipboard");
    const pending = botCloudComputerApi
      .readClipboard(session)
      .then((r) => r.text);
    // Start the write inside the click, so Safari still counts it as the user's gesture.
    const copied = copyToThisDevice(pending).catch(() => false);
    try {
      const value = await pending;
      if (!value) {
        setNote(t("cloudComputer.clipboardEmpty"));
      } else if (await copied) {
        setNote(t("cloudComputer.clipboardCopied"));
      } else {
        // No clipboard access here: leave it selected in the field to copy by hand.
        setText(value);
        setNote(t("cloudComputer.clipboardShown"));
        requestAnimationFrame(() => field.current?.focus({ cursor: "all" }));
      }
    } catch (e) {
      setNote(apiErrorMessage(e, t("cloudComputer.inputFailed"), t));
    } finally {
      setBusy(null);
    }
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter sends; Shift+Enter is a new line; Enter that confirms an IME word is not a send.
    if (e.key !== "Enter" || e.shiftKey || e.nativeEvent.isComposing) return;
    e.preventDefault();
    void send();
  };

  return (
    <div className={styles.inputBar} data-testid="cloud-computer-input">
      <Input.TextArea
        ref={field}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKeyDown}
        placeholder={t("cloudComputer.inputPlaceholder")}
        autoSize={{ minRows: 1, maxRows: 4 }}
        maxLength={20000}
      />
      <div className={styles.inputActions}>
        <Button
          type="primary"
          disabled={!text}
          loading={busy === "type"}
          onClick={() => void send()}
        >
          {t("cloudComputer.typeIn")}
        </Button>
        <Button
          loading={busy === "clipboard"}
          onClick={() => void fetchClipboard()}
        >
          {t("cloudComputer.fetchClipboard")}
        </Button>
        <span className={styles.inputNote} role="status">
          {note || (isMacDesktop() ? t("cloudComputer.macShortcuts") : "")}
        </span>
      </div>
    </div>
  );
}
