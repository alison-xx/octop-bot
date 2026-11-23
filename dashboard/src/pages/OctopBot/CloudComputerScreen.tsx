import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import styles from "./cloudComputerScreen.module.less";

/** `/api/…/screen/ws?ticket=…` on this page's server → a ws(s):// URL. */
export function screenSocketUrl(
  wsPath: string,
  origin = window.location.origin,
): string {
  const url = new URL(wsPath, origin);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

type Phase = "connecting" | "connected" | "closed";

/** A Bot's cloud computer desktop through noVNC; mouse and keyboard only while taken over. */
export default function CloudComputerScreen({
  wsPath,
  interactive,
}: {
  wsPath: string;
  interactive: boolean;
}) {
  const { t } = useTranslation();
  const host = useRef<HTMLDivElement>(null);
  const rfb = useRef<{ viewOnly: boolean; disconnect(): void } | null>(null);
  const [phase, setPhase] = useState<Phase>("connecting");

  useEffect(() => {
    let cancelled = false;
    void import("@novnc/novnc").then(({ default: RFB }) => {
      if (cancelled || !host.current) return;
      const client = new RFB(host.current, screenSocketUrl(wsPath), {
        wsProtocols: ["binary"],
      });
      client.scaleViewport = true;
      client.viewOnly = !interactive;
      client.addEventListener("connect", () => setPhase("connected"));
      client.addEventListener("disconnect", () => setPhase("closed"));
      rfb.current = client;
    });
    return () => {
      cancelled = true;
      rfb.current?.disconnect();
      rfb.current = null;
    };
    // A new ticket means a new connection; interactivity changes in place below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wsPath]);

  useEffect(() => {
    if (rfb.current) rfb.current.viewOnly = !interactive;
  }, [interactive]);

  return (
    <div className={styles.frame} data-phase={phase}>
      <div ref={host} className={styles.screen} />
      {phase !== "connected" && (
        <p className={styles.note} role="status">
          {t(
            phase === "closed"
              ? "cloudComputer.screenClosed"
              : "cloudComputer.screenConnecting",
          )}
        </p>
      )}
    </div>
  );
}
