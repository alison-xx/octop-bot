import { useEffect, useState } from "react";
import { Button, Popconfirm, Segmented, Spin, Switch } from "antd";
import {
  Clock,
  File,
  FileArchive,
  FileAudio,
  FileCode,
  FileImage,
  FileSpreadsheet,
  FileText,
  FileVideo,
  Presentation,
  Trash2,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  botProfileApi,
  type LibraryFile,
  type UpcomingJob,
} from "../../api/modules/botProfile";
import { octopCronApi } from "../../api/modules/cronjob";
import { apiErrorMessage } from "../../utils/apiError";
import { saveBlobAsFile } from "../../utils/saveBlobAsFile";
import styles from "./BotActivityLibrary.module.less";

const FIRST = 5;
const PERIODS = ["today", "week", "older"] as const;

const KINDS: [RegExp, LucideIcon][] = [
  [/^image\//, FileImage],
  [/^video\//, FileVideo],
  [/^audio\//, FileAudio],
  [/\.(xlsx?|csv|numbers)$/i, FileSpreadsheet],
  [/\.(pptx?|key)$/i, Presentation],
  [/\.(zip|tar|gz|tgz|7z|rar)$/i, FileArchive],
  [/\.(py|js|ts|tsx|json|html|css|sh|sql|ya?ml)$/i, FileCode],
  [/^text\/|\.(pdf|docx?|md|txt|rtf|pages)$/i, FileText],
];

export function fileIcon(file: Pick<LibraryFile, "name" | "mime">) {
  const hit = KINDS.find(
    ([pattern]) => pattern.test(file.mime ?? "") || pattern.test(file.name),
  );
  return hit ? hit[1] : File;
}

function Upcoming({
  agentId,
  canToggle,
}: {
  agentId: string;
  canToggle: boolean;
}) {
  const { t } = useTranslation();
  const [jobs, setJobs] = useState<UpcomingJob[] | null>(null);
  const [error, setError] = useState("");
  const [all, setAll] = useState(false);
  const [changing, setChanging] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let live = true;
    setError("");
    botProfileApi
      .upcoming(agentId)
      .then((body) => {
        if (live) setJobs(body.jobs);
      })
      .catch((e) => {
        if (live) setError(apiErrorMessage(e, t("cronJobs.loadFailed"), t));
      });
    return () => {
      live = false;
    };
  }, [agentId, revision, t]);
  const toggle = async (job: UpcomingJob, enabled: boolean) => {
    setChanging(job.id);
    setError("");
    setJobs(
      (rows) =>
        rows?.map((row) => (row.id === job.id ? { ...row, enabled } : row)) ??
        rows,
    );
    try {
      await octopCronApi.patch(agentId, job.id, { enabled });
    } catch (e) {
      setError(apiErrorMessage(e, t("cronJobs.operationFailed"), t));
    } finally {
      setChanging(null);
      setRevision((n) => n + 1);
    }
  };
  const remove = async (job: UpcomingJob) => {
    setChanging(job.id);
    setError("");
    try {
      await octopCronApi.delete(agentId, job.id);
      setJobs((rows) => rows?.filter((row) => row.id !== job.id) ?? rows);
    } catch (e) {
      setError(apiErrorMessage(e, t("cronJobs.operationFailed"), t));
    } finally {
      setChanging(null);
    }
  };
  if (!jobs && !error) return <Spin size="small" className={styles.spin} />;
  const shown = all ? jobs ?? [] : (jobs ?? []).slice(0, FIRST);
  return (
    <>
      <h5 className={styles.heading}>{t("botProfile.upcoming")}</h5>
      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
      {jobs?.length === 0 ? (
        <p className={styles.empty}>{t("botProfile.noUpcoming")}</p>
      ) : (
        jobs && (
          <ul className={styles.card}>
            {shown.map((job) => (
              <li key={job.id} className={styles.job}>
                <Clock size={16} className={styles.glyph} />
                <span className={styles.text}>
                  <strong>{job.name}</strong>
                  <small>{job.schedule}</small>
                </span>
                <Switch
                  size="small"
                  checked={job.enabled}
                  loading={changing === job.id}
                  disabled={
                    !canToggle ||
                    !job.can_toggle ||
                    (changing !== null && changing !== job.id)
                  }
                  aria-label={t("botProfile.toggle", { name: job.name })}
                  onChange={(on) => void toggle(job, on)}
                />
                {canToggle && (
                  <Popconfirm
                    title={t("cronJobs.deleteConfirm")}
                    okText={t("common.delete")}
                    cancelText={t("common.cancel")}
                    okButtonProps={{ danger: true }}
                    onConfirm={() => remove(job)}
                  >
                    <Button
                      size="small"
                      type="text"
                      danger
                      icon={<Trash2 size={14} />}
                      disabled={changing !== null}
                      aria-label={t("botProfile.delete", { name: job.name })}
                      title={t("common.delete")}
                    />
                  </Popconfirm>
                )}
              </li>
            ))}
            {!all && jobs.length > FIRST && (
              <li>
                <button
                  type="button"
                  className={styles.more}
                  onClick={() => setAll(true)}
                >
                  {t("botProfile.showMore")}
                </button>
              </li>
            )}
          </ul>
        )
      )}
    </>
  );
}

function Library({ agentId }: { agentId: string }) {
  const { t } = useTranslation();
  const [files, setFiles] = useState<LibraryFile[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    botProfileApi
      .library(agentId)
      .then((body) => {
        if (live) setFiles(body.files);
      })
      .catch((e) => {
        if (live) setError(apiErrorMessage(e, t("octopBot.failed"), t));
      });
    return () => {
      live = false;
    };
  }, [agentId, t]);
  const open = async (file: LibraryFile) => {
    setError("");
    try {
      await saveBlobAsFile(
        await botProfileApi.download(agentId, file.path),
        file.name,
      );
    } catch (e) {
      setError(apiErrorMessage(e, t("octopBot.failed"), t));
    }
  };
  if (!files && !error) return <Spin size="small" className={styles.spin} />;
  return (
    <>
      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
      {files?.length === 0 && (
        <p className={styles.empty}>{t("botProfile.noFiles")}</p>
      )}
      {PERIODS.map((period) => {
        const group = files?.filter((file) => file.period === period) ?? [];
        if (!group.length) return null;
        return (
          <section key={period} aria-label={t("botProfile." + period)}>
            <h5 className={styles.heading}>{t("botProfile." + period)}</h5>
            <ul className={styles.files}>
              {group.map((file) => {
                const Icon = fileIcon(file);
                return (
                  <li key={file.path}>
                    <button
                      type="button"
                      className={styles.file}
                      title={file.path}
                      aria-label={t("botProfile.download", { name: file.name })}
                      onClick={() => void open(file)}
                    >
                      <Icon size={16} className={styles.glyph} />
                      <span>{file.name}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </section>
        );
      })}
    </>
  );
}

/** Grok-style Bot profile body: upcoming scheduled tasks and the files it made. */
export default function BotActivityLibrary({
  agentId,
  canToggle,
}: {
  agentId: string;
  canToggle: boolean;
}) {
  const { t } = useTranslation();
  const [tab, setTab] = useState<"activity" | "library">("activity");
  return (
    <div className={styles.root}>
      <Segmented
        block
        value={tab}
        onChange={(value) => setTab(value as "activity" | "library")}
        options={[
          { value: "activity", label: t("botProfile.activity") },
          { value: "library", label: t("botProfile.library") },
        ]}
      />
      {tab === "activity" ? (
        <Upcoming key={agentId} agentId={agentId} canToggle={canToggle} />
      ) : (
        <Library key={agentId} agentId={agentId} />
      )}
    </div>
  );
}
