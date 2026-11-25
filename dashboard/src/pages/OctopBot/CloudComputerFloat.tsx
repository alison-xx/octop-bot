import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { Button, Modal, Space, Spin, Tooltip } from "antd";
import {
  ChevronDown,
  Hand,
  Maximize2,
  Monitor,
  RectangleHorizontal,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  botCloudComputerApi,
  type CloudComputerGlance,
  type CloudComputerStatus,
} from "../../api/modules/botCloudComputer";
import { apiErrorMessage } from "../../utils/apiError";
import CloudComputerScreen from "./CloudComputerScreen";
import styles from "./cloudComputerFloat.module.less";

/** pill: a small badge; window: a live view-only screen; expanded: the big screen. */
export type FloatMode = "hidden" | "pill" | "window" | "expanded";
export type Corner = "br" | "bl" | "tr" | "tl";

const STATUS_POLL_MS = 3000;
const GLANCE_POLL_MS = 5000;
/** A finished turn shrinks the window to the pill after this long. */
const IDLE_TO_PILL_MS = 30_000;
/** A computer used this recently still shows the pill. */
const RECENT_SECONDS = 120;
const MIN_WIDTH = 240;
const MAX_WIDTH = 640;
const DEFAULT_WIDTH = 360;

const storageKey = (name: string) => `octop.cloudFloat.${name}`;

/**
 * The chat header's "cloud computer" button and the float talk through this bus: the
 * button toggles the float, the float reports whether it is open and the Bot is busy.
 */
const bus = new EventTarget();
interface FloatState {
  botId: string;
  open: boolean;
  busy: boolean;
}
export function toggleCloudFloat(botId: string) {
  bus.dispatchEvent(new CustomEvent("toggle", { detail: botId }));
}
function announce(state: FloatState) {
  bus.dispatchEvent(new CustomEvent("state", { detail: state }));
}
function readStored<T>(name: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(storageKey(name));
    return raw === null ? fallback : (JSON.parse(raw) as T);
  } catch {
    return fallback;
  }
}
function writeStored(name: string, value: unknown) {
  try {
    localStorage.setItem(storageKey(name), JSON.stringify(value));
  } catch {
    // Private mode or blocked storage: the float just forgets its place.
  }
}

/**
 * What the float should show for a status, given what it shows now. Pure, so the
 * auto-open / auto-shrink rules are testable without timers.
 */
export function nextMode(
  current: FloatMode,
  status: CloudComputerStatus | null,
  {
    pillOnly,
    idleSinceMs,
    nowMs,
    closed = false,
    pinned = false,
    starting = false,
  }: {
    pillOnly: boolean;
    idleSinceMs: number | null;
    nowMs: number;
    /** The user closed the float for this Bot: only a takeover brings it back. */
    closed?: boolean;
    /** The user asked to see it (header button): show at least the pill. */
    pinned?: boolean;
    /** The user opened the screen and the computer is starting for it: stay open. */
    starting?: boolean;
  },
): FloatMode {
  if (status?.takeover && status.state === "running") return "expanded";
  if (closed) return "hidden";
  if (starting && (current === "window" || current === "expanded"))
    return current;
  if (!status || status.state !== "running") return pinned ? "pill" : "hidden";
  if (status.busy) {
    if (current === "expanded" || current === "window") return current;
    return pillOnly ? "pill" : "window";
  }
  if (current === "expanded") return current;
  if (current === "window") {
    return idleSinceMs !== null && nowMs - idleSinceMs >= IDLE_TO_PILL_MS
      ? "pill"
      : "window";
  }
  if (current === "pill") return "pill";
  if (pinned) return "window";
  const recent =
    status.activity_at != null &&
    nowMs / 1000 - status.activity_at < RECENT_SECONDS;
  return recent ? "pill" : "hidden";
}

/** The corner nearest to a point inside a box of the given size. */
export function nearestCorner(
  x: number,
  y: number,
  width: number,
  height: number,
): Corner {
  const vertical = y < height / 2 ? "t" : "b";
  const horizontal = x < width / 2 ? "l" : "r";
  return `${vertical}${horizontal}` as Corner;
}

/**
 * Octop Bot cloud: while a Bot works on its cloud computer, a floating live screen sits in
 * the corner of the chat (like ChatGPT's agent view). It shrinks to a pill when the Bot is
 * idle, expands for a takeover, and can be dragged to any corner or resized.
 */
