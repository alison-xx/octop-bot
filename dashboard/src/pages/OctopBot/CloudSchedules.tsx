import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Button, Empty, Input, Modal, Select, Spin } from "antd";
import dayjs from "dayjs";
import utc from "dayjs/plugin/utc";
import timezonePlugin from "dayjs/plugin/timezone";
import { CalendarClock, Plus, RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  botCloudApi,
  type CloudRule,
  type CloudSchedule,
} from "../../api/modules/botCloud";
import type { WorkspaceBot } from "../../api/modules/octopBot";
import { octopCronApi } from "../../api/modules/cronjob";
import { useServerTimezone } from "../../hooks/useServerTimezone";
import { formatServerIsoDateTime } from "../../utils/formatMessageTime";
import { apiErrorMessage } from "../../utils/apiError";
import { defaultOnceRunAt } from "../Control/CronJobs/onceSchedule";
import {
  cloudDraftFromTimer,
  type CloudScheduleDraft,
} from "./cloudScheduleDraft";
import styles from "./cloud.module.less";
dayjs.extend(utc);
dayjs.extend(timezonePlugin);

export default function CloudSchedules({
  accountId,
  bots,
  botId,
  onBot,
  seedId,
  clearSeed,
  onOpen,
}: {
  accountId: string;
  bots: WorkspaceBot[];
  botId?: string;
  onBot: (id?: string) => void;
  seedId?: string;
  clearSeed: () => void;
  onOpen: (id: string) => void;
}) {
  const { t, i18n } = useTranslation();
  const timezone = useServerTimezone();
  const [rows, setRows] = useState<CloudSchedule[] | null>(null);
  const [error, setError] = useState("");
  const [draft, setDraft] = useState<CloudScheduleDraft | null>(null);
  const [monthDay, setMonthDay] = useState(1);
  const [pending, setPending] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [createError, setCreateError] = useState("");
  const [checkList, setCheckList] = useState(false);
  const guard = useRef(false);
  const seq = useRef(0);
  const load = useCallback(async () => {
    const v = ++seq.current;
    try {
      const result = await botCloudApi.schedules(accountId);
      if (v === seq.current) {
        setRows(result.items);
        setLoadError("");
      }
    } catch (e) {
      if (v === seq.current)
        setLoadError(apiErrorMessage(e, t("octopBot.failed"), t));
    }
  }, [accountId, t]);
  useEffect(() => {
    void load();
    window.addEventListener("focus", load);
    return () => {
      window.removeEventListener("focus", load);
    };
  }, [load]);
  useEffect(() => {
    if (!seedId || !botId) return;
    let alive = true;
    octopCronApi
      .get(botId, seedId)
      .then((job) => {
        if (!alive) return;
        const source = cloudDraftFromTimer(job);
        if (source) setDraft(source);
        else setError(t("botCloud.pauseFirst"));
      })
      .catch((e) => {
        if (alive) setError(apiErrorMessage(e, t("octopBot.failed"), t));
      });
    return () => {
      alive = false;
    };
  }, [botId, seedId, t]);
  const start = () => {
    clearSeed();
    setError("");
    setCreateError("");
    setCheckList(false);
    setMonthDay(1);
    setDraft({
      name: "",
      instruction: "",
      frequency: "daily",
      time: "09:00",
      weekday: 1,
      once: defaultOnceRunAt(timezone).slice(0, 16),
    });
  };
  const close = () => {
    if (!guard.current) {
      setDraft(null);
      clearSeed();
      setCreateError("");
      setCheckList(false);
    }
  };
  const update = (patch: Partial<CloudScheduleDraft>) =>
    setDraft((old) => old && { ...old, ...patch });
  const date = (value: string) => formatServerIsoDateTime(value, timezone);
  async function create() {
    if (
      !draft ||
      guard.current ||
      checkList ||
      !draft.name.trim() ||
      !draft.instruction.trim()
    )
      return;
    const [hour, minute] = (
      draft.frequency === "once" ? draft.once.slice(11, 16) : draft.time
    )
      .split(":")
      .map(Number);
    const rule: CloudRule = {
      frequency: draft.frequency,
      hour,
      minute,
      timezone,
    };
    if (draft.frequency === "weekly") rule.weekdays = [draft.weekday];
    if (draft.frequency === "monthly") rule.month_day = monthDay;
    if (draft.frequency === "once") {
      const instant = draft.once ? dayjs.tz(draft.once, timezone) : null;
      if (
        !instant ||
        !instant.isValid() ||
        instant.format("YYYY-MM-DDTHH:mm") !== draft.once ||
        instant.valueOf() <= Date.now()
      ) {
        setCreateError(t("botClient.activity.future"));
        return;
      }
      rule.once_at = instant.toISOString();
    }
    guard.current = true;
    setPending(true);
    setCreateError("");
    let submitted = false;
    try {
      if (
        seedId &&
        botId &&
        !cloudDraftFromTimer(await octopCronApi.get(botId, seedId))
      ) {
        setCreateError(t("botCloud.pauseFirst"));
        return;
      }
      submitted = true;
      const row = await botCloudApi.createSchedule({
        account_id: accountId,
        name: draft.name.trim(),
        instruction: draft.instruction.trim(),
        bot_id: botId,
        rule,
      });
      ++seq.current;
      setRows((prev) => [row, ...(prev || []).filter((r) => r.id !== row.id)]);
      setDraft(null);
      clearSeed();
      setError("");
      setLoadError("");
    } catch (e) {
      setCreateError(apiErrorMessage(e, t("octopBot.failed"), t));
      if (
        submitted &&
        !(e instanceof Error && /Request failed: 4\d\d\b/.test(e.message))
      ) {
        setCheckList(true);
        void load();
      }
    } finally {
      guard.current = false;
      setPending(false);
    }
  }
  async function toggle(row: CloudSchedule) {
    if (guard.current) return;
    guard.current = true;
    setPending(true);
    setError("");
    try {
      const updated = await botCloudApi.toggleSchedule(
        accountId,
        row.id,
        !row.enabled,
      );
      ++seq.current;
      setRows(
        (prev) => prev?.map((r) => (r.id === row.id ? updated : r)) ?? null,
      );
    } catch (e) {
      setError(apiErrorMessage(e, t("octopBot.failed"), t));
      void load();
    } finally {
      guard.current = false;
      setPending(false);
    }
  }
  return (
    <section className={styles.scheduleArea}>
      <div className={styles.bar}>
        <h2>
          <CalendarClock size={18} />
          {t("botCloud.schedules")}
        </h2>
        <Button
          icon={<RefreshCw size={14} />}
          aria-label={t("common.refresh")}
          onClick={() => void load()}
        />
        <Button icon={<Plus size={15} />} type="primary" onClick={start}>
          {t("botCloud.newSchedule")}
        </Button>
      </div>
      <p className={styles.hint}>{t("botCloud.scheduleHint")}</p>
      {(error || loadError) && (
        <Alert type="error" showIcon message={error || loadError} />
      )}
      {!rows ? (
        !loadError && <Spin />
      ) : !rows.length ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={t("botCloud.noSchedules")}
        />
      ) : (
        <ul className={styles.jobs}>
          {rows.map((row) => (
            <li key={row.id}>
              <div>
                <h3>{row.name}</h3>
                <small>
                  {[
                    row.bot_name,
                    row.rule_text,
                    row.finished_once
                      ? t("botCloud.onceEnded")
                      : row.enabled
                      ? t("common.enabled")
                      : t("botCloud.paused"),
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </small>
                {row.next_run_at && row.enabled && (
                  <p>{t("botCloud.next", { time: date(row.next_run_at) })}</p>
                )}
                {row.last_run_at && (
                  <p>
                    {t("botCloud.lastRun", { time: date(row.last_run_at) })}
                  </p>
                )}
                {row.last_result_preview && <p>{row.last_result_preview}</p>}
                {row.last_error && (
                  <Alert type="warning" message={row.last_error} />
                )}
              </div>
              <div className={styles.actions}>
                {!!row.run_count && row.session_id && (
                  <Button size="small" onClick={() => onOpen(row.session_id)}>
                    {t("botCloud.openResult")}
                  </Button>
                )}
                {!row.finished_once && (
                  <Button
                    size="small"
                    disabled={pending}
                    onClick={() => void toggle(row)}
                  >
                    {t(
                      row.enabled
                        ? "botClient.activity.pause"
                        : "botClient.activity.resume",
                    )}
                  </Button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
      {draft && (
        <Modal
          open
          centered
          width={500}
          title={t("botCloud.newSchedule")}
          onCancel={close}
          footer={null}
          maskClosable={!pending}
        >
          <form
            className={styles.form}
            onSubmit={(e) => {
              e.preventDefault();
              void create();
            }}
          >
            <label>
              {t("botCloud.scheduleName")}
              <Input
                required
                maxLength={45}
                value={draft.name}
                onChange={(e) => update({ name: e.target.value })}
              />
            </label>
            <label>
              {t("botCloud.bot")}
              <Select
                value={botId || ""}
                disabled={Boolean(seedId)}
                onChange={(v) => onBot(v || undefined)}
                options={[
                  { value: "", label: t("botCloud.defaultBot") },
                  ...bots.map((b) => ({ value: b.agent_id, label: b.name })),
                ]}
              />
            </label>
            <label>
              {t("botClient.activity.instructions")}
              <Input.TextArea
                required
                maxLength={4000}
                autoSize={{ minRows: 3, maxRows: 6 }}
                value={draft.instruction}
                onChange={(e) => update({ instruction: e.target.value })}
              />
            </label>
            <div className={styles.fields}>
              <label>
                {t("botClient.activity.frequency")}
                <Select
                  value={draft.frequency}
                  onChange={(frequency) => update({ frequency })}
                  options={[
                    "daily",
                    "weekdays",
                    "weekly",
                    "monthly",
                    "once",
                  ].map((v) => ({
                    value: v,
                    label: t(
                      v === "monthly"
                        ? "botCloud.monthly"
                        : "botClient.activity." + v,
                    ),
                  }))}
                />
              </label>
              <label>
                {t("botClient.activity.time", { timezone })}
                {draft.frequency === "once" ? (
                  <Input
                    type="datetime-local"
                    required
                    value={draft.once}
                    onChange={(e) => update({ once: e.target.value })}
                  />
                ) : (
                  <Input
                    type="time"
                    required
                    value={draft.time}
                    onChange={(e) => update({ time: e.target.value })}
                  />
                )}
              </label>
            </div>
            {draft.frequency === "weekly" && (
              <label>
                {t("botClient.activity.weekday")}
                <Select
                  value={draft.weekday}
                  onChange={(weekday) => update({ weekday })}
                  options={Array.from({ length: 7 }, (_, i) => ({
                    value: i + 1,
                    label: new Intl.DateTimeFormat(i18n.language, {
                      weekday: "long",
                      timeZone: "UTC",
                    }).format(Date.UTC(2024, 0, 1 + i)),
                  }))}
                />
              </label>
            )}
            {draft.frequency === "monthly" && (
              <label>
                {t("botCloud.monthDay")}
                <Input
                  type="number"
                  required
                  min={1}
                  max={31}
                  value={monthDay}
                  onChange={(e) => setMonthDay(Number(e.target.value))}
                />
              </label>
            )}
            <p className={styles.hint}>{t("botCloud.scheduleHint")}</p>
            {createError && (
              <Alert
                type="error"
                message={createError}
                description={checkList ? t("botCloud.verifyCreate") : undefined}
              />
            )}
            <div className={styles.actions}>
              <Button onClick={close} disabled={pending}>
                {t(checkList ? "botCloud.backToSchedules" : "common.cancel")}
              </Button>
              <Button
                htmlType="submit"
                type="primary"
                loading={pending}
                disabled={
                  checkList || !draft.name.trim() || !draft.instruction.trim()
                }
              >
                {t("botCloud.createCloud")}
              </Button>
            </div>
          </form>
        </Modal>
      )}
    </section>
  );
}
