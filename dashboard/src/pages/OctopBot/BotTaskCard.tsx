import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import cx from "classnames";
import {
  Check,
  ChevronDown,
  ChevronRight,
  Circle,
  Hand,
  Minus,
  Pause,
  X,
} from "lucide-react";
import AuthImage from "../../components/AuthImage";
import { officeThumbnailUrl } from "../../utils/toolMediaBlocks";
import Markdown from "../../components/Markdown";
import FileTypeIcon from "../../components/FileCard/FileTypeIcon";
import {
  fileTypeLabel,
  fileTypeOf,
  formatFileSize,
  middleEllipsis,
} from "../../components/FileCard/fileCardMeta";
import type { TodoListItem } from "../../utils/parseWriteTodos";
import {
  taskSeconds,
  type BotDeliverable,
  type BotTask,
  type BotTaskCriterion,
  type BotTaskEntry,
} from "./botTasks";
import styles from "./botTaskCard.module.less";

type Phase = "live" | "waiting" | "paused" | "done" | "partial" | "stopped";

function phaseOf(task: BotTask, live: boolean, waiting: boolean): Phase {
  if (task.status !== "running") return task.status;
  if (waiting) return "waiting";
  return live ? "live" : "paused";
}

function useDuration(task: BotTask, ticking: boolean): string {
  const { t } = useTranslation();
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    if (!ticking) return undefined;
    const timer = window.setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => window.clearInterval(timer);
  }, [ticking]);
  const seconds = taskSeconds(task, now);
  return seconds < 60
    ? t("botTask.seconds", { count: seconds })
    : t("botTask.minutes", { count: Math.round(seconds / 60) });
}

function PhaseIcon({ phase }: { phase: Phase }) {
  if (phase === "live") return <span className={styles.spinner} aria-hidden />;
  if (phase === "paused") return <Pause size={14} aria-hidden />;
  if (phase === "waiting") return <Hand size={14} aria-hidden />;
  if (phase === "done") return <Check size={15} aria-hidden />;
  if (phase === "stopped") return <Minus size={15} aria-hidden />;
  return <X size={15} aria-hidden />;
}

function CheckIcon({ status }: { status: BotTaskCriterion["status"] }) {
  if (status === "passed") return <Check size={14} aria-hidden />;
  if (status === "failed") return <X size={14} aria-hidden />;
  if (status === "skipped") return <Minus size={14} aria-hidden />;
  return <Circle size={11} aria-hidden />;
}

function Criteria({ criteria }: { criteria: BotTaskCriterion[] }) {
  const { t } = useTranslation();
  return (
    <ul className={styles.criteria}>
      {criteria.map((item, index) => (
        <li key={index} className={cx(styles.criterion, styles[item.status])}>
          <span
            className={styles.checkIcon}
            title={t(`botTask.check.${item.status}`)}
          >
            <CheckIcon status={item.status} />
          </span>
          <span className={styles.criterionBody}>
            <span>{item.text}</span>
            {item.evidence && (
              <small className={styles.evidence}>{item.evidence}</small>
            )}
          </span>
        </li>
      ))}
    </ul>
  );
}

function Steps({ todos, live }: { todos: TodoListItem[]; live: boolean }) {
  return (
    <ol className={styles.steps}>
      {todos.map((todo) => (
        <li
          key={todo.id}
          className={cx(styles.step, styles[`step_${todo.status}`], {
            [styles.stepNow]: live && todo.status === "in_progress",
          })}
        >
          <span className={styles.stepIcon} aria-hidden>
            {todo.status === "completed" ? (
              <Check size={13} />
            ) : (
              <Circle size={9} />
            )}
          </span>
          <span className={styles.stepText}>{todo.content}</span>
        </li>
      ))}
    </ol>
  );
}

function Deliverables({
  items,
  agentId,
}: {
  items: BotDeliverable[];
  agentId?: string | null;
}) {
  const { t } = useTranslation();
  // A file sent again replaces its earlier version in the list.
  const latest = new Map<string, BotDeliverable>();
  for (const item of items) latest.set(item.name, item);
  return (
    <ul className={styles.deliverables}>
      {[...latest.values()].map((item) => {
        const thumbnailUrl = officeThumbnailUrl(agentId, item.preview);
        const facts = item.facts.map((fact) =>
          t(`botTask.fact.${fact.k}`, { count: fact.n, w: fact.w, h: fact.h }),
        );
        return (
          <li key={item.name} className={styles.deliverable}>
            {thumbnailUrl ? (
              <AuthImage
                url={thumbnailUrl}
                alt={item.name}
                className={styles.officePreview}
              />
            ) : (
              <FileTypeIcon
                kind={fileTypeOf(item.name)}
                label={fileTypeLabel(item.name)}
                size={28}
              />
            )}
            <span className={styles.deliverableBody}>
              <span className={styles.deliverableName} title={item.name}>
                {middleEllipsis(item.name, 40)}
                {item.version > 1 && (
                  <span className={styles.version}>v{item.version}</span>
                )}
              </span>
              <small className={styles.evidence}>
                {[
                  formatFileSize(item.size),
                  t("botTask.checked", {
                    facts: facts.length
                      ? facts.join(" · ")
                      : t("botTask.opens"),
                  }),
                ].join(" · ")}
              </small>
            </span>
          </li>
        );
      })}
    </ul>
  );
}

/**
 * The task card: where the task started in the chat, always showing its newest state —
 * the plan with the current step, and the acceptance criteria with their evidence.
 * A finished task folds into one line; its report sits where it finished.
 */
