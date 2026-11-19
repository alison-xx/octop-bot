import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Button, Input, Popconfirm, Spin } from "antd";
import { ArrowUp, Cloud, RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  botCloudApi,
  type CloudConversation,
} from "../../api/modules/botCloud";
import type { WorkspaceBot } from "../../api/modules/octopBot";
import LazyMarkdown from "../../components/Markdown/LazyMarkdown";
import { useServerTimezone } from "../../hooks/useServerTimezone";
import { formatMessageTime } from "../../utils/formatMessageTime";
import { apiErrorMessage } from "../../utils/apiError";
import { BotCharacter, octopCharacter } from "./BotCharacter";
import styles from "./cloud.module.less";

export default function CloudChat({
  accountId,
  sessionId,
  model,
  bot,
  canStart,
  onAccepted,
}: {
  accountId: string;
  sessionId?: string;
  model: string;
  bot?: WorkspaceBot;
  canStart: boolean;
  onAccepted: (id: string) => void;
}) {
  const { t } = useTranslation();
  const timezone = useServerTimezone();
  const [data, setData] = useState<CloudConversation | null>(null);
  const [error, setError] = useState("");
  const [sendError, setSendError] = useState("");
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const requestRef = useRef<{ body: string; id: string }>();
  const submitLock = useRef(false);
  const cancellation = useRef<{ task: string; request: string }>();
  const mounted = useRef(false);
  const version = useRef(0);
  const timeline = useRef<HTMLDivElement>(null);
  const follow = useRef(true);
  const load = useCallback(async () => {
    if (!sessionId) return;
    const current = ++version.current;
    try {
      const history = await botCloudApi.conversation(accountId, sessionId);
      if (current === version.current && mounted.current) {
        setData(history);
        setError("");
      }
    } catch (err) {
      if (current === version.current && mounted.current)
        setError(apiErrorMessage(err, t("octopBot.failed"), t));
    }
  }, [accountId, sessionId, t]);
  const ongoing = data?.tasks.find((task) =>
    ["queued", "running", "waiting_user", "paused"].includes(task.status),
  );
  const hasOngoing = Boolean(ongoing);
  useEffect(() => {
    mounted.current = true;
    void load();
    return () => {
      mounted.current = false;
    };
  }, [load]);
  useEffect(() => {
    if (!sessionId) return;
    const refresh = () => {
      if (document.visibilityState !== "hidden") void load();
    };
    const timer = window.setInterval(refresh, hasOngoing ? 4500 : 20000);
    window.addEventListener("focus", refresh);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", refresh);
    };
  }, [load, sessionId, hasOngoing]);
  const messageCount = data?.items.length;
  const latestTaskStatus = data?.tasks[0]?.status;
  useEffect(() => {
    const el = timeline.current;
    if (el && follow.current) el.scrollTop = el.scrollHeight;
  }, [messageCount, latestTaskStatus]);
  const canSend = Boolean(
    text.trim() &&
      !sending &&
      (!sessionId || data) &&
      (ongoing ? ongoing.can_answer : canStart),
  );
  async function submit() {
    if (!canSend || submitLock.current) return;
    const input = {
      account_id: accountId,
      session_id: sessionId,
      model: !sessionId ? model || undefined : undefined,
      bot_id: bot?.agent_id,
      input_task_id: ongoing?.can_answer ? ongoing.id : undefined,
      message: text.trim(),
    };
    const body = JSON.stringify(input);
    if (requestRef.current?.body !== body)
      requestRef.current = { body, id: crypto.randomUUID() };
    submitLock.current = true;
    setSending(true);
    setSendError("");
    try {
      const task = await botCloudApi.turn({
        ...input,
        request_id: requestRef.current.id,
      });
      if (!mounted.current) return;
      setText("");
      requestRef.current = undefined;
      follow.current = true;
      if (sessionId === task.session_id) await load();
      if (mounted.current) onAccepted(task.session_id);
    } catch (err) {
      if (mounted.current)
        setSendError(apiErrorMessage(err, t("octopBot.failed"), t));
    } finally {
      submitLock.current = false;
      if (mounted.current) setSending(false);
    }
  }
  async function stopTask(id: string) {
    if (!sessionId || submitLock.current) return;
    submitLock.current = true;
    setSending(true);
    setSendError("");
    if (cancellation.current?.task !== id)
      cancellation.current = { task: id, request: crypto.randomUUID() };
    try {
      await botCloudApi.cancelTask(
        accountId,
        sessionId,
        id,
        cancellation.current.request,
      );
      if (mounted.current) await load();
    } catch (err) {
      if (mounted.current)
        setSendError(apiErrorMessage(err, t("octopBot.failed"), t));
    } finally {
      submitLock.current = false;
      if (mounted.current) setSending(false);
    }
  }
  const tasks = data?.tasks || [];
  return (
    <>
      {error && (
        <Alert
          type="error"
          showIcon
          message={error}
          action={
            <Button size="small" onClick={() => void load()}>
              {t("common.retry")}
            </Button>
          }
        />
      )}
      <div
        className={styles.timeline}
        ref={timeline}
        onScroll={(e) => {
          const el = e.currentTarget;
          follow.current =
            el.scrollHeight - el.clientHeight - el.scrollTop < 70;
        }}
      >
        {sessionId && !data && !error ? (
          <Spin />
        ) : !sessionId ? (
          <div className={styles.welcome}>
            <BotCharacter
              bot={bot}
              look={
                bot ? undefined : { ...octopCharacter, source: "character" }
              }
              size={72}
              badges={false}
            />
            <h3>{bot?.name || t("botCloud.defaultBot")}</h3>
            <p>{t("botCloud.startHint")}</p>
          </div>
        ) : null}
        {data?.items.map((m, i) => (
          <article
            className={styles.message}
            data-role={m.role}
            key={(m.created_at || "") + "-" + i}
          >
            <header>
              {t(m.role === "user" ? "octopBot.you" : "botCloud.defaultBot")}
              {m.created_at && (
                <time dateTime={m.created_at}>
                  {formatMessageTime(Date.parse(m.created_at), timezone)}
                </time>
              )}
            </header>
            <LazyMarkdown content={m.content} />
          </article>
        ))}
        {tasks
          .filter(
            (task) =>
              task.status !== "completed" ||
              (task.result &&
                !data?.items.some(
                  (m) =>
                    m.role === "assistant" &&
                    (m.task_id === task.id || m.content === task.result),
                )),
          )
          .map((task) => (
            <section className={styles.taskState} key={task.id}>
              <div>
                <Cloud size={15} />
                <strong>
                  {t("botCloud.status." + task.status, {
                    defaultValue: task.status,
                  })}
                </strong>
              </div>
              {ongoing?.id === task.id && (
                <Popconfirm
                  title={t("botCloud.stopConfirm")}
                  onConfirm={() => void stopTask(task.id)}
                  okText={t("botCloud.stop")}
                >
                  <Button disabled={sending} size="small">
                    {t("botCloud.stop")}
                  </Button>
                </Popconfirm>
              )}
              {task.error && <p>{task.error}</p>}
              {task.status === "completed" && task.result && (
                <LazyMarkdown content={task.result} />
              )}
              {task.can_answer ? (
                <p>{task.question || t("botCloud.answer")}</p>
              ) : (
                task.status === "waiting_user" && (
                  <p>{t("botCloud.handleInLynxce")}</p>
                )
              )}
            </section>
          ))}
      </div>
      <form
        className={styles.composer}
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        {sendError && <Alert type="error" showIcon message={sendError} />}
        <Input.TextArea
          value={text}
          onChange={(e) => setText(e.target.value)}
          maxLength={30000}
          aria-label={t("botCloud.message")}
          placeholder={t(
            ongoing?.can_answer ? "botCloud.answer" : "botCloud.message",
          )}
          autoSize={{ minRows: 2, maxRows: 6 }}
          onKeyDown={(e) => {
            if (
              e.key === "Enter" &&
              !e.shiftKey &&
              !e.nativeEvent.isComposing
            ) {
              e.preventDefault();
              void submit();
            }
          }}
        />
        <div>
          <small>{t("botCloud.cloudBilling")}</small>
          {sessionId && (
            <Button
              aria-label={t("common.refresh")}
              type="text"
              icon={<RefreshCw size={15} />}
              onClick={() => void load()}
            />
          )}
          <Button
            htmlType="submit"
            type="primary"
            shape="circle"
            aria-label={t("octopBot.send")}
            icon={<ArrowUp size={17} />}
            loading={sending}
            disabled={!canSend}
          />
        </div>
      </form>
    </>
  );
}
