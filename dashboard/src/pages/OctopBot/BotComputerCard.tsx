import { useEffect, useState } from "react";
import { Alert, Button, Modal, Select, Spin } from "antd";
import { Moon, ShieldAlert } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  botComputerApi as api,
  type ComputerApp,
  type ComputerLevel,
  type ComputerPermission,
  type ComputerState,
} from "../../api/modules/botComputer";
import { useDesktopStream } from "../../hooks/useDesktopStream";
import { apiErrorMessage } from "../../utils/apiError";
import { getDesktopBridge } from "../../utils/desktopBridge";
import styles from "./botComputer.module.less";

const LEVELS: ComputerLevel[] = ["off", "view", "background", "foreground"];

/** The bot's computer: live view of the host desktop through the remote desktop stream. */
export default function BotComputerCard({ botId }: { botId: string }) {
  const { t } = useTranslation();
  const [state, setState] = useState<ComputerState | null>(null);
  const [apps, setApps] = useState<ComputerApp[]>([]);
  const [level, setLevel] = useState<ComputerLevel>("off");
  const [ids, setIds] = useState<string[]>([]);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [frame, setFrame] = useState("");
  const [attempt, setAttempt] = useState(0);
  const { status, connect, disconnect } = useDesktopStream();
  // Missing macOS grants: the screen stream is refused, so ask for them instead of spinning.
  const needs = state?.available ? state.permissions_needed ?? [] : [];
  const live = Boolean(
    state?.available && state.level !== "off" && needs.length === 0,
  );

  useEffect(() => {
    let current = true;
    const read = () =>
      api.state(botId).then(
        (next) => current && setState(next),
        (e) => current && setError(apiErrorMessage(e, t("octopBot.failed"), t)),
      );
    void read();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void read();
    }, 3000);
    return () => {
      current = false;
      window.clearInterval(timer);
    };
  }, [botId, t]);

  // One stream per user: a slow thumbnail in the panel, a smooth view when open.
  useEffect(() => {
    if (!live) {
      setFrame("");
      return;
    }
    connect(
      { onFrame: (data) => setFrame("data:image/jpeg;base64," + data) },
      open ? { quality: 70, maxFps: 8 } : { quality: 35, maxFps: 1 },
    );
    return () => disconnect();
  }, [live, open, attempt, connect, disconnect]);

  useEffect(() => {
    if (!open) return;
    let current = true;
    Promise.all([api.state(botId), api.apps(botId)]).then(
      ([now, candidates]) => {
        if (!current) return;
        setState(now);
        setLevel(now.level);
        setIds(now.apps.map((a) => a.id));
        setApps([
          ...new Map(
            [...now.apps, ...candidates].map((a) => [a.id, a]),
          ).values(),
        ]);
      },
      (e) => current && setError(apiErrorMessage(e, t("octopBot.failed"), t)),
    );
    return () => {
      current = false;
    };
  }, [botId, open, t]);

  async function update(operation: Promise<ComputerState>) {
    setBusy(true);
    setError("");
    try {
      setState(await operation);
    } catch (e) {
      setError(apiErrorMessage(e, t("octopBot.failed"), t));
    } finally {
      setBusy(false);
    }
  }

  const summary = !state
    ? ""
    : needs.length
    ? t("octopBot.computer.needsPermission")
    : !live
    ? t("octopBot.computer.asleep")
    : state.paused
    ? t("octopBot.computer.paused")
    : state.active_app
    ? t("octopBot.computer.using", { app: state.active_app })
    : t("octopBot.computer." + state.level);
  const screen = (big: boolean) =>
    needs.length ? (
      <ShieldAlert size={big ? 22 : 16} className={styles.warn} />
    ) : frame ? (
      <img className={styles.frame} src={frame} alt="" draggable={false} />
    ) : live && status === "error" ? (
      big ? (
        <span className={styles.failed}>
          {t("octopBot.computer.streamFailed")}
          <Button size="small" onClick={() => setAttempt((n) => n + 1)}>
            {t("octopBot.retry")}
          </Button>
        </span>
      ) : (
        <Moon size={14} />
      )
    ) : live ? (
      <Spin size={big ? "default" : "small"} />
    ) : (
      <span className={styles.asleep}>
        <Moon size={big ? 22 : 14} />
      </span>
    );

  return (
    <>
      <button
        type="button"
        className={styles.card}
        onClick={() => {
          setError("");
          setOpen(true);
        }}
      >
        <span className={styles.text}>
          <strong>{t("octopBot.computer.card")}</strong>
          <small>{summary}</small>
        </span>
        <span className={styles.thumb} data-live={live || undefined}>
          {screen(false)}
        </span>
      </button>
      <Modal
        open={open}
        title={t("octopBot.computer.card")}
        width={880}
        footer={null}
        onCancel={() => setOpen(false)}
        destroyOnClose
      >
        {error && <Alert type="error" message={error} showIcon />}
        {needs.length ? (
          <ComputerPermissions needs={needs} />
        ) : (
          <div className={styles.view} data-live={live || undefined}>
            {screen(true)}
          </div>
        )}
        {state && !state.available ? (
          <Alert type="info" message={t("octopBot.computer.unavailable")} />
        ) : (
          state && (
            <div className={styles.controls}>
              <label>
                <span>{t("octopBot.computer.level")}</span>
                <Select
                  value={level}
                  onChange={setLevel}
                  options={LEVELS.map((v) => ({
                    value: v,
                    label: t("octopBot.computer." + v),
                  }))}
                />
              </label>
              <label className={styles.apps}>
                <span>{t("octopBot.computer.apps")}</span>
                <Select
                  mode="multiple"
                  showSearch
                  optionFilterProp="label"
                  value={ids}
                  onChange={setIds}
                  options={apps.map((a) => ({ value: a.id, label: a.name }))}
                />
              </label>
              <div className={styles.actions}>
                {live && (
                  <Button
                    loading={busy}
                    onClick={() => void update(api.pause(botId, !state.paused))}
                  >
                    {t(
                      state.paused
                        ? "octopBot.computer.resume"
                        : "octopBot.computer.takeover",
                    )}
                  </Button>
                )}
                <Button
                  type="primary"
                  loading={busy}
                  onClick={() => void update(api.save(botId, level, ids))}
                >
                  {t("common.save")}
                </Button>
              </div>
            </div>
          )
        )}
      </Modal>
    </>
  );
}

