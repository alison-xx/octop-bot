import { useState } from "react";
import { Check, Copy, TextQuote } from "lucide-react";
import { useTranslation } from "react-i18next";
import { copyText } from "../../../utils/copyText";
import { message } from "../../../utils/antdMessage";
import styles from "../index.module.less";

export function CopyButton({ text }: { text: string }) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className={styles.msgCopyBtn}
      title={t("common.copy")}
      aria-label={t("common.copy")}
      onBlur={() => setCopied(false)}
      onMouseLeave={() => setCopied(false)}
      onClick={async () => {
        if (await copyText(text)) {
          setCopied(true);
          message.success(t("common.copied"));
        } else message.error(t("common.copyFailed"));
      }}
    >
      {copied ? <Check size={14} /> : <Copy size={14} />}
    </button>
  );
}

export function QuoteButton({
  text,
  onQuote,
}: {
  text: string;
  onQuote: (quote: string) => void;
}) {
  const { t } = useTranslation();
  return (
    <button
      type="button"
      className={styles.msgCopyBtn}
      title={t("botDirectory.quote")}
      aria-label={t("botDirectory.quote")}
      onMouseDown={(event) => event.preventDefault()}
      onClick={(event) => {
        const body = event.currentTarget
          .closest("[data-quotable-message]")
          ?.querySelector("[data-quote-body]");
        const selection = window.getSelection();
        const excerpt =
          selection &&
          body?.contains(selection.anchorNode) &&
          body.contains(selection.focusNode)
            ? selection.toString().trim()
            : "";
        const quote = (excerpt || text)
          .trim()
          .split(/\r?\n/)
          .map((line) => "> " + line)
          .join("\n");
        onQuote(quote + "\n\n");
      }}
    >
      <TextQuote size={14} />
    </button>
  );
}
