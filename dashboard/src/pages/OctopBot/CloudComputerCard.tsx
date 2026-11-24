import { useEffect, useState } from "react";
import { Button, Modal, Space } from "antd";
import { useTranslation } from "react-i18next";
import {
  botCloudComputerApi,
  type CloudComputerStatus,
} from "../../api/modules/botCloudComputer";
import { apiErrorMessage } from "../../utils/apiError";
import styles from "./botComputer.module.less";
import CloudComputerScreen from "./CloudComputerScreen";

/** Octop Bot cloud: this Bot's computer, and pausing it to stop paying for running time. */
export default function CloudComputerCard({ botId }: { botId: string }) {
  const { t } = useTranslation();
  const [status, setStatus] = useState<CloudComputerStatus | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  // One-time WebSocket path for the open screen; null while the screen is closed.
  const [screen, setScreen] = useState<string | null>(null);
  // Screen session for typing and the clipboard while it is open.
  const [session, setSession] = useState("");

  useEffect(() => {
    let mounted = true;
    botCloudComputerApi
      .status(botId)
      .then((next) => {
        if (!mounted) return;
        setStatus(next);
        setError("");
      })
      .catch(
        (e) =>
          mounted &&
          setError(apiErrorMessage(e, t("cloudComputer.unavailable"), t)),
      );
    return () => {
      mounted = false;
    };
    // Reload for another Bot, not when translations change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [botId]);

  const pause = async () => {
    setBusy(true);
    try {
      setStatus(await botCloudComputerApi.pause(botId));
    } catch (e) {
      setError(apiErrorMessage(e, t("cloudComputer.unavailable"), t));
    } finally {
      setBusy(false);
    }
  };

  const openScreen = async () => {
    setBusy(true);
    try {
      const ticket = await botCloudComputerApi.openScreen(botId);
      setSession(ticket.session);
      setScreen(ticket.ws_path);
      setStatus(await botCloudComputerApi.status(botId));
    } catch (e) {
      setError(apiErrorMessage(e, t("cloudComputer.unavailable"), t));
    } finally {
      setBusy(false);
    }
  };

  const takeover = async (active: boolean) => {
    setBusy(true);
    try {
      setStatus(await botCloudComputerApi.takeover(botId, active));
    } catch (e) {
      setError(apiErrorMessage(e, t("cloudComputer.unavailable"), t));
    } finally {
      setBusy(false);
    }
  };

  const minutes =
    status?.state === "running" && status.running_since
      ? Math.max(1, Math.round((Date.now() / 1000 - status.running_since) / 60))
      : null;

  return (
    <div className={styles.card} data-testid="cloud-computer">
      <span className={styles.text}>
        <strong>
          {error
            ? t("cloudComputer.unavailable")
            : status
            ? t(`cloudComputer.state.${status.state}`)
            : "…"}
        </strong>
        <small>
          {minutes !== null
            ? t("cloudComputer.runningFor", { minutes })
            : t("cloudComputer.hint")}
        </small>
        {!!status?.disk_gb && (
          <small>
            {t("cloudComputer.diskFee", {
              gb: status.disk_gb,
              credits: status.disk_daily_credits,
            })}
            {!status.disk_billing && ` · ${t("cloudComputer.diskBillingOff")}`}
          </small>
        )}
        {status?.reclaim_notified && (
          <small className={styles.overdue}>
            {t("cloudComputer.reclaimWarning")}
          </small>
        )}
        {!!status?.disk_overdue_days && (
          <small className={styles.overdue}>
            {t("cloudComputer.diskOverdue", { days: status.disk_overdue_days })}
          </small>
        )}
      </span>
      <Space size={6}>
        {status && (
          <Button size="small" loading={busy} onClick={() => void openScreen()}>
            {t("cloudComputer.view")}
          </Button>
        )}
        {status?.state === "running" && !status.takeover && (
          <Button size="small" disabled={busy} onClick={() => void pause()}>
            {t("cloudComputer.pause")}
          </Button>
        )}
      </Space>
      <Modal
        open={screen !== null}
        title={t("cloudComputer.section")}
        width={960}
        footer={
          <Space>
            <span>
              {t(
                status?.takeover
                  ? "cloudComputer.controlHint"
                  : "cloudComputer.viewHint",
              )}
            </span>
            <Button
              type={status?.takeover ? "default" : "primary"}
              loading={busy}
              onClick={() => void takeover(!status?.takeover)}
            >
              {t(
                status?.takeover
                  ? "cloudComputer.handBack"
                  : "cloudComputer.takeOver",
              )}
            </Button>
          </Space>
        }
        onCancel={() => {
          setScreen(null);
          // Closing the screen hands the computer back to the Bot.
          if (status?.takeover) void takeover(false);
        }}
        destroyOnClose
      >
        {screen && (
          <CloudComputerScreen
            wsPath={screen}
            interactive={status?.takeover === true}
            session={session}
          />
        )}
      </Modal>
    </div>
  );
}
