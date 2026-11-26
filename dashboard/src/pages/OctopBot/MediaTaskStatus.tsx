import { Film, Images } from "lucide-react";
import { useTranslation } from "react-i18next";
import { parseActionArgs } from "../../api/types/hitl";
import { useElapsedSince } from "../../hooks/useElapsedSeconds";
import type { ChatMessage } from "../Chat/hooks/useChat";
import type { TFunction } from "i18next";
import styles from "./botConversation.module.less";

export function isMediaTool(name?: string) {
  return name === "generate_image" || name === "generate_video";
}

function elapsedLabel(ms: number, t: TFunction): string {
  const seconds = Math.max(0, ms / 1000);
  if (seconds < 1 && seconds > 0) return t("mediaTask.underSecond");
  const whole = Math.floor(seconds);
  return whole < 60
    ? t("mediaTask.seconds", { n: whole })
    : t("mediaTask.minutes", { m: Math.floor(whole / 60), s: whole % 60 });
}

function LiveElapsed({ start }: { start: number }) {
  const seconds = useElapsedSince(start);
  const { t } = useTranslation();
  return (
    <time>
      {t("mediaTask.elapsed", { time: elapsedLabel(seconds * 1000, t) })}
    </time>
  );
}

export default function MediaTaskStatus({
  message,
  live,
}: {
  message: ChatMessage;
  live: boolean;
}) {
  const { t } = useTranslation();
  const tool = message.toolData!;
  const video = tool.name === "generate_video";
  const args = parseActionArgs(tool.arguments);
  const count = !video && typeof args.count === "number" ? args.count : 1;
  const output = parseActionArgs(tool.output);
  const timing = parseActionArgs(output.timing);
  const rows = output[video ? "videos" : "images"];
  const completed =
    output.status === "completed" && Array.isArray(rows) && rows.length > 0;
  const failed =
    message.status === "error" ||
    output.is_error === true ||
    output.status === "failed";
  const error = parseActionArgs(output.error);
  const errorLabel =
    error.code === "credit_limit_reached"
      ? "dailyLimit"
      : error.code === "insufficient_credits"
      ? "noCredits"
      : error.code === "download_failed"
      ? "downloadFailed"
      : undefined;
  const active = live && !failed && !completed && !tool.output;
  const progress = tool.mediaProgress;
  const partial = completed && !video && rows.length < count;
  const phase = partial
    ? "partial"
    : completed
    ? "completed"
    : failed
    ? "failed"
    : active
    ? progress?.phase || "preparing"
    : "unconfirmed";
  const Icon = video ? Film : Images;
  return (
    <section
      className={styles.mediaTask}
      aria-busy={active}
      aria-label={t(video ? "mediaTask.video" : "mediaTask.image", { count })}
    >
      <Icon size={18} aria-hidden />
      <div className={styles.mediaTaskBody}>
        <strong>
          {t(video ? "mediaTask.video" : "mediaTask.image", { count })}
        </strong>
        <div className={styles.mediaTaskMeta}>
          <span role="status">
            {t("mediaTask." + phase)}
            {completed && !video
              ? t("mediaTask.deliveredCount", { count: rows.length })
              : ""}
          </span>
          {active && message.timestamp > 0 && (
            <LiveElapsed start={message.timestamp} />
          )}
          {(completed || failed) && typeof timing.total_ms === "number" && (
            <time>
              {t("mediaTask.total", {
                time: elapsedLabel(timing.total_ms, t),
              })}
            </time>
          )}
        </div>
        {failed && errorLabel && <small>{t("mediaTask." + errorLabel)}</small>}
        {active &&
          phase === "generating" &&
          typeof progress?.percent === "number" && (
            <div className={styles.mediaTaskProgress}>
              <progress
                aria-label={t("mediaTask.generating")}
                max={100}
                value={progress.percent}
              />
              <span>{progress.percent}%</span>
            </div>
          )}
        {completed && typeof timing.ready_ms === "number" && (
          <small>
            {t("mediaTask.timeToReady", {
              time: elapsedLabel(timing.ready_ms, t),
            })}
          </small>
        )}
        {completed && typeof tool.deliveryToChatMs === "number" ? (
          <small>
            {t("mediaTask.toChat", {
              time: elapsedLabel(tool.deliveryToChatMs, t),
            })}
          </small>
        ) : (
          completed &&
          typeof timing.delivery_ms === "number" && (
            <small>
              {t("mediaTask.deliveryTime", {
                time: elapsedLabel(timing.delivery_ms, t),
              })}
            </small>
          )
        )}
      </div>
    </section>
  );
}
