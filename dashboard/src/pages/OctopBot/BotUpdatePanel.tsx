import { useEffect, useState } from "react";
import { Button, Switch } from "antd";
import { useTranslation } from "react-i18next";
import {
  getDesktopBridge,
  type DesktopBotUpdateStatus,
  type DesktopClientSettings,
} from "../../utils/desktopBridge";
import styles from "./BotUpdatePanel.module.less";

/**
 * "About & updates" on the Octop Bot desktop settings page: the installed
 * version, what the background updater is doing, and its two switches.
 * Only the desktop Bot shell exposes `botUpdates`; elsewhere this renders nothing.
 */
export default function BotUpdatePanel() {
  const { t } = useTranslation();
  const bridge = getDesktopBridge();
  const updates = bridge?.botUpdates;
  const [status, setStatus] = useState<DesktopBotUpdateStatus | null>(null);
  const [settings, setSettings] = useState<DesktopClientSettings | null>(null);
  const [checking, setChecking] = useState(false);

  useEffect(() => {
    if (!updates || !bridge) return;
    let alive = true;
    void updates.state().then((next) => alive && setStatus(next));
    void bridge.clientSettings.get().then((next) => alive && setSettings(next));
    const stop = updates.onChange((next) => setStatus(next));
    return () => {
      alive = false;
      stop();
    };
  }, [updates, bridge]);

  if (!updates || !bridge || !status) return null;

  const check = async () => {
    setChecking(true);
    try {
      setStatus(await updates.check());
    } finally {
      setChecking(false);
    }
  };

  const change = async (patch: Partial<DesktopClientSettings>) => {
    setSettings(await bridge.clientSettings.set(patch));
  };

  const busy =
    checking || status.kind === "checking" || status.kind === "downloading";
  const line = (() => {
    switch (status.kind) {
      case "ready":
        return t(
          status.urgent
            ? "botClient.update.readyUrgent"
            : "botClient.update.ready",
          { version: status.version },
        );
      case "available":
        return t(
          status.urgent
            ? "botClient.update.availableUrgent"
            : "botClient.update.available",
          { version: status.version },
        );
      case "downloading":
        return t("botClient.update.downloading", { version: status.version });
      case "checking":
        return t("botClient.update.checking");
      case "error":
        return t("botClient.update.failed");
      default:
        return t("botClient.update.upToDate");
    }
  })();

  return (
    <section className={styles.panel} aria-labelledby="bot-update-title">
      <h2 id="bot-update-title">{t("botClient.update.title")}</h2>
      <div className={styles.row}>
        <div>
          <div className={styles.version}>
            {t("botClient.update.current", { version: status.currentVersion })}
          </div>
          <div
            className={styles.status}
            data-tone={
              status.urgent
                ? "urgent"
                : status.kind === "error"
                ? "error"
                : status.version
                ? "new"
                : "quiet"
            }
            role="status"
          >
            {line}
          </div>
        </div>
        {status.kind === "ready" || status.kind === "available" ? (
          <Button type="primary" onClick={() => void updates.apply()}>
            {t(
              status.kind === "ready"
                ? "botClient.update.restart"
                : "botClient.update.download",
            )}
          </Button>
        ) : (
          <Button loading={busy} onClick={() => void check()}>
            {t("botClient.update.check")}
          </Button>
        )}
      </div>
      {status.notes &&
        (status.kind === "ready" || status.kind === "available") && (
          <pre className={styles.notes}>{plainNotes(status.notes)}</pre>
        )}
      {settings && (
        <>
          <label className={styles.toggle}>
            <span>
              {t("botClient.update.autoDownload")}
              <small>{t("botClient.update.autoDownloadHint")}</small>
            </span>
            <Switch
              checked={settings.autoDownloadUpdates !== false}
              onChange={(on) => void change({ autoDownloadUpdates: on })}
            />
          </label>
          <label className={styles.toggle}>
            <span>
              {t("botClient.update.beta")}
              <small>{t("botClient.update.betaHint")}</small>
            </span>
            <Switch
              checked={!settings.stableOnly}
              onChange={(on) => void change({ stableOnly: !on })}
            />
          </label>
        </>
      )}
    </section>
  );
}

/** Release notes come from CHANGELOG Markdown; show them as plain lines. */
export function plainNotes(notes: string): string {
  return notes
    .split("\n")
    .map((line) =>
      line
        .replace(/^#{1,6}\s+/, "")
        .replace(/\*\*(.+?)\*\*/g, "$1")
        .replace(/`([^`]+)`/g, "$1"),
    )
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}
