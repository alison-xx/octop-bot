import { useEffect, useState } from "react";
import { Alert, Button, Popconfirm } from "antd";
import { Import } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import {
  octopImportApi,
  type OctopImportPreview,
  type OctopImportReport,
} from "../../api/modules/octopImport";
import { apiErrorMessage } from "../../utils/apiError";
import { getDesktopBridge, isBotWebClient } from "../../utils/desktopBridge";
import settings from "./BotClientSettings.module.less";

function summary(report: OctopImportReport, t: TFunction) {
  const imported = report.agents.filter((a) => a.status === "imported");
  const skipped = report.agents.filter((a) => a.status === "skipped");
  const failed = report.agents.filter((a) => a.status === "failed");
  const channels = imported.reduce((n, a) => n + a.channels, 0);
  const cron = imported.reduce((n, a) => n + a.cron_jobs, 0);
  return [
    t("botClient.octopImport.done", {
      agents: imported.length,
      threads: imported.reduce((n, a) => n + a.threads, 0),
    }),
    report.providers.length > 0 &&
      t("botClient.octopImport.providers", {
        names: report.providers.join(", "),
      }),
    (channels > 0 || cron > 0) &&
      t("botClient.octopImport.paused", { channels, cron }),
    skipped.length > 0 &&
      t("botClient.octopImport.skipped", { count: skipped.length }),
    failed.length > 0 &&
      t("botClient.octopImport.failed", {
        names: failed.map((a) => a.name).join(", "),
      }),
  ].filter((line): line is string => Boolean(line));
}

/** Settings → General: one-click import from an Octop install on this computer. */
export default function OctopImport() {
  const { t } = useTranslation();
  const desktop = !!getDesktopBridge() && !isBotWebClient();
  const [found, setFound] = useState<OctopImportPreview | null>(null);
  const [working, setWorking] = useState(false);
  const [lines, setLines] = useState<string[]>([]);
  const [failed, setFailed] = useState(false);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    if (!desktop) return;
    let live = true;
    octopImportApi
      .preview()
      .then((result) => {
        if (live) setFound(result);
      })
      // Not the desktop app's own server, or Octop unreadable: nothing to offer.
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [desktop, revision]);

  if (!found?.available) return null;
  const pending = found.agents.filter((a) => !a.exists);
  const threads = pending.reduce((n, a) => n + a.threads, 0);

  const run = async () => {
    setWorking(true);
    setError("");
    try {
      const report = await octopImportApi.run();
      setLines(summary(report, t));
      setFailed(report.agents.some((a) => a.status === "failed"));
      setRevision((n) => n + 1);
    } catch (e) {
      setError(apiErrorMessage(e, t("octopBot.failed"), t));
    } finally {
      setWorking(false);
    }
  };
  return (
    <>
      <h3>{t("botClient.octopImport.title")}</h3>
      <div className={settings.group}>
        <div className={settings.row}>
          <span>
            {pending.length > 0 || found.providers.length > 0
              ? t("botClient.octopImport.found", {
                  agents: pending.length,
                  threads,
                })
              : t("botClient.octopImport.nothingNew")}
            <small>{found.home}</small>
          </span>
          <Popconfirm
            title={t("botClient.octopImport.confirmTitle")}
            description={
              <div className={settings.confirm}>
                {t("botClient.octopImport.confirmBody")}
              </div>
            }
            okText={t("botClient.octopImport.action")}
            onConfirm={run}
            disabled={pending.length === 0 && found.providers.length === 0}
          >
            <Button
              icon={<Import size={15} />}
              loading={working}
              disabled={pending.length === 0 && found.providers.length === 0}
            >
              {t("botClient.octopImport.action")}
            </Button>
          </Popconfirm>
        </div>
      </div>
      {error && <Alert type="error" showIcon message={error} />}
      {lines.length > 0 && (
        <Alert
          type={failed ? "warning" : "success"}
          showIcon
          message={lines[0]}
          description={
            lines.length > 1 ? (
              <>
                {lines.slice(1).map((line) => (
                  <div key={line}>{line}</div>
                ))}
              </>
            ) : undefined
          }
        />
      )}
    </>
  );
}
