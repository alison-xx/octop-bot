import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  botCloudComputerApi,
  viewOnlyScreen,
  type ScreenSession,
} from "../../api/modules/botCloudComputer";
import { ACCESS_TOKEN_RENEWED_EVENT, getAuthToken } from "../../api/request";
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
  botId,
  session = "",
}: {
  wsPath: string;
  interactive: boolean;
  session?: ScreenSession;
  botId?: string;
}) {
  const { t } = useTranslation();
  const host = useRef<HTMLDivElement>(null);
  const rfb = useRef<
    (KeySender & { viewOnly: boolean; disconnect(): void }) | null
  >(null);
  const [phase, setPhase] = useState<Phase>("connecting");
  const [note, setNote] = useState("");
  // Read when the client is created: takeover may land while noVNC is still loading.
  const viewOnly = viewOnlyScreen(session);
  const canControl = interactive && !viewOnly;
  const expiresAt =
    typeof session === "object" && "expiresAt" in session
      ? session.expiresAt
      : undefined;
  const [expired, setExpired] = useState(false);
  useEffect(() => {
    setExpired(false);
    if (expiresAt === undefined) return;
    const timeout = window.setTimeout(
      () => setExpired(true),
      Math.max(0, expiresAt - Date.now()),
    );
    return () => window.clearTimeout(timeout);
  }, [expiresAt]);
  const interactiveRef = useRef(canControl);

  useEffect(() => {
    // Negotiated desktop sessions expire with the original sign-in and ticket.
    if (
      !botId ||
      !session ||
      viewOnlyScreen(session) ||
      (typeof session === "object" && !session.renewable)
    )
      return;
    let lastToken = "";
    // The viewer can stay open across sliding login renewals. Only a changed
    // sign-in credential needs sending; this never starts or resumes a computer.
    const renew = () => {
      const token = getAuthToken();
      if (!token || token === lastToken) return;
      lastToken = token;
      void botCloudComputerApi.renewScreen(botId, session).catch(() => {
        if (lastToken === token) lastToken = "";
      });
    };
    renew();
    window.addEventListener(ACCESS_TOKEN_RENEWED_EVENT, renew);
    window.addEventListener("storage", renew);
    return () => {
      window.removeEventListener(ACCESS_TOKEN_RENEWED_EVENT, renew);
      window.removeEventListener("storage", renew);
    };
  }, [botId, session]);

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
    interactiveRef.current = canControl;
    if (rfb.current) rfb.current.viewOnly = !canControl;
  }, [canControl]);

  useEffect(() => {
    if (
      !canControl ||
      expired ||
      !host.current ||
      !isApplePlatform() ||
      (typeof session === "object" && phase !== "connected")
    )
      return;
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
  }, [canControl, expired, session, phase]);

  const typing =
    canControl &&
    !expired &&
    session !== "" &&
    (typeof session === "string" || phase === "connected");
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
