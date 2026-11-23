import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import cx from "classnames";
import type { AskQuestion } from "../../api/types/hitl";
import styles from "./botAskCard.module.less";

const LETTERS = "ABCDEFGH";

/** What the user gave for one question. `null` means skipped. */
type Given = { picked: string[]; other: string };
export type BotAskAnswer = Given | null;

const empty = (): Given => ({ picked: [], other: "" });

function answerText(answer: BotAskAnswer): string | null {
  if (!answer) return null;
  const parts = [...answer.picked];
  if (answer.other.trim()) parts.push(answer.other.trim());
  return parts.length ? parts.join("; ") : null;
}

const headOf = (question: AskQuestion) =>
  question.header?.trim() || question.question;

/**
 * Read answers back from the reply the card sent (`head: answer` per line),
 * so a reloaded transcript can still show the review.
 */
export function parseAskAnswers(
  questions: AskQuestion[],
  reply: string | undefined,
): BotAskAnswer[] | null {
  if (!reply) return null;
  const lines = new Map<string, string>();
  for (const line of reply.split("\n")) {
    const at = line.indexOf(": ");
    if (at > 0) lines.set(line.slice(0, at).trim(), line.slice(at + 2).trim());
  }
  if (!questions.some((q) => lines.has(headOf(q)))) return null;
  return questions.map((question) => {
    const text = lines.get(headOf(question));
    if (!text) return null;
    const labels = new Set((question.options ?? []).map((o) => o.label));
    const parts = text.split("; ");
    return {
      picked: parts.filter((part) => labels.has(part)),
      other: parts.filter((part) => !labels.has(part)).join("; "),
    };
  });
}

export interface BotAskCardProps {
  questions: AskQuestion[];
  /** Answering is possible only while pending with a submit handler. */
  onSubmit?: (message: string) => void;
  /** Answers already given, shown as a read-only review. */
  answers?: BotAskAnswer[] | null;
}

/**
 * Question card that sits in the Bot conversation. One question per page;
 * after submitting it turns into a read-only review in place.
 */
