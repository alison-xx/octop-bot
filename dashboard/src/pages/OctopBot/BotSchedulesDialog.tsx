import { useEffect, useRef, useState } from "react";
import {
  Alert,
  Button,
  Empty,
  Input,
  Modal,
  Popconfirm,
  Select,
  Spin,
} from "antd";
import { Plus, RefreshCw, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { octopCronApi } from "../../api/modules/cronjob";
import type { OctopCronRow } from "../../api/types";
import { apiErrorMessage } from "../../utils/apiError";
import {
  CRON_NAME_MAX_LEN,
  CRON_PROMPT_MAX_LEN,
} from "../Control/CronJobs/constants";
import {
  formatCronTimestamp,
  LATEST_SESSION_TARGET,
  THREAD_TARGET_PREFIX,
} from "../Control/CronJobs/cronDisplay";
import {
  defaultOnceRunAt,
  formatTriggerText,
  isFutureWallClock,
  isOnceTrigger,
  lastRunStatusTag,
  onceRunAtFromTrigger,
  oneShotPhase,
  oneShotPhaseLabelKey,
} from "../Control/CronJobs/onceSchedule";
import styles from "./BotActivity.module.less";

type Frequency = "daily" | "weekdays" | "weekly" | "once";
const weekdays = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;
type Weekday = (typeof weekdays)[number];

function weekdayLabel(day: Weekday, locale: string) {
  return new Intl.DateTimeFormat(locale, {
    weekday: "long",
    timeZone: "UTC",
  }).format(Date.UTC(2024, 0, 1 + weekdays.indexOf(day)));
}

function scheduleLabel(trigger: string, locale: string, t: TFunction) {
  const parts =
    /^cron:(\d{1,2}) (\d{1,2}) \* \* (\*|mon-fri|mon|tue|wed|thu|fri|sat|sun)$/.exec(
      trigger,
    );
  if (!parts)
    return formatTriggerText(trigger, {
      once: t("botClient.activity.once"),
      mail: t("botClient.activity.mail"),
    });
  const day = parts[3];
  const frequency =
    day === "*"
      ? t("botClient.activity.daily")
      : day === "mon-fri"
      ? t("botClient.activity.weekdays")
      : weekdayLabel(day as Weekday, locale);
  return (
    frequency +
    " · " +
    parts[2].padStart(2, "0") +
    ":" +
    parts[1].padStart(2, "0")
  );
}

function ScheduleForm({
  agentId,
  threadId,
  timezone,
  local,
  onCancel,
  onCreated,
}: {
  agentId: string;
  threadId?: string;
  timezone: string;
  local: boolean;
  onCancel: () => void;
  onCreated: (job: OctopCronRow) => void;
}) {
  const { t, i18n } = useTranslation();
  const [name, setName] = useState("");
  const [prompt, setPrompt] = useState("");
  const [frequency, setFrequency] = useState<Frequency>("daily");
  const [day, setDay] = useState<Weekday>("mon");
  const [time, setTime] = useState("09:00");
  const [once, setOnce] = useState(() =>
    defaultOnceRunAt(timezone).slice(0, 16),
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submitting = useRef(false);
  async function submit() {
    if (submitting.current || !prompt.trim()) return;
    setError("");
    if (
      frequency === "once" &&
      (!once || !isFutureWallClock(once + ":00", timezone))
    ) {
      setError(t("botClient.activity.future"));
      return;
    }
    if (frequency !== "once" && !/^([01]\d|2[0-3]):[0-5]\d$/.test(time)) {
      setError(t("botClient.activity.timeRequired"));
      return;
    }
    const [hour, minute] = time.split(":").map(Number);
    const dayPart =
      frequency === "weekdays" ? "mon-fri" : frequency === "weekly" ? day : "*";
    const trigger =
      frequency === "once"
        ? "date:" + once + ":00"
        : `cron:${minute} ${hour} * * ${dayPart}`;
    submitting.current = true;
    setBusy(true);
    try {
      const row = await octopCronApi.create(agentId, {
        name: name.trim() || undefined,
        prompt: prompt.trim(),
        trigger,
        task_type: "agent",
        allow_all: false,
        enabled: true,
        session_key: threadId
          ? THREAD_TARGET_PREFIX + threadId
          : LATEST_SESSION_TARGET,
      });
      onCreated(row);
    } catch (err) {
      setError(apiErrorMessage(err, t("cronJobs.operationFailed"), t));
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  }
  return (
    <form
      className={styles.form}
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      <label>
        {t("botClient.activity.taskName")}
        <Input
          autoFocus
          value={name}
          onChange={(e) => setName(e.target.value)}
          maxLength={CRON_NAME_MAX_LEN}
        />
      </label>
      <label>
        {t("botClient.activity.instructions")}
        <Input.TextArea
          required
          autoSize={{ minRows: 3, maxRows: 6 }}
          maxLength={CRON_PROMPT_MAX_LEN}
          value={prompt}
          placeholder={t("botClient.activity.example")}
          onChange={(e) => setPrompt(e.target.value)}
        />
      </label>
      <div className={styles.fields}>
        <label>
          {t("botClient.activity.frequency")}
          <Select
            aria-label={t("botClient.activity.frequency")}
            value={frequency}
            onChange={setFrequency}
            options={["daily", "weekdays", "weekly", "once"].map((value) => ({
              value,
              label: t("botClient.activity." + value),
            }))}
          />
        </label>
        {frequency === "weekly" && (
          <label>
            {t("botClient.activity.weekday")}
            <Select
              aria-label={t("botClient.activity.weekday")}
              value={day}
              onChange={setDay}
              options={weekdays.map((value) => ({
                value,
                label: weekdayLabel(value, i18n.language),
              }))}
            />
          </label>
        )}
        <label>
          {t("botClient.activity.time", { timezone })}
          {frequency === "once" ? (
            <Input
              type="datetime-local"
              required
              value={once}
              onChange={(e) => setOnce(e.target.value)}
            />
          ) : (
            <Input
              type="time"
              required
              value={time}
              onChange={(e) => setTime(e.target.value)}
            />
          )}
        </label>
      </div>
      <p className={styles.hint}>
        {t(
          threadId
            ? "botClient.activity.deliverHere"
            : local
            ? "botClient.activity.deliverLatest"
            : "botClient.activity.deliverLatestServer",
        )}
      </p>
      {error && <Alert type="error" showIcon message={error} />}
      <div className={styles.actions}>
        <Button disabled={busy} onClick={onCancel}>
          {t("common.cancel")}
        </Button>
        <Button
          type="primary"
          htmlType="submit"
          loading={busy}
          disabled={!prompt.trim()}
        >
          {t("cronJobs.createJob")}
        </Button>
      </div>
    </form>
  );
}

export default function BotSchedulesDialog({
  agentId,
  name,
  threadId,
  edition,
  onClose,
}: {
  agentId: string;
  name: string;
  threadId?: string;
  /** Where the server runs: only "desktop" runs tasks on this computer. */
  edition?: "desktop" | "web" | "cloud" | "server";
  onClose: () => void;
}) {
  const { t, i18n } = useTranslation();
  const [data, setData] = useState<{
    jobs: OctopCronRow[];
    timezone: string;
  } | null>(null);
  const [revision, setRevision] = useState(0);
  const [editing, setEditing] = useState(false);
  const [changing, setChanging] = useState<string | null>(null);
  const [loadError, setLoadError] = useState("");
  const [changeError, setChangeError] = useState("");
  useEffect(() => {
    let current = true;
    setData(null);
    setLoadError("");
    setChangeError("");
    Promise.all([octopCronApi.list(agentId), octopCronApi.settings()])
      .then(([jobs, settings]) => {
        if (current) setData({ jobs, timezone: settings.timezone });
      })
      .catch((err) => {
        if (current)
          setLoadError(apiErrorMessage(err, t("cronJobs.loadFailed"), t));
      });
    return () => {
      current = false;
    };
  }, [agentId, revision, t]);
  const toggle = async (job: OctopCronRow) => {
    if (changing) return;
    setChanging(job.id);
    setChangeError("");
    try {
      const updated = await octopCronApi.patch(agentId, job.id, {
        enabled: !job.enabled,
      });
      setData(
        (current) =>
          current && {
            ...current,
            jobs: current.jobs.map((row) =>
              row.id === updated.id ? updated : row,
            ),
          },
      );
    } catch (err) {
      setChangeError(apiErrorMessage(err, t("cronJobs.operationFailed"), t));
    } finally {
      setChanging(null);
    }
  };
  const remove = async (job: OctopCronRow) => {
    if (changing) return;
    setChanging(job.id);
    setChangeError("");
    try {
      await octopCronApi.delete(agentId, job.id);
      setData(
        (current) =>
          current && {
            ...current,
            jobs: current.jobs.filter((row) => row.id !== job.id),
          },
      );
    } catch (err) {
      setChangeError(apiErrorMessage(err, t("cronJobs.operationFailed"), t));
    } finally {
      setChanging(null);
    }
  };
  // Until the server says otherwise, keep the local wording for where results go.
  const local = !edition || edition === "desktop";
  const where = !edition
    ? null
    : edition === "desktop"
    ? "botClient.activity.localExecution"
    : edition === "cloud"
    ? "botClient.activity.cloudExecution"
    : "botClient.activity.serverExecution";
  return (
    <Modal
      open
      centered
      title={
        editing
          ? t("cronJobs.createJob")
          : t("botClient.activity.scheduleTitle", { name })
      }
      onCancel={onClose}
      footer={null}
      width={520}
    >
      <div className={styles.body}>
        {where && <p className={styles.hint}>{t(where)}</p>}
        {loadError ? (
          <Alert
            type="error"
            showIcon
            message={loadError}
            action={
              <Button onClick={() => setRevision((n) => n + 1)}>
                {t("common.retry")}
              </Button>
            }
          />
        ) : !data ? (
          <Spin />
        ) : editing ? (
          <ScheduleForm
            agentId={agentId}
            threadId={threadId}
            timezone={data.timezone}
            local={local}
            onCancel={() => setEditing(false)}
            onCreated={(row) => {
              setData(
                (current) =>
                  current && { ...current, jobs: [row, ...current.jobs] },
              );
              setEditing(false);
            }}
          />
        ) : (
          <>
            <div className={styles.toolbar}>
              <span className={styles.hint}>
                {t("cronJobs.scheduleTimezone")} · {data.timezone}
              </span>
              <div className={styles.actions}>
                <Button
                  aria-label={t("common.refresh")}
                  title={t("common.refresh")}
                  icon={<RefreshCw size={14} />}
                  disabled={changing !== null}
                  onClick={() => setRevision((n) => n + 1)}
                />
                <Button
                  type="primary"
                  icon={<Plus size={15} />}
                  onClick={() => {
                    setEditing(true);
                    setChangeError("");
                  }}
                >
                  {t("cronJobs.createJob")}
                </Button>
              </div>
            </div>
            {changeError && (
              <Alert type="error" showIcon message={changeError} />
            )}
            {data.jobs.length === 0 ? (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={t("botClient.activity.noSchedules")}
              />
            ) : (
              <ul className={styles.rows}>
                {data.jobs.map((job) => {
                  const phase = oneShotPhase(
                    job.trigger,
                    job.enabled,
                    job.last_status,
                  );
                  const status = job.last_status
                    ? lastRunStatusTag(job.last_status)
                    : null;
                  const pastOnce =
                    !job.enabled &&
                    isOnceTrigger(job.trigger) &&
                    !isFutureWallClock(
                      onceRunAtFromTrigger(job.trigger),
                      data.timezone,
                    );
                  const action = t(
                    job.enabled
                      ? "botClient.activity.pause"
                      : "botClient.activity.resume",
                  );
                  return (
                    <li key={job.id}>
                      <div className={styles.job}>
                        <strong>{job.name}</strong>
                        <span>
                          {scheduleLabel(job.trigger, i18n.language, t)} ·{" "}
                          {t(
                            phase
                              ? oneShotPhaseLabelKey(phase)
                              : job.enabled
                              ? "common.enabled"
                              : "cronJobs.oneShotPaused",
                          )}
                        </span>
                        {job.task_type !== "script" &&
                          job.prompt !== job.name && (
                            <small>{job.prompt}</small>
                          )}
                        {job.last_run_at && (
                          <small>
                            {t("botClient.activity.lastRun")} ·{" "}
                            {formatCronTimestamp(
                              job.last_run_at,
                              data.timezone,
                            )}
                            {status && " · " + t(status.labelKey)}
                          </small>
                        )}
                        {(job.last_status === "error" ||
                          job.last_status === "waiting" ||
                          job.last_status === "expired") &&
                          job.last_error && <small>{job.last_error}</small>}
                      </div>
                      {!pastOnce && job.task_type !== "script" && (
                        <Button
                          size="small"
                          loading={changing === job.id}
                          disabled={changing !== null && changing !== job.id}
                          aria-busy={changing === job.id}
                          onClick={() => void toggle(job)}
                          aria-label={action + " " + job.name}
                        >
                          {action}
                        </Button>
                      )}
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
                          loading={changing === job.id}
                          disabled={changing !== null && changing !== job.id}
                          aria-label={t("common.delete") + " " + job.name}
                          title={t("common.delete")}
                        />
                      </Popconfirm>
                    </li>
                  );
                })}
              </ul>
            )}
          </>
        )}
      </div>
    </Modal>
  );
}