const PERMISSION_TEXT: Record<ComputerPermission, [string, string]> = {
  screen_recording: [
    "octopBot.computer.permScreen",
    "octopBot.computer.permScreenHint",
  ],
  accessibility: [
    "octopBot.computer.permAccessibility",
    "octopBot.computer.permAccessibilityHint",
  ],
};

/** What macOS still has to allow, with a way to ask for each grant. */
function ComputerPermissions({ needs }: { needs: ComputerPermission[] }) {
  const { t } = useTranslation();
  const bridge = getDesktopBridge();
  const request = bridge?.requestComputerPermission;
  const relaunch = bridge?.relaunch;
  return (
    <section className={styles.permissions} aria-labelledby="bot-computer-perm">
      <ShieldAlert size={22} className={styles.warn} aria-hidden="true" />
      <strong id="bot-computer-perm">{t("octopBot.computer.permTitle")}</strong>
      <p>
        {t(
          request
            ? "octopBot.computer.permBody"
            : "octopBot.computer.permManual",
        )}
      </p>
      <ul>
        {needs.map((kind) => (
          <li key={kind}>
            <span>
              <b>{t(PERMISSION_TEXT[kind][0])}</b>
              <small>{t(PERMISSION_TEXT[kind][1])}</small>
            </span>
            {request && (
              <Button onClick={() => void request(kind)}>
                {t("octopBot.computer.permGrant")}
              </Button>
            )}
          </li>
        ))}
      </ul>
      {needs.includes("screen_recording") && (
        <p className={styles.relaunch}>
          {t("octopBot.computer.permRelaunchHint")}
          {relaunch && (
            <Button type="primary" onClick={() => relaunch()}>
              {t("octopBot.computer.permRelaunch")}
            </Button>
          )}
        </p>
      )}
    </section>
  );
}
