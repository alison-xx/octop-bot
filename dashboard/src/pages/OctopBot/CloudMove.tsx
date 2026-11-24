import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Button, Modal, Progress } from "antd";
import { useTranslation } from "react-i18next";
import { botCloudApi, type CloudMoveStatus } from "../../api/modules/botCloud";
import { getDesktopBridge, isBotOnlyDesktop } from "../../utils/desktopBridge";

const LATER_KEY = "octop.bot.cloud-move.later";
const POLL_MS = 1000;

/**
 * Desktop, signed in with Lynxce: the team lives in the Octop Bot cloud, shared
 * with phones and the web. Offers to move this computer's Bots, chats and
 * groups there, then reopens the app on the cloud, already signed in.
 */
export default function CloudMove() {
  const { t } = useTranslation();
  const bridge = getDesktopBridge();
  const available = isBotOnlyDesktop() && Boolean(bridge?.useLynxceCloud);
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState<CloudMoveStatus | null>(null);
  const [error, setError] = useState("");
  const timer = useRef<number>();
  const mounted = useRef(true);
  useEffect(
    () => () => {
      mounted.current = false;
      window.clearTimeout(timer.current);
    },
    [],
  );

  const follow = useCallback(
    (next: CloudMoveStatus) => {
      if (!mounted.current) return;
      setStatus(next);
      if (next.state === "running") {
        setOpen(true);
        timer.current = window.setTimeout(() => {
          botCloudApi.moveStatus().then(follow, () => {
            if (!mounted.current) return;
            // Lost track of the move: offer the retry, which resumes it.
            setStatus({ ...next, state: "failed" });
            setError(t("botCloudMove.failed"));
          });
        }, POLL_MS);
      } else if (next.state === "done" && next.access_token) {
        setOpen(true);
        void bridge?.useLynxceCloud?.(next.access_token);
      } else if (next.state === "failed") {
        setOpen(true);
        setError(
          t(`apiErrors.${next.error_code}`, {
            defaultValue: t("botCloudMove.failed"),
          }),
        );
      }
    },
    [bridge, t],
  );

  useEffect(() => {
    if (!available) return;
    let current = true;
    Promise.all([botCloudApi.account(), botCloudApi.moveStatus()]).then(
      ([account, moving]) => {
        if (!current) return;
        if (moving.state !== "idle") follow(moving);
        else if (account.connected && !sessionStorage.getItem(LATER_KEY))
          setOpen(true);
      },
      () => undefined,
    );
    return () => {
      current = false;
    };
  }, [available, follow]);

  if (!available || !open) return null;
  const running = status?.state === "running";
  const done = status?.state === "done";
  const start = () => {
    setError("");
    botCloudApi.move().then(follow, () => setError(t("botCloudMove.failed")));
  };
  const later = () => {
    sessionStorage.setItem(LATER_KEY, "1");
    setOpen(false);
  };
  const percent =
    status && status.total > 0
      ? Math.round((status.done / status.total) * 100)
      : 0;
  return (
    <Modal
      open
      centered
      title={t("botCloudMove.title")}
      closable={!running && !done}
      maskClosable={false}
      onCancel={later}
      footer={
        running || done
          ? null
          : [
              <Button key="later" onClick={later}>
                {t("botCloudMove.later")}
              </Button>,
              <Button key="start" type="primary" onClick={start}>
                {t(error ? "botCloudMove.retry" : "botCloudMove.start")}
              </Button>,
            ]
      }
    >
      <p>{t("botCloudMove.body")}</p>
      <p>{t("botCloudMove.what")}</p>
      {(running || done) && (
        <>
          <Progress percent={done ? 100 : percent} />
          <p aria-live="polite">
            {done
              ? t("botCloudMove.switching")
              : status && status.total > 0
              ? t("botCloudMove.running", {
                  done: Math.min(status.done + 1, status.total),
                  total: status.total,
                })
              : t("botCloudMove.preparing")}
          </p>
        </>
      )}
      {error && <Alert type="error" showIcon message={error} />}
    </Modal>
  );
}
