import { useEffect, useState } from "react";
import { botInboxApi, type BotInboxItem } from "../../api/modules/botInbox";

const POLL_MS = 15_000;

/**
 * Cards my Bots are waiting on, refreshed every 15 s while the page is visible and whenever
 * it comes back to the front. Errors keep the last list (a server without the inbox: empty).
 */
export function useBotInbox(): BotInboxItem[] {
  const [items, setItems] = useState<BotInboxItem[]>([]);
  useEffect(() => {
    let alive = true;
    const load = () => {
      if (document.visibilityState !== "visible") return;
      botInboxApi
        .list()
        .then((res) => {
          if (alive) setItems(res.items ?? []);
        })
        .catch(() => undefined);
    };
    load();
    const timer = window.setInterval(load, POLL_MS);
    document.addEventListener("visibilitychange", load);
    window.addEventListener("focus", load);
    return () => {
      alive = false;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", load);
      window.removeEventListener("focus", load);
    };
  }, []);
  return items;
}