export default function BotAskCard({
  questions,
  onSubmit,
  answers: given,
}: BotAskCardProps) {
  const { t } = useTranslation();
  const total = questions.length;
  const [answers, setAnswers] = useState<BotAskAnswer[]>(
    () => given ?? questions.map(empty),
  );
  const [page, setPage] = useState(0);
  const [sent, setSent] = useState(false);
  const [typing, setTyping] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const review = sent || !onSubmit;

  useEffect(() => {
    if (typing) input.current?.focus();
  }, [typing, page]);

  if (total === 0) return null;
  const shown = review && given ? given : answers;
  const isLast = page === total - 1;

  const go = (next: number) => {
    setTyping(false);
    setPage(Math.max(0, Math.min(total - 1, next)));
  };

  const submit = (final: BotAskAnswer[]) => {
    if (!onSubmit) return;
    const lines = questions.flatMap((question, index) => {
      const text = answerText(final[index]);
      return text ? [`${headOf(question)}: ${text}`] : [];
    });
    setSent(true);
    setTyping(false);
    setPage(0);
    onSubmit(lines.length ? lines.join("\n") : t("chat.ask.skipMessage"));
  };

  const advance = (final: BotAskAnswer[]) => {
    if (isLast) submit(final);
    else go(page + 1);
  };

  const update = (answer: BotAskAnswer, then?: "advance") => {
    const next = answers.map((a, i) => (i === page ? answer : a));
    setAnswers(next);
    if (then) advance(next);
  };

  const pick = (label: string) => {
    const question = questions[page];
    const current = answers[page] ?? empty();
    setTyping(false);
    if (question.multi_select) {
      const picked = current.picked.includes(label)
        ? current.picked.filter((v) => v !== label)
        : [...current.picked, label];
      update({ ...current, picked });
    } else {
      update({ picked: [label], other: "" }, isLast ? undefined : "advance");
    }
  };

  const tile = (index: number, on: boolean) => (
    <span className={cx(styles.tile, on && styles.tileOn)} aria-hidden>
      {LETTERS[index] ?? index + 1}
    </span>
  );

  const questionPage = (question: AskQuestion, index: number) => {
    const options = question.options ?? [];
    const answer = answers[index] ?? empty();
    const openEnded = options.length === 0;
    const otherOn = openEnded || (index === page && typing) || !!answer.other;
    return (
      <div
        key={index}
        className={cx(styles.page, (review || index !== page) && styles.hidden)}
        aria-hidden={review || index !== page}
      >
        <div className={styles.title}>{question.question}</div>
        <div
          className={styles.options}
          role={question.multi_select ? "group" : "radiogroup"}
          aria-label={question.question}
        >
          {options.map((option, i) => {
            const on = answer.picked.includes(option.label);
            return (
              <button
                key={option.label}
                type="button"
                role={question.multi_select ? "checkbox" : "radio"}
                aria-checked={on}
                className={cx(styles.row, on && styles.rowOn)}
                onClick={() => pick(option.label)}
              >
                {tile(i, on)}
                <span className={styles.text}>
                  <span>{option.label}</span>
                  {option.description ? (
                    <span className={styles.desc}>{option.description}</span>
                  ) : null}
                </span>
              </button>
            );
          })}
          {otherOn && index === page ? (
            <label className={cx(styles.row, styles.rowOn)}>
              {tile(options.length, true)}
              <input
                ref={input}
                className={styles.input}
                value={answer.other}
                placeholder={
                  openEnded
                    ? t("chat.ask.freeTextPlaceholder")
                    : t("octopBot.ask.somethingElse")
                }
                onFocus={() => setTyping(true)}
                onChange={(e) =>
                  update({
                    picked: question.multi_select ? answer.picked : [],
                    other: e.target.value,
                  })
                }
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.nativeEvent.isComposing) {
                    e.preventDefault();
                    if (answer.other.trim()) advance(answers);
                  }
                }}
              />
            </label>
          ) : (
            <button
              type="button"
              className={cx(styles.row, answer.other && styles.rowOn)}
              onClick={() => setTyping(true)}
            >
              {tile(options.length, Boolean(answer.other))}
              <span className={cx(styles.text, styles.placeholder)}>
                {answer.other || t("octopBot.ask.somethingElse")}
              </span>
            </button>
          )}
        </div>
      </div>
    );
  };

  const reviewPage = (question: AskQuestion, index: number) => {
    const answer = shown[index];
    const options = question.options ?? [];
    const rows = (answer?.picked ?? []).map((label) => ({
      label,
      at: Math.max(
        0,
        options.findIndex((o) => o.label === label),
      ),
    }));
    if (answer?.other) rows.push({ label: answer.other, at: options.length });
    return (
      <div
        key={`review-${index}`}
        className={cx(styles.page, index !== page && styles.hidden)}
        aria-hidden={index !== page}
      >
        <div className={cx(styles.title, styles.titleDone)}>
          {question.question}
        </div>
        <div className={styles.options}>
          {!sent && !given ? null : rows.length ? (
            rows.map((row) => (
              <div key={row.label} className={styles.answer}>
                {tile(row.at, true)}
                <span className={styles.text}>{row.label}</span>
              </div>
            ))
          ) : (
            <div className={cx(styles.answer, styles.placeholder)}>
              {t("octopBot.ask.skipped")}
            </div>
          )}
        </div>
      </div>
    );
  };

  return (
    <section
      className={styles.card}
      aria-label={t("chat.ask.title")}
      data-bot-ask={review ? "review" : "open"}
    >
      <div className={styles.pages}>
        {questions.map(questionPage)}
        {review ? questions.map(reviewPage) : null}
      </div>
      <footer className={styles.footer}>
        <span
          className={styles.dots}
          role="img"
          aria-label={`${page + 1} / ${total}`}
        >
          {questions.map((_, index) => (
            <span
              key={index}
              className={cx(styles.dot, index === page && styles.dotOn)}
            />
          ))}
        </span>
        {review ? (
          <span className={styles.actions}>
            <button
              type="button"
              className={styles.pill}
              disabled={page === 0}
              onClick={() => go(page - 1)}
            >
              {t("chat.ask.back")}
            </button>
            <button
              type="button"
              className={styles.pill}
              disabled={isLast}
              onClick={() => go(page + 1)}
            >
              {t("chat.ask.next")}
            </button>
          </span>
        ) : (
          <span className={styles.actions}>
            {page > 0 ? (
              <button
                type="button"
                className={styles.pill}
                onClick={() => go(page - 1)}
              >
                {t("chat.ask.back")}
              </button>
            ) : null}
            <button
              type="button"
              className={styles.pill}
              onClick={() => update(null, "advance")}
            >
              {t("octopBot.ask.skip")}
            </button>
            <button
              type="button"
              className={cx(styles.pill, styles.primary)}
              onClick={() => advance(answers)}
            >
              {isLast ? t("octopBot.ask.done") : t("chat.ask.next")}
            </button>
          </span>
        )}
      </footer>
    </section>
  );
}
