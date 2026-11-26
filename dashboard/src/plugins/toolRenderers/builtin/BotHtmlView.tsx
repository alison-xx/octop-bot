import { useMemo } from "react";
import DOMPurify from "dompurify";
import styles from "./BotViewRenderer.module.less";

export default function BotHtmlView({
  html,
  title,
  thumbnail = false,
}: {
  html: string;
  title: string;
  thumbnail?: boolean;
}) {
  const srcDoc = useMemo(() => {
    const template = document.createElement("template");
    template.innerHTML = html;
    const markup = DOMPurify.sanitize(template.content, {
      FORBID_TAGS: [
        "meta",
        "link",
        "base",
        "form",
        "iframe",
        "object",
        "embed",
        "script",
        "audio",
        "video",
        "source",
      ],
      FORBID_ATTR: [
        "href",
        "xlink:href",
        "src",
        "srcset",
        "target",
        "action",
        "formaction",
        "ping",
        "background",
        "autofocus",
      ],
    });
    const csp =
      "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'";
    return (
      '<!doctype html><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="' +
      csp +
      '"><style>html{color-scheme:light dark}body{margin:12px;font:14px/1.5 system-ui,sans-serif;overflow-wrap:anywhere}</style>' +
      markup
    );
  }, [html]);
  return (
    <iframe
      className={styles.frame}
      title={title}
      tabIndex={thumbnail ? -1 : undefined}
      sandbox=""
      referrerPolicy="no-referrer"
      srcDoc={srcDoc}
    />
  );
}
