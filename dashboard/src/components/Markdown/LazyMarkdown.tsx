import { lazy, Suspense, useEffect, useRef, useState } from "react";
import type { MarkdownProps } from "./index";

const Markdown = lazy(() => import("./index"));

function MarkdownPlainFallback({ content }: { content: string }) {
  return (
    <div style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
      {content}
    </div>
  );
}

export default function LazyMarkdown(props: MarkdownProps) {
  const { content, isStreaming } = props;
  const [shown, setShown] = useState(content);
  const latest = useRef(content);
  const painted = useRef(content);
  const timer = useRef<ReturnType<typeof setTimeout>>();
  useEffect(() => {
    latest.current = content;
    const paint = () => {
      const target = latest.current;
      let end = painted.current.length;
      const remaining = target.length - end;
      // Catch up to each batch in short steps. Final text is always immediate.
      end += Math.max(12, Math.ceil(remaining / 2));
      if (
        end < target.length &&
        target.charCodeAt(end) >= 0xdc00 &&
        target.charCodeAt(end) <= 0xdfff
      )
        end++;
      painted.current = target.slice(0, end);
      setShown(painted.current);
      timer.current = end < target.length ? setTimeout(paint, 32) : undefined;
    };
    if (
      !isStreaming ||
      !content.startsWith(painted.current) ||
      !painted.current ||
      content.length - painted.current.length > 240 ||
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches
    ) {
      clearTimeout(timer.current);
      timer.current = undefined;
      painted.current = content;
      setShown(content);
    } else if (!timer.current && painted.current !== content) {
      paint();
    }
  }, [content, isStreaming]);
  useEffect(() => () => clearTimeout(timer.current), []);
  const visible =
    isStreaming && shown && content.startsWith(shown) ? shown : content;
  return (
    <Suspense fallback={<MarkdownPlainFallback content={visible} />}>
      <Markdown {...props} content={visible} />
    </Suspense>
  );
}
