import {
  Fragment,
  useCallback,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import {
  Alert,
  Button,
  Drawer,
  Dropdown,
  Empty,
  Mentions,
  Spin,
  Tag,
} from "antd";
import {
  ArrowUp,
  ArrowDown,
  BookOpen,
  Flag,
  Folder,
  Link2,
  Paperclip,
  Plus,
  X,
  Settings2,
} from "lucide-react";
import { Link } from "react-router-dom";
import type { MentionsRef } from "antd/es/mentions";
import { CopyButton, QuoteButton } from "../Chat/components/MessageTextActions";
import { dragHasFiles } from "../Chat/utils/droppedFiles";
import { useTranslation } from "react-i18next";
import {
  octopBotApi,
  type BotGroup,
  type GroupDraft,
  type GroupGoal,
  type GroupMessage,
  type WorkspaceBot,
} from "../../api/modules/octopBot";
import LazyMarkdown from "../../components/Markdown/LazyMarkdown";
import { useServerTimezone } from "../../hooks/useServerTimezone";
import { apiErrorMessage } from "../../utils/apiError";
import {
  formatMessageTime,
  formatServerHourMinute,
  formatServerYmd,
} from "../../utils/formatMessageTime";
import { saveBlobAsFile } from "../../utils/saveBlobAsFile";
import { BOT_HOME } from "../../utils/botClientRoute";
import { useCurrentUser } from "../../hooks/useCurrentUser";
import { roomDraft, type RoomRequest } from "./GroupRoomDraft";
import { resolveMentions } from "./groupMentions";
import { groupPollDelay } from "./groupRoomPolling";
import groupStyles from "./GroupRoom.module.less";
import RoomIdentity from "./RoomIdentity";
import directory from "./directory.module.less";
import conversation from "./botConversation.module.less";
import {
  appearanceOf,
  colorStyle,
  BotCharacter,
  GroupCharacter,
} from "./BotCharacter";
import ExpertAgentAvatar from "../Chat/components/ExpertAgentAvatar";
import { GoalForm } from "./GroupForms";
import GroupMemory from "./GroupMemory";
import GroupFiles from "./GroupFiles";
import ReferenceDialog from "./ReferenceDialog";
import styles from "./index.module.less";
import emptyGroupArt from "../../assets/bot/empty-group.webp";

export function mergeMessages(
  previous: GroupMessage[],
  incoming: GroupMessage[],
): GroupMessage[] {
  const known = new Set(previous.map((item) => item.message_id));
  const added = incoming.filter((item) => !known.has(item.message_id));
  return added.length ? [...previous, ...added] : previous;
}

function GroupRoomView({
  group,
  bots,
  title,
  onOpenList,
  onOpenSettings,
  onNewGroup,
  onMember,
  onPreview,
  guide,
  onSent,
}: {
  group: BotGroup;
  bots: WorkspaceBot[];
  title?: React.ReactNode;
  onOpenList?: () => void;
  onOpenSettings?: () => void;
  onNewGroup?: () => void;
  onMember?: (id: string) => void;
  onPreview?: (key: string, text: string) => void;
  /** Onboarding guide shown above the composer. */
  guide?: React.ReactNode;
  /** A message from the composer reached the group. */
  onSent?: () => void;
}) {
  const { t } = useTranslation();
  const standalone = Boolean(title);
  const mobile = Boolean(onOpenList);
  const [details, setDetails] = useState(false);
  const timezone = useServerTimezone();
  const [rows, setRows] = useState<GroupMessage[]>([]);
  const [drafts, setDrafts] = useState<GroupDraft[]>([]);
  const [goal, setGoal] = useState<GroupGoal | null>(null);
  const [goalOpen, setGoalOpen] = useState(false);
  const [memoryOpen, setMemoryOpen] = useState(false);
  const [filesOpen, setFilesOpen] = useState(false);
  const [referenceOpen, setReferenceOpen] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [error, setError] = useState("");
  const [ready, setReady] = useState(false);
  const user = useCurrentUser();
  const composer = roomDraft(user?.id ?? null, group.group_id);
  const { text, attachments, sending, uploading, outbox, uploadError } =
    useSyncExternalStore(composer.subscribe, composer.read);
  const [historyError, setHistoryError] = useState("");
  const [newMessages, setNewMessages] = useState(0);
  const [away, setAway] = useState(false);
  const input = useRef<MentionsRef>(null);
  const previousCount = useRef(0);
  const setText = (value: string) => composer.patch({ text: value });
  const attach = (path: string) => {
    const state = composer.read();
    if (state.attachments.includes(path)) return;
    if (state.attachments.length >= 16) {
      composer.patch({ uploadError: t("octopBot.attachmentLimit") });
      return;
    }
    composer.patch({ attachments: [...state.attachments, path] });
  };
  const fileInput = useRef<HTMLInputElement>(null);
  const [reload, setReload] = useState(0);
  const list = useRef<HTMLDivElement>(null);
  const follow = useRef(true);
  const cursor = useRef<string>();
  const active = useRef(true);
  const members = bots.filter((bot) => group.member_ids.includes(bot.agent_id));
  const describeError = useCallback(
    (e: unknown) => apiErrorMessage(e, t("octopBot.failed"), t),
    [t],
  );
  useEffect(() => {
    let disposed = false;
    active.current = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let loading = false;
    let quietPolls = 0;
    let busy = false;
    const schedule = () => {
      clearTimeout(timer);
      timer = undefined;
      // A hidden tab stops polling; becoming visible refreshes at once.
      if (disposed || document.visibilityState === "hidden") return;
      const live = busy || Boolean(composer.read().sending);
      timer = setTimeout(load, groupPollDelay(live, quietPolls));
    };
    const load = async () => {
      if (loading || disposed) return;
      loading = true;
      clearTimeout(timer);
      try {
        const [newRows, newGoal, newDrafts] = await Promise.all([
          octopBotApi.messages(group.group_id, cursor.current),
          octopBotApi.goal(group.group_id),
          octopBotApi.drafts(group.group_id),
        ]);
        if (disposed) return;
        if (newRows.length)
          cursor.current = newRows[newRows.length - 1].message_id;
        busy = newDrafts.length > 0;
        quietPolls = busy || newRows.length ? 0 : quietPolls + 1;
        setHistoryError("");
        setRows((prev) => mergeMessages(prev, newRows));
        setGoal(newGoal);
        setDrafts(newDrafts);
        setReady(true);
      } catch (e) {
        if (!disposed) {
          setHistoryError(describeError(e));
          setReady(true);
        }
      } finally {
        loading = false;
      }
      schedule();
    };
    const onVisibility = () => {
      if (document.visibilityState === "visible") void load();
      else clearTimeout(timer);
    };
    // A send starts a turn: switch to the fast cadence straight away.
    let sending = composer.read().sending;
    const onComposer = () => {
      const next = composer.read().sending;
      if (next && next !== sending) {
        quietPolls = 0;
        if (!loading) void load();
      }
      sending = next;
    };
    document.addEventListener("visibilitychange", onVisibility);
    const unsubscribe = composer.subscribe(onComposer);
    void load();
    return () => {
      disposed = true;
      active.current = false;
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisibility);
      unsubscribe();
    };
  }, [group.group_id, describeError, reload, composer]);
  useEffect(() => {
    const added = rows.length - previousCount.current;
    previousCount.current = rows.length;
    if (follow.current && list.current)
      list.current.scrollTop = list.current.scrollHeight;
    else if (added > 0) setNewMessages((n) => n + added);
  }, [rows, drafts]);
  const jumpToLatest = () => {
    follow.current = true;
    if (list.current) list.current.scrollTop = list.current.scrollHeight;
    setAway(false);
    setNewMessages(0);
  };
  useEffect(() => {
    const last = rows.at(-1);
    if (standalone && last) {
      const speaker =
        bots.find((bot) => bot.agent_id === last.agent_id)?.name ??
        (last.role === "user" ? t("octopBot.you") : "");
      const text =
        last.text.trim() || last.attachment_paths?.at(-1)?.split("/").pop();
      if (text)
        onPreview?.(
          "group:" + group.group_id,
          (speaker ? speaker + " · " : "") + text,
        );
    }
  }, [rows, standalone, onPreview, group.group_id, bots, t]);
  const deliver = async (request: RoomRequest) => {
    const state = composer.read();
    if (state.sending || state.uploading) return;
    const sameDraft =
      request.fromComposer &&
      state.text.trim() === request.text &&
      JSON.stringify(state.attachments) === JSON.stringify(request.paths);
    const pending = { ...request, error: undefined };
    composer.patch({
      sending: request.id,
      outbox: [...state.outbox.filter((it) => it.id !== request.id), pending],
      ...(sameDraft ? { text: "", attachments: [] } : {}),
    });
    jumpToLatest();
    try {
      await octopBotApi.send(
        group.group_id,
        request.text,
        request.mentions,
        request.id,
        request.paths,
      );
      composer.patch({
        sending: null,
        outbox: composer.read().outbox.filter((it) => it.id !== request.id),
      });
      if (request.fromComposer) onSent?.();
      if (active.current) setReload((value) => value + 1);
    } catch (e) {
      const current = composer.read();
      const restore = sameDraft && !current.text && !current.attachments.length;
      composer.patch({
        sending: null,
        outbox: current.outbox.map((it) =>
          it.id === request.id ? { ...it, error: describeError(e) } : it,
        ),
        ...(restore ? { text: request.text, attachments: request.paths } : {}),
      });
    }
  };
  const send = () => {
    const state = composer.read(),
      message = state.text.trim();
    if (
      (!message && !state.attachments.length) ||
      state.sending ||
      state.uploading
    )
      return;
    const prior = state.outbox.find(
      (it) =>
        it.fromComposer &&
        it.text === message &&
        JSON.stringify(it.paths) === JSON.stringify(state.attachments),
    );
    if (prior) return deliver(prior);
    const addressedText = message
      .split("\n")
      .filter((line) => !line.trimStart().startsWith(">"))
      .join("\n");
    return deliver({
      id: Array.from(crypto.getRandomValues(new Uint32Array(4)), (word) =>
        word.toString(16).padStart(8, "0"),
      ).join(""),
      text: message,
      paths: state.attachments,
      mentions: resolveMentions(addressedText, members),
      fromComposer: true,
    });
  };
  const upload = async (files: File[]) => {
    const state = composer.read();
    if (!files.length || state.uploading || state.sending) return;
    if (files.length + state.attachments.length > 16) {
      composer.patch({ uploadError: t("octopBot.attachmentLimit") });
      return;
    }
    const failures: string[] = [];
    for (const [index, file] of files.entries()) {
      composer.patch({
        uploadError: "",
        uploading: t("botGroupChat.uploading", {
          name: file.name,
          index: index + 1,
          total: files.length,
        }),
      });
      try {
        const saved = await octopBotApi.upload(group.group_id, file);
        attach(saved.path);
      } catch (e) {
        failures.push(
          t("botGroupChat.uploadFailed", {
            name: file.name,
            reason: describeError(e),
          }),
        );
      }
    }
    composer.patch({ uploading: null, uploadError: failures.join("\n") });
  };
  const handleFileDrag = (event: React.DragEvent) => {
    if (!dragHasFiles(event.dataTransfer)) return;
    event.preventDefault();
    event.stopPropagation();
    const available = !sending && !uploading;
    event.dataTransfer.dropEffect = available ? "copy" : "none";
    setDragOver(available);
  };
  const handleFileDrop = (event: React.DragEvent) => {
    const transfer = event.dataTransfer;
    if (!dragHasFiles(transfer) && !transfer.files.length) return;
    event.preventDefault();
    event.stopPropagation();
    setDragOver(false);
    if (sending || uploading) return;
    if (
      Array.from(transfer.items ?? []).some(
        (item) => item.webkitGetAsEntry?.()?.isDirectory,
      )
    ) {
      composer.patch({ uploadError: t("botGroupChat.folderDrop") });
      return;
    }
    if (!transfer.files.length) {
      composer.patch({ uploadError: t("upload.emptyDrop") });
      return;
    }
    void upload(Array.from(transfer.files));
  };
  const inputs = new Map(
    rows
      .filter((row) => row.role === "user")
      .map((row) => [row.request_id, row]),
  );
  const retryMember = (errorRow: GroupMessage, original: GroupMessage) => {
    if (!errorRow.agent_id) return;
    return deliver({
      id: "retry-" + errorRow.message_id,
      text: original.text,
      paths: original.attachment_paths ?? [],
      mentions: [errorRow.agent_id],
      fromComposer: false,
    });
  };
  const fileName = (path: string) => path.split("/").pop() || path;
  const download = async (path: string) => {
    try {
      await saveBlobAsFile(
        await octopBotApi.download(group.group_id, path),
        fileName(path),
      );
    } catch (e) {
      if (active.current) setError(describeError(e));
    }
  };
  const info = details && (
    <div className={directory.groupInfo}>
      <div className={directory.panelActions}>
        <button
          type="button"
          title={t("octopBot.groupSettings")}
          aria-label={t("octopBot.groupSettings")}
          onClick={onOpenSettings}
        >
          <Settings2 size={16} />
        </button>
        <button
          type="button"
          title={t("common.close")}
          aria-label={t("common.close")}
          onClick={() => setDetails(false)}
        >
          <X size={16} />
        </button>
      </div>
      <GroupCharacter members={members} size={62} />
      <h2>{group.name}</h2>
      <small>{t("octopBot.memberCount", { count: members.length })}</small>
      <p>{t("botDirectory.groupHistoryHelp")}</p>
      {onNewGroup && (
        <Button icon={<Plus size={15} />} onClick={onNewGroup}>
          {t("botDirectory.newGroupWithMembers")}
        </Button>
      )}
      <div className={directory.infoSection}>
        <h3>{t("octopBot.members")}</h3>
        {members.map((bot) => (
          <button
            type="button"
            key={bot.agent_id}
            onClick={() => onMember?.(bot.agent_id)}
          >
            <BotCharacter bot={bot} size={26} />
            <span>{bot.name}</span>
            {bot.agent_id === group.admin_id && (
              <small>{t("octopBot.admin")}</small>
            )}
          </button>
        ))}
      </div>
      <div className={directory.infoSection}>
        <button type="button" onClick={() => setGoalOpen(true)}>
          <Flag size={15} />
          <span>{goal?.title || t("octopBot.setGoal")}</span>
          {goal && <small>{t("octopBot." + goal.status)}</small>}
        </button>
        <button type="button" onClick={() => setMemoryOpen(true)}>
          <BookOpen size={15} />
          <span>{t("octopBot.groupMemory")}</span>
        </button>
        <button type="button" onClick={() => setFilesOpen(true)}>
          <Folder size={15} />
          <span>{t("octopBot.groupFiles")}</span>
        </button>
      </div>
    </div>
  );
  return (
    <div className={standalone ? directory.chatLayout : directory.transparent}>
      <section className={standalone ? directory.groupRoom : styles.room}>
        {standalone ? (
          <RoomIdentity
            expanded={details}
            onToggle={() => setDetails((v) => !v)}
            onList={onOpenList}
          >
            {title}
          </RoomIdentity>
        ) : (
          <div className={styles.roomTools}>
            <Button
              type="text"
              size="small"
              icon={<Flag size={15} />}
              onClick={() => setGoalOpen(true)}
            >
              {goal?.title || t("octopBot.setGoal")}
            </Button>
            {goal && (
              <>
                <Tag>{t("octopBot." + goal.status)}</Tag>
                <span className={styles.muted}>
                  {
                    goal.stages.filter((stage) => stage.status === "done")
                      .length
                  }
                  /{goal.stages.length}
                </span>
              </>
            )}
            <Button
              size="small"
              type="text"
              icon={<BookOpen size={15} />}
              onClick={() => setMemoryOpen(true)}
            >
              {t("octopBot.groupMemory")}
            </Button>
            <Button
              size="small"
              type="text"
              icon={<Folder size={15} />}
              onClick={() => setFilesOpen(true)}
            >
              {t("octopBot.groupFiles")}
            </Button>
          </div>
        )}
        <div className={groupStyles.timelineArea}>
          <div
            className={standalone ? directory.timeline : styles.timeline}
            ref={list}
            onScroll={(e) => {
              const el = e.currentTarget;
              follow.current =
                el.scrollHeight - el.scrollTop - el.clientHeight < 80;
              setAway(!follow.current);
              if (follow.current) setNewMessages(0);
            }}
          >
            {!ready ? (
              <Spin />
            ) : (
              // A failed first load is not an empty room: the retry alert explains it.
              !rows.length &&
              !historyError && (
                <Empty
                  className={styles.illustratedEmpty}
                  image={<img src={emptyGroupArt} alt="" />}
                  description={t("octopBot.groupWelcome")}
                />
              )
            )}
            {rows.map((row, index) => {
              const speaker = bots.find((bot) => bot.agent_id === row.agent_id);
              const activity = row.stage_number
                ? t(
                    row.is_wrap_up
                      ? "botGroupChat.stageReview"
                      : "botGroupChat.stageWork",
                    { stage: row.stage_number },
                  )
                : row.is_wrap_up
                ? t("botGroupChat.wrapUp")
                : null;
              const original =
                row.role === "error" &&
                speaker &&
                group.member_ids.includes(speaker.agent_id) &&
                !inputs.has("retry-" + row.message_id)
                  ? inputs.get(row.request_id)
                  : undefined;
              const stamp = row.created_at * 1000;
              const date =
                standalone &&
                (!index ||
                  formatServerYmd(stamp, timezone) !==
                    formatServerYmd(
                      rows[index - 1].created_at * 1000,
                      timezone,
                    ));
              return (
                <Fragment key={row.message_id}>
                  {date && (
                    <time
                      className={conversation.date}
                      dateTime={new Date(stamp).toISOString()}
                    >
                      {formatServerYmd(stamp, timezone)}
                    </time>
                  )}
                  {standalone &&
                    newMessages > 0 &&
                    index === rows.length - newMessages && (
                      <div className={conversation.date}>
                        {t("botGroupChat.newMessages", { count: newMessages })}
                      </div>
                    )}
                  <article
                    data-quotable-message=""
                    className={standalone ? directory.message : styles.message}
                    data-role={row.role}
                    data-wrap-up={(standalone && row.is_wrap_up) || undefined}
                    style={
                      standalone && speaker
                        ? colorStyle(appearanceOf(speaker).color)
                        : undefined
                    }
                  >
                    {row.role === "user" ? (
                      standalone ? null : (
                        <ExpertAgentAvatar iconName="user" size={30} />
                      )
                    ) : (
                      <BotCharacter
                        bot={speaker}
                        size={30}
                        admin={row.agent_id === group.admin_id}
                      />
                    )}
                    <div
                      className={
                        standalone ? directory.messageBody : styles.messageBody
                      }
                    >
                      <header>
                        <strong>
                          {row.role === "user"
                            ? t("octopBot.you")
                            : speaker?.name || row.agent_id || group.name}
                        </strong>
                        {activity ? (
                          <small className={directory.admin}>{activity}</small>
                        ) : (
                          standalone &&
                          speaker &&
                          row.agent_id === group.admin_id && (
                            <small className={directory.admin}>
                              {t("octopBot.admin")}
                            </small>
                          )
                        )}
                        <small>
                          {standalone
                            ? formatServerHourMinute(stamp, timezone)
                            : formatMessageTime(stamp, timezone)}
                        </small>
                        {standalone && row.text.trim() && (
                          <span className={directory.messageActions}>
                            <CopyButton text={row.text} />
                            <QuoteButton
                              text={row.text}
                              onQuote={(quote) => {
                                setText(quote + composer.read().text);
                                input.current?.focus();
                              }}
                            />
                          </span>
                        )}
                      </header>
                      <div
                        data-quote-body=""
                        className={
                          standalone
                            ? [
                                directory.bubble,
                                row.role === "user"
                                  ? conversation.outgoing
                                  : conversation.incoming,
                              ].join(" ")
                            : directory.transparent
                        }
                      >
                        {row.role === "error" ? (
                          <Alert
                            type="error"
                            message={row.text}
                            action={
                              original && (
                                <Button
                                  type="text"
                                  size="small"
                                  disabled={Boolean(sending || uploading)}
                                  onClick={() =>
                                    void retryMember(row, original)
                                  }
                                >
                                  {t("botGroupChat.retryMember")}
                                </Button>
                              )
                            }
                          />
                        ) : (
                          <LazyMarkdown content={row.text} />
                        )}
                        {row.thread_id && row.agent_id && (
                          <Link
                            to={
                              BOT_HOME +
                              "/bots/" +
                              encodeURIComponent(row.agent_id) +
                              "/" +
                              encodeURIComponent(row.thread_id)
                            }
                          >
                            {t("octopBot.openApproval")}
                          </Link>
                        )}
                        {row.attachment_paths?.map((path) => (
                          <Button
                            key={path}
                            type="link"
                            icon={<Paperclip size={14} />}
                            onClick={() => void download(path)}
                          >
                            {fileName(path)}
                          </Button>
                        ))}
                      </div>
                    </div>
                  </article>
                </Fragment>
              );
            })}
            {drafts
              .filter(
                (draft) =>
                  draft.text &&
                  !rows.some(
                    (row) =>
                      row.agent_id === draft.agent_id &&
                      row.request_id === draft.request_id &&
                      row.text === draft.text,
                  ),
              )
              .map((draft) => {
                const speaker = bots.find(
                  (bot) => bot.agent_id === draft.agent_id,
                );
                return (
                  <article
                    key={draft.request_id + ":" + draft.agent_id}
                    className={standalone ? directory.message : styles.message}
                    data-role="assistant"
                    style={
                      standalone && speaker
                        ? colorStyle(appearanceOf(speaker).color)
                        : undefined
                    }
                  >
                    <BotCharacter
                      bot={speaker}
                      size={30}
                      admin={draft.agent_id === group.admin_id}
                      state="working"
                    />
                    <div
                      className={
                        standalone ? directory.messageBody : styles.messageBody
                      }
                    >
                      <header>
                        <strong>{speaker?.name ?? draft.agent_id}</strong>
                        {standalone ? (
                          <span
                            role="status"
                            className={conversation.liveStatus}
                          >
                            {t("chat.generating")}
                          </span>
                        ) : (
                          <Spin size="small" />
                        )}
                      </header>
                      <div
                        className={
                          standalone
                            ? [directory.bubble, conversation.incoming].join(
                                " ",
                              )
                            : directory.transparent
                        }
                      >
                        <LazyMarkdown content={draft.text} isStreaming />
                      </div>
                    </div>
                  </article>
                );
              })}
          </div>
          {away && (
            <Button
              className={groupStyles.jump}
              icon={<ArrowDown size={14} />}
              size="small"
              onClick={jumpToLatest}
            >
              {newMessages
                ? t("botGroupChat.newMessages", { count: newMessages })
                : t("botGroupChat.latest")}
            </Button>
          )}
        </div>
        {guide}
        <div
          className={[
            standalone
              ? [directory.compose, conversation.composerShell].join(" ")
              : styles.compose,
            dragOver ? groupStyles.dropActive : "",
          ].join(" ")}
          onDragEnter={handleFileDrag}
          onDragOver={handleFileDrag}
          onDragLeave={(event) => {
            const next = event.relatedTarget;
            if (!(next instanceof Node && event.currentTarget.contains(next)))
              setDragOver(false);
          }}
          onDrop={handleFileDrop}
        >
          {dragOver && (
            <span className={groupStyles.dropHint} role="status">
              {t("botGroupChat.dropFiles")}
            </span>
          )}
          {standalone && (
            <Dropdown
              trigger={["click"]}
              menu={{
                items: [
                  {
                    key: "upload",
                    label: t("common.upload"),
                    icon: <Paperclip size={15} />,
                    disabled:
                      Boolean(sending || uploading) || attachments.length >= 16,
                  },
                  {
                    key: "reference",
                    label: t("octopBot.reference"),
                    icon: <Link2 size={15} />,
                    disabled: Boolean(sending),
                  },
                  {
                    key: "files",
                    label: t("octopBot.groupFiles"),
                    icon: <Folder size={15} />,
                  },
                ],
                onClick: ({ key }) => {
                  if (key === "upload") fileInput.current?.click();
                  else if (key === "reference") setReferenceOpen(true);
                  else setFilesOpen(true);
                },
              }}
            >
              <Button
                type="text"
                loading={Boolean(uploading)}
                className={directory.composePlus}
                title={t("chat.composerMore")}
                aria-label={t("chat.composerMore")}
                icon={<Plus size={17} />}
              />
            </Dropdown>
          )}
          {attachments.length > 0 && (
            <div
              className={[styles.attachments, groupStyles.attachments].join(
                " ",
              )}
            >
              {attachments.map((path) => (
                <Tag
                  key={path}
                  closable={!sending && !uploading}
                  onClose={() =>
                    composer.patch({
                      attachments: composer
                        .read()
                        .attachments.filter((p) => p !== path),
                    })
                  }
                >
                  <span title={fileName(path)}>{fileName(path)}</span>
                </Tag>
              ))}
            </div>
          )}
          {outbox.some((it) => it.id !== sending) && (
            <div className={groupStyles.failures}>
              {outbox
                .filter((it) => it.id !== sending)
                .map((it) => (
                  <Alert
                    key={it.id}
                    className={groupStyles.failure}
                    type="error"
                    showIcon
                    message={it.error || t("botGroupChat.unconfirmed")}
                    description={it.text || it.paths.map(fileName).join(", ")}
                    closable
                    onClose={() =>
                      composer.patch({
                        outbox: composer
                          .read()
                          .outbox.filter((item) => item.id !== it.id),
                      })
                    }
                    action={
                      <Button
                        size="small"
                        disabled={Boolean(sending || uploading)}
                        onClick={() => void deliver(it)}
                      >
                        {t("botGroupChat.retrySend")}
                      </Button>
                    }
                  />
                ))}
            </div>
          )}
          {historyError && (
            <Alert
              type="warning"
              message={historyError}
              action={
                <Button size="small" onClick={() => setReload((n) => n + 1)}>
                  {t("octopBot.retry")}
                </Button>
              }
            />
          )}
          {uploadError && (
            <Alert
              type="error"
              showIcon
              message={uploadError}
              closable
              onClose={() => composer.patch({ uploadError: "" })}
            />
          )}
          {(sending || uploading) && (
            <div className={groupStyles.status} role="status">
              <Spin size="small" />
              {uploading || t("botGroupChat.sending")}
            </div>
          )}
          {error && (
            <Alert
              type="error"
              showIcon
              message={error}
              closable
              onClose={() => setError("")}
            />
          )}
          <Mentions
            ref={input}
            value={text}
            onChange={setText}
            aria-label={t("octopBot.message")}
            placeholder={
              standalone
                ? t("botDirectory.messageTo", { name: group.name })
                : t("octopBot.groupPrompt")
            }
            autoSize={{ minRows: standalone ? 1 : 2, maxRows: 6 }}
            options={members.map((bot) => ({
              key: bot.agent_id,
              value: members.some(
                (other) =>
                  other.agent_id !== bot.agent_id && other.name === bot.name,
              )
                ? bot.agent_id
                : bot.name,
              label: bot.name,
            }))}
            onPressEnter={(event) => {
              if (
                event.nativeEvent.isComposing ||
                event.nativeEvent.keyCode === 229
              )
                return;
              if (
                (standalone && !event.shiftKey) ||
                event.metaKey ||
                event.ctrlKey
              ) {
                event.preventDefault();
                void send();
              }
            }}
          />
          {!standalone && (
            <Button
              type="text"
              title={t("common.upload")}
              aria-label={t("common.upload")}
              icon={<Paperclip size={16} />}
              loading={Boolean(uploading)}
              disabled={
                Boolean(sending || uploading) || attachments.length >= 16
              }
              onClick={() => fileInput.current?.click()}
            />
          )}
          <input
            type="file"
            multiple
            hidden
            ref={fileInput}
            onChange={(e) => {
              const files = Array.from(e.currentTarget.files ?? []);
              e.currentTarget.value = "";
              void upload(files);
            }}
          />
          {!standalone && (
            <Button
              type="text"
              disabled={Boolean(sending)}
              icon={<Link2 size={15} />}
              onClick={() => setReferenceOpen(true)}
            >
              {t("octopBot.reference")}
            </Button>
          )}
          <Button
            type="primary"
            className={
              standalone
                ? [directory.send, conversation.send].join(" ")
                : undefined
            }
            aria-label={t("octopBot.send")}
            loading={Boolean(sending)}
            disabled={
              Boolean(uploading || sending) ||
              (!text.trim() && !attachments.length)
            }
            icon={<ArrowUp size={16} />}
            onClick={() => {
              // Keep typing flow: the button disables itself once the draft clears.
              input.current?.focus();
              void send();
            }}
          >
            {!standalone && t("octopBot.send")}
          </Button>
        </div>
        {goalOpen && (
          <GoalForm
            group={group}
            bots={bots}
            goal={goal}
            onClose={() => setGoalOpen(false)}
            onSaved={(value) => {
              setGoal(value);
              setGoalOpen(false);
            }}
          />
        )}
        {memoryOpen && (
          <GroupMemory
            id={group.group_id}
            onClose={() => setMemoryOpen(false)}
          />
        )}
        {filesOpen && (
          <GroupFiles
            id={group.group_id}
            onClose={() => setFilesOpen(false)}
            onAttach={
              sending || uploading
                ? undefined
                : (path) => {
                    attach(path);
                    setFilesOpen(false);
                  }
            }
          />
        )}
        {referenceOpen && (
          <ReferenceDialog
            onClose={() => setReferenceOpen(false)}
            onPick={(value) =>
              setText(
                [composer.read().text, value].filter(Boolean).join("\n\n"),
              )
            }
          />
        )}
      </section>
      {standalone &&
        details &&
        (mobile ? (
          <Drawer
            placement="right"
            width={292}
            open
            closable={false}
            onClose={() => setDetails(false)}
            styles={{ body: { padding: 0 } }}
          >
            {info}
          </Drawer>
        ) : (
          <aside className={directory.infoPanel}>{info}</aside>
        ))}
    </div>
  );
}

export default function GroupRoom(
  props: React.ComponentProps<typeof GroupRoomView>,
) {
  const user = useCurrentUser();
  return (
    <GroupRoomView
      key={JSON.stringify([user?.id, props.group.group_id])}
      {...props}
    />
  );
}