export default function CloudComputerFloat({
  botId,
  botName,
}: {
  botId: string;
  botName: string;
}) {
  const { t } = useTranslation();
  const [status, setStatus] = useState<CloudComputerStatus | null>(null);
  const [glance, setGlance] = useState<CloudComputerGlance | null>(null);
  const [mode, setMode] = useState<FloatMode>("hidden");
  const [screen, setScreen] = useState<{ ws: string; session: string } | null>(
    null,
  );
  const [corner, setCorner] = useState<Corner>(() =>
    readStored<Corner>("corner", "br"),
  );
  const [width, setWidth] = useState(() =>
    readStored<number>("width", DEFAULT_WIDTH),
  );
  const [fit, setFit] = useState(() => readStored<boolean>("fit", false));
  const [pillOnly, setPillOnly] = useState(() =>
    readStored<boolean>(`pillOnly.${botId}`, false),
  );
  const [closed, setClosed] = useState(() =>
    readStored<boolean>(`closed.${botId}`, false),
  );
  // Shown on request from the header button (sticks until closed again).
  const [pinned, setPinned] = useState(false);
  // Opening the screen starts (or resumes) the computer; that can take a minute or two.
  const [starting, setStarting] = useState(false);
  // Why the computer did not start (shown on the pill), translated when rendered.
  const [startError, setStartError] = useState<unknown>(null);
  const startingRef = useRef(false);
  useEffect(() => {
    startingRef.current = starting;
  }, [starting]);
  const [busy, setBusy] = useState(false);
  const idleSince = useRef<number | null>(null);
  const [dragging, setDragging] = useState<{ x: number; y: number } | null>(
    null,
  );

  // Status: only while the page is visible.
  useEffect(() => {
    let current = true;
    const read = () => {
      if (document.visibilityState !== "visible") return;
      botCloudComputerApi.status(botId).then(
        (next) => current && setStatus(next),
        () => current && setStatus(null),
      );
    };
    read();
    const timer = window.setInterval(read, STATUS_POLL_MS);
    return () => {
      current = false;
      window.clearInterval(timer);
    };
  }, [botId]);

  useEffect(() => {
    if (status?.busy) idleSince.current = null;
    else if (idleSince.current === null) idleSince.current = Date.now();
    setMode((current) =>
      nextMode(current, status, {
        pillOnly,
        idleSinceMs: idleSince.current,
        nowMs: Date.now(),
        closed,
        pinned,
        starting,
      }),
    );
  }, [status, pillOnly, closed, pinned, starting]);

  const close = useCallback(() => {
    setClosed(true);
    setPinned(false);
    writeStored(`closed.${botId}`, true);
    setMode("hidden");
  }, [botId]);

  // The header button: show the float (as the live window) or close it.
  useEffect(() => {
    const onToggle = (event: Event) => {
      if ((event as CustomEvent<string>).detail !== botId) return;
      if (mode !== "hidden") {
        close();
        return;
      }
      setClosed(false);
      writeStored(`closed.${botId}`, false);
      setPillOnly(false);
      writeStored(`pillOnly.${botId}`, false);
      setPinned(true);
      // The computer icon opens the screen, starting the computer if it is off.
      setStartError(null);
      setStarting(status?.state !== "running");
      setMode("window");
    };
    bus.addEventListener("toggle", onToggle);
    return () => bus.removeEventListener("toggle", onToggle);
  }, [botId, close, mode, status?.state]);

  useEffect(() => {
    announce({ botId, open: mode !== "hidden", busy: Boolean(status?.busy) });
  }, [botId, mode, status?.busy]);

  // Window title and the pill's thumbnail; a glance never wakes the computer.
  useEffect(() => {
    if (mode === "hidden") {
      setGlance(null);
      return;
    }
    let current = true;
    const read = () => {
      if (document.visibilityState !== "visible") return;
      botCloudComputerApi.glance(botId).then(
        (next) => current && setGlance(next),
        () => undefined,
      );
    };
    read();
    const timer = window.setInterval(read, GLANCE_POLL_MS);
    return () => {
      current = false;
      window.clearInterval(timer);
    };
  }, [botId, mode]);

  // The live screen is connected only while it is visible (window or expanded). Tickets are
  // single-use, so moving between the window and the big view takes a fresh one.
  const live = mode === "window" || mode === "expanded" ? mode : null;
  useEffect(() => {
    setScreen(null);
    if (!live) return;
    let current = true;
    botCloudComputerApi.openScreen(botId).then(
      (ticket) => {
        if (!current) return;
        setScreen({ ws: ticket.ws_path, session: ticket.session });
        if (!startingRef.current) return;
        // Up now: stay open as a fresh window once the status says it is running.
        idleSince.current = Date.now();
        botCloudComputerApi
          .status(botId)
          .then(
            (next) => current && setStatus(next),
            () => undefined,
          )
          .finally(() => current && setStarting(false));
      },
      (err) => {
        if (!current) return;
        setScreen(null);
        if (startingRef.current) {
          // It did not start (no free computer, out of credits, ...): say why on the pill.
          setStartError(err ?? new Error());
          setStarting(false);
          setMode("pill");
        }
      },
    );
    return () => {
      current = false;
    };
  }, [botId, live]);

  const collapse = () => {
    setPillOnly(true);
    writeStored(`pillOnly.${botId}`, true);
    setMode("pill");
  };
  const open = () => {
    setPillOnly(false);
    writeStored(`pillOnly.${botId}`, false);
    setStartError(null);
    setStarting(status?.state !== "running");
    setMode("window");
  };
  const takeover = async (active: boolean) => {
    setBusy(true);
    try {
      setStatus(await botCloudComputerApi.takeover(botId, active));
      if (!active) setMode("window");
    } finally {
      setBusy(false);
    }
  };

  const onDragStart = useCallback((event: ReactPointerEvent<HTMLElement>) => {
    if ((event.target as HTMLElement).closest("button")) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    setDragging({ x: event.clientX, y: event.clientY });
  }, []);
  const onDragEnd = useCallback((event: ReactPointerEvent<HTMLElement>) => {
    setDragging(null);
    const next = nearestCorner(
      event.clientX,
      event.clientY,
      window.innerWidth,
      window.innerHeight,
    );
    setCorner(next);
    writeStored("corner", next);
  }, []);
  const onResize = useCallback(
    (event: ReactPointerEvent<HTMLElement>) => {
      if (event.buttons !== 1) return;
      const grow = corner.endsWith("r") ? -event.movementX : event.movementX;
      setWidth((w) => {
        const next = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, w + grow));
        writeStored("width", next);
        return next;
      });
    },
    [corner],
  );

  if (mode === "hidden") return null;

  const title = glance?.window || botName;
  const activity = starting
    ? t("cloudComputer.float.starting")
    : startError
    ? apiErrorMessage(startError, t("cloudComputer.float.startFailed"), t)
    : status?.takeover
    ? t("cloudComputer.float.youControl")
    : status?.state !== "running"
    ? t(
        status?.state === "paused"
          ? "cloudComputer.state.paused"
          : "cloudComputer.state.none",
      )
    : status?.busy && status.activity
    ? t(`cloudComputer.float.activity.${status.activity}`, {
        defaultValue: t("cloudComputer.float.working"),
      })
    : t("cloudComputer.float.idle");

  if (mode === "pill") {
    return (
      <div
        className={styles.pill}
        data-corner={corner}
        data-busy={status?.busy || undefined}
      >
        <button
          type="button"
          className={styles.pillOpen}
          onClick={open}
          aria-label={t("cloudComputer.float.open")}
        >
          {glance?.thumbnail ? (
            <img
              src={`data:image/jpeg;base64,${glance.thumbnail}`}
              alt=""
              className={styles.pillThumb}
            />
          ) : (
            <Monitor size={15} aria-hidden="true" />
          )}
          <span className={styles.dot} aria-hidden="true" />
          <span
            className={`${styles.pillText} ${
              status?.disk_overdue_days ? styles.overdue : ""
            }`}
          >
            {status?.disk_overdue_days
              ? t("cloudComputer.diskOverdue", {
                  days: status.disk_overdue_days,
                })
              : activity}
          </span>
        </button>
        {startError ? (
          <button type="button" className={styles.pillRetry} onClick={open}>
            {t("cloudComputer.float.retry")}
          </button>
        ) : null}
        <button
          type="button"
          className={styles.pillClose}
          onClick={close}
          aria-label={t("cloudComputer.float.close")}
          title={t("cloudComputer.float.close")}
        >
          <X size={13} />
        </button>
      </div>
    );
  }

  return (
    <>
      {mode === "window" && (
        <section
          className={styles.float}
          data-corner={corner}
          data-busy={status?.busy || undefined}
          data-dragging={dragging ? true : undefined}
          style={{ width }}
          aria-label={t("cloudComputer.section")}
        >
          <header
            className={styles.bar}
            onPointerDown={onDragStart}
            onPointerUp={onDragEnd}
          >
            <Monitor size={14} aria-hidden="true" />
            <span className={styles.title} title={title}>
              {title}
            </span>
            <Tooltip title={t("cloudComputer.float.fit")}>
              <Button
                type="text"
                size="small"
                aria-label={t("cloudComputer.float.fit")}
                icon={<RectangleHorizontal size={14} />}
                onClick={() => {
                  setFit((v) => !v);
                  writeStored("fit", !fit);
                }}
              />
            </Tooltip>
            <Tooltip title={t("cloudComputer.float.expand")}>
              <Button
                type="text"
                size="small"
                aria-label={t("cloudComputer.float.expand")}
                icon={<Maximize2 size={14} />}
                onClick={() => setMode("expanded")}
              />
            </Tooltip>
            <Tooltip title={t("cloudComputer.float.collapse")}>
              <Button
                type="text"
                size="small"
                aria-label={t("cloudComputer.float.collapse")}
                icon={<ChevronDown size={14} />}
                onClick={collapse}
              />
            </Tooltip>
            <Tooltip title={t("cloudComputer.float.close")}>
              <Button
                type="text"
                size="small"
                aria-label={t("cloudComputer.float.close")}
                icon={<X size={14} />}
                onClick={close}
              />
            </Tooltip>
          </header>
          <div className={styles.view} data-fit={fit || undefined}>
            {screen && (
              <CloudComputerScreen
                wsPath={screen.ws}
                interactive={false}
                session={screen.session}
              />
            )}
            {starting && !screen ? (
              <div className={styles.starting} role="status">
                <Spin size="small" />
                <span>{t("cloudComputer.float.starting")}</span>
              </div>
            ) : (
              <button
                type="button"
                className={styles.takeHint}
                onClick={() => void takeover(true)}
              >
                <Hand size={14} aria-hidden="true" />
                {t("cloudComputer.float.takeOverHint")}
              </button>
            )}
          </div>
          <footer className={styles.status}>
            <div>{activity}</div>
            {!!status?.disk_gb && (
              <div>
                {t("cloudComputer.diskFee", {
                  gb: status.disk_gb,
                  credits: status.disk_daily_credits,
                })}
                {!status.disk_billing &&
                  ` · ${t("cloudComputer.diskBillingOff")}`}
              </div>
            )}
            {status?.reclaim_notified && (
              <div className={styles.overdue}>
                {t("cloudComputer.reclaimWarning")}
              </div>
            )}
            {!!status?.disk_overdue_days && (
              <div className={styles.overdue}>
                {t("cloudComputer.diskOverdue", {
                  days: status.disk_overdue_days,
                })}
              </div>
            )}
          </footer>
          <span
            className={styles.resize}
            data-corner={corner}
            onPointerMove={onResize}
            aria-hidden="true"
          />
        </section>
      )}
      <Modal
        open={mode === "expanded"}
        title={title}
        width={960}
        footer={
          <Space>
            <span>
              {t(
                status?.takeover
                  ? "cloudComputer.controlHint"
                  : "cloudComputer.viewHint",
              )}
            </span>
            <Button
              type={status?.takeover ? "default" : "primary"}
              loading={busy}
              onClick={() => void takeover(!status?.takeover)}
            >
              {t(
                status?.takeover
                  ? "cloudComputer.handBack"
                  : "cloudComputer.takeOver",
              )}
            </Button>
          </Space>
        }
        onCancel={() => {
          if (status?.takeover) void takeover(false);
          else setMode("window");
        }}
        destroyOnClose
      >
        {!!status?.disk_gb && (
          <div>
            {t("cloudComputer.diskFee", {
              gb: status.disk_gb,
              credits: status.disk_daily_credits,
            })}
            {!status.disk_billing && ` · ${t("cloudComputer.diskBillingOff")}`}
          </div>
        )}
        {status?.reclaim_notified && (
          <div className={styles.overdue}>
            {t("cloudComputer.reclaimWarning")}
          </div>
        )}
        {!!status?.disk_overdue_days && (
          <div className={styles.overdue}>
            {t("cloudComputer.diskOverdue", { days: status.disk_overdue_days })}
          </div>
        )}
        {screen && (
          <div
            className={styles.big}
            data-control={status?.takeover || undefined}
          >
            <CloudComputerScreen
              wsPath={screen.ws}
              interactive={status?.takeover === true}
              session={screen.session}
            />
          </div>
        )}
      </Modal>
    </>
  );
}

/**
 * The chat header's cloud computer button: shows or closes the floating screen, with a
 * breathing dot while the Bot is working on the computer.
 */
export function CloudComputerToggle({ botId }: { botId: string }) {
  const { t } = useTranslation();
  const [state, setState] = useState<FloatState | null>(null);
  useEffect(() => {
    const onState = (event: Event) => {
      const next = (event as CustomEvent<FloatState>).detail;
      if (next.botId === botId) setState(next);
    };
    bus.addEventListener("state", onState);
    return () => bus.removeEventListener("state", onState);
  }, [botId]);
  const label = t(
    state?.open ? "cloudComputer.float.close" : "cloudComputer.float.show",
  );
  return (
    <Button
      type="text"
      className={styles.toggle}
      data-busy={state?.busy || undefined}
      data-open={state?.open || undefined}
      title={label}
      aria-label={label}
      aria-pressed={state?.open ?? false}
      icon={<Monitor size={17} />}
      onClick={() => toggleCloudFloat(botId)}
    />
  );
}
