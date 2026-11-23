import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { botCloudComputerApi } from "../../api/modules/botCloudComputer";
import { apiErrorMessage } from "../../utils/apiError";
import CloudComputerInputBar from "./CloudComputerInputBar";
import styles from "./cloudComputerScreen.module.less";
import {
  copyToThisDevice,
  installMacShortcuts,
  isApplePlatform,
  type KeySender,
} from "./macShortcuts";

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

// The desktop's own copy shortcut needs a moment before its clipboard holds the selection.
const COPY_SETTLE_MS = 400;

/**
 * A Bot's cloud computer desktop through noVNC; mouse and keyboard only while taken over.
 * With a screen session, a taken-over screen also gets the input bar (IME text, clipboard)
 * and, on a Mac, ⌘ shortcuts that act like Ctrl and carry the clipboard.
 */
export default function CloudComputerScreen({
  wsPath,
  interactive,
  session = "",
}: {
  wsPath: string;
  interactive: boolean;
  session?: string;
}) {
  const { t } = useTranslation();
  const host = useRef<HTMLDivElement>(null);
  const rfb = useRef<
    (KeySender & { viewOnly: boolean; disconnect(): void }) | null
  >(null);
  const [phase, setPhase] = useState<Phase>("connecting");
  const [note, setNote] = useState("");
  // Read when the client is created: takeover may land while noVNC is still loading.
  const interactiveRef = useRef(interactive);

  useEffect(() => {
    let cancelled = false;
    void import("@novnc/novnc").then(({ default: RFB }) => {
      if (cancelled || !host.current) return;
      const client = new RFB(host.current, screenSocketUrl(wsPath), {
        wsProtocols: ["binary"],
      });
      client.scaleViewport = true;
      client.viewOnly = !interactiveRef.current;
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
  }, [wsPath]);

  useEffect(() => {
    interactiveRef.current = interactive;
    if (rfb.current) rfb.current.viewOnly = !interactive;
  }, [interactive]);

  useEffect(() => {
    if (!interactive || !host.current || !isApplePlatform()) return;
    const failed = (e: unknown) =>
      setNote(apiErrorMessage(e, t("cloudComputer.inputFailed"), t));
    return installMacShortcuts(
      host.current,
      () => rfb.current,
      session
        ? {
            paste: (text) =>
              void botCloudComputerApi
                .typeText(session, text)
                .then(() => setNote(t("cloudComputer.pasted")), failed),
            copyBack: () => {
              const pending = new Promise((done) =>
                setTimeout(done, COPY_SETTLE_MS),
              )
                .then(() => botCloudComputerApi.readClipboard(session))
                .then((r) => r.text);
              void copyToThisDevice(pending).then(
                (copied) =>
                  setNote(
                    t(
                      copied
                        ? "cloudComputer.clipboardCopied"
                        : "cloudComputer.copyBlocked",
                    ),
                  ),
                failed,
              );
            },
          }
        : null,
    );
    // Install once per session and mode; `t` changing is not a reason to reinstall.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [interactive, session]);

  const typing = interactive && session !== "";
  return (
    <>
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
      {typing && (
        <CloudComputerInputBar session={session} note={note} onNote={setNote} />
      )}
    </>
  );
}
