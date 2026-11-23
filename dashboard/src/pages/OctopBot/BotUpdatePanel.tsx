import { useEffect, useState } from "react";
import { Button, Switch } from "antd";
import { useTranslation } from "react-i18next";
import {
  getDesktopBridge,
  type DesktopBotUpdateStatus,
  type DesktopClientSettings,
} from "../../utils/desktopBridge";
import settings from "./BotClientSettings.module.less";
import styles from "./BotUpdatePanel.module.less";

/**
 * Settings → General → "About & updates" on the Octop Bot desktop client: the
 * installed version, what the background updater is doing, and its two
 * switches. Only the desktop Bot shell exposes `botUpdates`; elsewhere this
 * renders nothing.
 */
export default function BotUpdatePanel() {
  const { t } = useTranslation();
  const bridge = getDesktopBridge();
  const updates = bridge?.botUpdates;
  const [status, setStatus] = useState<DesktopBotUpdateStatus | null>(null);
  const [prefs, setPrefs] = useState<DesktopClientSettings | null>(null);
  const [checking, setChecking] = useState(false);

  useEffect(() => {
    if (!updates || !bridge) return;
    let alive = true;
    void updates.state().then((next) => alive && setStatus(next));
    void bridge.clientSettings.get().then((next) => alive && setPrefs(next));
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
    setPrefs(await bridge.clientSettings.set(patch));
  };

  const busy =
    checking || status.kind === "checking" || status.kind === "downloading";
  const offer = status.kind === "ready" || status.kind === "available";
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
  const tone = status.urgent
    ? "urgent"
    : status.kind === "error"
    ? "error"
    : status.version
    ? "new"
    : "quiet";

  return (
    <>
      <h3>{t("botClient.update.title")}</h3>
      <div className={settings.group}>
        <div className={settings.row}>
          <span>
            {t("botClient.update.current", { version: status.currentVersion })}
            <small className={styles.status} data-tone={tone} role="status">
              {line}
            </small>
          </span>
          {offer ? (
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
        {status.notes && offer && (
          <div className={settings.row}>
            <pre className={styles.notes}>{plainNotes(status.notes)}</pre>
          </div>
        )}
        {prefs && (
          <>
            <div className={settings.row}>
              <span>
                {t("botClient.update.autoDownload")}
                <small>{t("botClient.update.autoDownloadHint")}</small>
              </span>
              <Switch
                checked={prefs.autoDownloadUpdates !== false}
                aria-label={t("botClient.update.autoDownload")}
                onChange={(on) => void change({ autoDownloadUpdates: on })}
              />
            </div>
            <div className={settings.row}>
              <span>
                {t("botClient.update.beta")}
                <small>{t("botClient.update.betaHint")}</small>
              </span>
              <Switch
                checked={!prefs.stableOnly}
                aria-label={t("botClient.update.beta")}
                onChange={(on) => void change({ stableOnly: !on })}
              />
            </div>
          </>
        )}
      </div>
    </>
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
