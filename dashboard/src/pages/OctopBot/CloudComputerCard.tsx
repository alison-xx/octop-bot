import { useEffect, useState } from "react";
import { Button } from "antd";
import { useTranslation } from "react-i18next";
import {
  botCloudComputerApi,
  type CloudComputerStatus,
} from "../../api/modules/botCloudComputer";
import { apiErrorMessage } from "../../utils/apiError";
import styles from "./botComputer.module.less";

/** Octop Bot cloud: this Bot's computer, and pausing it to stop paying for running time. */
export default function CloudComputerCard({ botId }: { botId: string }) {
  const { t } = useTranslation();
  const [status, setStatus] = useState<CloudComputerStatus | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

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
      </span>
      {status?.state === "running" && (
        <Button size="small" loading={busy} onClick={() => void pause()}>
          {t("cloudComputer.pause")}
        </Button>
      )}
    </div>
  );
}
