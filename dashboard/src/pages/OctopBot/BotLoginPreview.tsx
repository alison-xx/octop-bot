import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  ArrowUp,
  ChevronLeft,
  ChevronRight,
  FileSpreadsheet,
  ListChecks,
  LogIn,
  Monitor,
  Pause,
  Play,
  Plus,
  Users,
} from "lucide-react";
import mascot from "../../assets/avatars/octop-mascot.webp";
import { BotCharacter } from "./BotCharacter";
import styles from "./BotLoginPreview.module.less";

const scenes = ["retail", "sales", "launch"] as const;
const shapes = ["sparkle", "orb", "heart"] as const;
const colors = ["orange", "purple", "rose"] as const;

export default function BotLoginPreview({
  onUse,
  modalOpen,
}: {
  onUse: () => void;
  modalOpen: boolean;
}) {
  const { t } = useTranslation();
  const [index, setIndex] = useState(0);
  const [paused, setPaused] = useState(
    () =>
      window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches === true,
  );
  const [visible, setVisible] = useState(() => !document.hidden);
  const [hovered, setHovered] = useState(false);
  useEffect(() => {
    const onChange = () => setVisible(!document.hidden);
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    const motion = () => {
      if (reduced?.matches) setPaused(true);
    };
    document.addEventListener("visibilitychange", onChange);
    reduced?.addEventListener?.("change", motion);
    return () => {
      document.removeEventListener("visibilitychange", onChange);
      reduced?.removeEventListener?.("change", motion);
    };
  }, []);
  useEffect(() => {
    if (paused || hovered || modalOpen || !visible) return;
    const timer = window.setTimeout(
      () => setIndex((i) => (i + 1) % scenes.length),
      14000,
    );
    return () => window.clearTimeout(timer);
  }, [index, paused, hovered, modalOpen, visible]);
  const scene = scenes[index];
  const key = (name: string) => t("botPreview.scenes." + scene + "." + name);
  const choose = (i: number) => {
    setIndex((i + scenes.length) % scenes.length);
    setPaused(true);
  };
  const avatar = (i: number, size: number) => (
    <BotCharacter
      size={size}
      badges={false}
      look={{ source: "character", shape: shapes[i], color: colors[i] }}
    />
  );
  const rows = key("rows")
    .split("\n")
    .map((row) => row.split("|"));
  return (
    <main className={styles.workspace} aria-label={t("botPreview.workspace")}>
      <aside className={styles.sidebar}>
        <div className={styles.brand}>
          <img src={mascot} alt="" />
          Octop Bot
        </div>
        <button className={styles.newChat} onClick={onUse}>
          <Plus size={16} />
          {t("botPreview.newChat")}
        </button>
        <div className={styles.sectionName}>{t("botPreview.rooms")}</div>
        {scenes.map((s, i) => (
          <button
            key={s}
            className={styles.room}
            data-selected={i === index}
            aria-pressed={i === index}
            onClick={() => choose(i)}
          >
            {avatar(i, 25)}
            <span>{t("botPreview.scenes." + s + ".title")}</span>
          </button>
        ))}
        <div className={styles.sectionName}>{t("botPreview.team")}</div>
        <button className={styles.room} onClick={onUse}>
          <img width="27" src={mascot} alt="" />
          Chief
        </button>
        {scenes.map((s, i) => (
          <button key={s} className={styles.room} onClick={onUse}>
            {avatar(i, 25)}
            {t("botPreview.scenes." + s + ".agent")}
          </button>
        ))}
        <button className={styles.signIn} onClick={onUse}>
          <LogIn size={16} />
          {t("botPreview.signIn")}
        </button>
      </aside>
      <section className={styles.stage}>
        <header className={styles.header}>
          <div>
            <Users size={18} />
            <strong>{key("title")}</strong>
          </div>
          <button className={styles.login} onClick={onUse}>
            {t("botPreview.signIn")}
          </button>
        </header>
        <div className={styles.thread}>
          <div className={styles.transcript}>
            <nav
              className={styles.playback}
              onMouseEnter={() => setHovered(true)}
              onMouseLeave={() => setHovered(false)}
              aria-label={t("botPreview.scenarios")}
            >
              <span className={styles.demo}>{t("botPreview.demo")}</span>
              <span className={styles.counter}>
                {index + 1} / {scenes.length}
              </span>
              <button
                onClick={() => choose(index - 1)}
                aria-label={t("botPreview.previous")}
              >
                <ChevronLeft size={16} />
              </button>
              <button
                onClick={() => setPaused(!paused)}
                aria-label={t(paused ? "botPreview.play" : "botPreview.pause")}
              >
                {paused ? <Play size={14} /> : <Pause size={14} />}
              </button>
              <button
                onClick={() => choose(index + 1)}
                aria-label={t("botPreview.next")}
              >
                <ChevronRight size={16} />
              </button>
            </nav>
            <div className={styles.exchange} key={scene}>
              <p className={styles.question}>{key("question")}</p>
              <div className={styles.reply}>
                <img src={mascot} alt="" />
                <div>
                  <b>Chief</b>
                  <p>{key("dispatch")}</p>
                </div>
              </div>
              <div className={styles.reply}>
                {avatar(index, 31)}
                <div>
                  <b>{key("agent")}</b>
                  <p>{key("answer")}</p>
                  <button
                    type="button"
                    className={styles.computer}
                    onClick={onUse}
                    aria-label={t("botPreview.openComputer")}
                  >
                    <span className={styles.screenbar}>
                      <span>
                        <Monitor size={14} />
                        {t("botPreview.computer")}
                      </span>
                      <span>{t("botPreview.openComputer")} ↗</span>
                    </span>
                    <span className={styles.desktop} data-scene={scene}>
                      <span className={styles.app}>
                        <span className={styles.appbar}>
                          <span className={styles.dots} aria-hidden="true">
                            ● ● ●
                          </span>
                          {key("file")}
                        </span>
                        <span className={styles.sheet}>
                          <strong>{key("sheet")}</strong>
                          {scene === "sales" ? (
                            <span className={styles.pipeline}>
                              {rows.slice(1).map(([account, stage, action]) => (
                                <span className={styles.lead} key={account}>
                                  <em>{stage}</em>
                                  <b>{account}</b>
                                  <span>{action}</span>
                                </span>
                              ))}
                            </span>
                          ) : (
                            rows.map((row, i) => (
                              <span className={styles.row} key={row[0]}>
                                {row.map((cell, j) => (
                                  <span key={j}>
                                    {cell}
                                    {scene === "retail" && i > 0 && j === 1 && (
                                      <i
                                        className={styles.bar}
                                        style={{
                                          width: `${
                                            (Number(cell) /
                                              Number(rows[1][1])) *
                                            85
                                          }%`,
                                        }}
                                      />
                                    )}
                                  </span>
                                ))}
                              </span>
                            ))
                          )}
                        </span>
                      </span>
                    </span>
                  </button>
                  <button className={styles.file} onClick={onUse}>
                    {scene === "launch" ? (
                      <ListChecks size={16} />
                    ) : (
                      <FileSpreadsheet size={16} />
                    )}{" "}
                    {key("result")} <ChevronRight size={14} />
                  </button>
                </div>
              </div>
              <div className={styles.reply}>
                <img src={mascot} alt="" />
                <div>
                  <b>Chief</b>
                  <p>{key("nextStep")}</p>
                </div>
              </div>
            </div>
          </div>
        </div>
        <footer className={styles.footer}>
          <button className={styles.composer} onClick={onUse}>
            <Plus size={18} />
            <span>{t("botPreview.composer")}</span>
            <i>
              <ArrowUp size={17} />
            </i>
          </button>
        </footer>
      </section>
    </main>
  );
}