export default function BotTaskCard({
  entry,
  live,
}: {
  entry: BotTaskEntry;
  /** The Bot is working on this conversation right now. */
  live: boolean;
}) {
  const { t } = useTranslation();
  const { task, todos } = entry;
  const phase = phaseOf(task, live, entry.waiting);
  const finished = task.status !== "running";
  const [open, setOpen] = useState(!finished);
  const [showCriteria, setShowCriteria] = useState(false);
  useEffect(() => {
    if (finished) setOpen(false);
  }, [finished]);
  const duration = useDuration(task, phase === "live");
  const done = todos.filter((todo) => todo.status === "completed").length;
  const meta = [
    task.tier === "deep" ? t("botTask.deep") : null,
    todos.length ? t("botTask.steps", { done, total: todos.length }) : null,
    duration,
  ].filter(Boolean);

  return (
    <section
      className={cx(styles.card, styles[`phase_${phase}`])}
      aria-label={t("botTask.label", { goal: task.goal })}
    >
      <button
        type="button"
        className={styles.header}
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <span className={styles.phaseIcon}>
          <PhaseIcon phase={phase} />
        </span>
        <span className={styles.goal}>{task.goal}</span>
        <span className={styles.meta}>
          <span className={styles.phaseLabel}>
            {t(`botTask.phase.${phase}`)}
          </span>
          {meta.map((item) => (
            <span key={item}>{item}</span>
          ))}
        </span>
        {open ? (
          <ChevronDown size={15} aria-hidden />
        ) : (
          <ChevronRight size={15} aria-hidden />
        )}
      </button>
      {!finished && todos.length > 0 && (
        <div
          className={styles.progress}
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={todos.length}
          aria-valuenow={done}
        >
          <span style={{ width: `${(done / todos.length) * 100}%` }} />
        </div>
      )}
      {open && (
        <div className={styles.body} role="status" aria-live="polite">
          {todos.length > 0 && <Steps todos={todos} live={phase === "live"} />}
          {task.criteria.length > 0 && (
            <>
              <button
                type="button"
                className={styles.toggle}
                aria-expanded={showCriteria}
                onClick={() => setShowCriteria((value) => !value)}
              >
                {t("botTask.criteria", { count: task.criteria.length })}
                {showCriteria ? (
                  <ChevronDown size={13} aria-hidden />
                ) : (
                  <ChevronRight size={13} aria-hidden />
                )}
              </button>
              {showCriteria && <Criteria criteria={task.criteria} />}
            </>
          )}
        </div>
      )}
    </section>
  );
}

/**
 * The delivery report, where the task finished: did it meet each criterion (with the
 * evidence), what is not done, and what the Bot decided by itself.
 */
export function BotTaskReport({
  task,
  agentId,
}: {
  task: BotTask;
  agentId?: string | null;
}) {
  const { t } = useTranslation();
  const duration = useDuration(task, false);
  const [showReview, setShowReview] = useState(false);
  const done = task.status === "done";
  return (
    <section
      className={cx(
        styles.report,
        done ? styles.reportDone : styles.reportPartial,
      )}
    >
      <header className={styles.reportTitle}>
        <span className={styles.phaseIcon}>
          {done ? <Check size={15} aria-hidden /> : <X size={15} aria-hidden />}
        </span>
        <span>
          {t(done ? "botTask.reportDone" : "botTask.reportPartial", {
            goal: task.goal,
          })}
        </span>
      </header>
      {task.summary && <p className={styles.summary}>{task.summary}</p>}
      {Boolean(task.deliverables?.length) && (
        <>
          <h4 className={styles.sectionTitle}>{t("botTask.deliverables")}</h4>
          <Deliverables items={task.deliverables ?? []} agentId={agentId} />
        </>
      )}
      <h4 className={styles.sectionTitle}>{t("botTask.acceptance")}</h4>
      <Criteria criteria={task.criteria} />
      {task.open_issues.length > 0 && (
        <>
          <h4 className={styles.sectionTitle}>{t("botTask.openIssues")}</h4>
          <ul className={styles.plainList}>
            {task.open_issues.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </>
      )}
      {(task.review_status === "issues" ||
        task.review_status === "unverified") && (
        <p className={styles.evidence}>
          {t(
            task.review_status === "issues"
              ? "botTask.reviewIssues"
              : "botTask.reviewUnverified",
          )}
        </p>
      )}
      {Boolean(task.reviews && task.review) && (
        <>
          <h4 className={styles.sectionTitle}>{t("botTask.review")}</h4>
          {/* Reviewers answer in Markdown (often a table): rendered, folded until asked. */}
          <div
            className={cx(styles.review, { [styles.reviewOpen]: showReview })}
          >
            <Markdown content={task.review ?? ""} />
          </div>
          <button
            type="button"
            className={styles.toggle}
            aria-expanded={showReview}
            onClick={() => setShowReview((value) => !value)}
          >
            {t(showReview ? "botTask.hideReview" : "botTask.showReview")}
            {showReview ? (
              <ChevronDown size={13} aria-hidden />
            ) : (
              <ChevronRight size={13} aria-hidden />
            )}
          </button>
        </>
      )}
      {task.assumptions.length > 0 && (
        <>
          <h4 className={styles.sectionTitle}>{t("botTask.assumptions")}</h4>
          <ul className={styles.plainList}>
            {task.assumptions.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </>
      )}
      <footer className={styles.reportFooter}>
        {t("botTask.duration", { time: duration })}
      </footer>
    </section>
  );
}
