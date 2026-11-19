import { useId, useState, type CSSProperties } from "react";
import { Star, UserRound } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { BotAppearance, WorkspaceBot } from "../../api/modules/octopBot";
import { useAuthImageSrc } from "../../hooks/useAuthImageSrc";
import { resolveExpertAvatarUrl } from "../Experts/components/iconForName";
// Static first frame of public/octop-mascot-peek.webp, trimmed for small avatars.
import octopMascot from "../../assets/avatars/octop-mascot.webp";
import data from "../../vendor/ds-bot/characters.json";
import styles from "./characters.module.less";

// Vector geometry and inks from DS Bot. Attribution and Apache license in /licenses/ds-bot.txt.
type Geometry = {
  body: string;
  shade: string;
  light?: string;
  eyes: number[][];
  paints?: (string | number)[][];
};
const shapes: Record<string, Geometry> = data.shapes;
const inks: Record<string, string[]> = data.inks;
export const octopCharacter = { shape: "octop", color: "rose" } as const;
export const shapeIds = [octopCharacter.shape, ...Object.keys(shapes)];
export const inkIds = Object.keys(inks);
export function appearanceOf(bot?: WorkspaceBot): BotAppearance {
  const appearance: BotAppearance = bot?.avatar ?? {
    ...(bot?.is_main ? octopCharacter : { shape: "gumdrop", color: "blue" }),
    source: bot?.icon_url ? "photo" : "character",
  };
  return visibleAppearance(appearance, bot?.is_main);
}
function visibleAppearance(look: BotAppearance, chief = false): BotAppearance {
  if (look.shape === "whale" && chief) return { ...look, ...octopCharacter };
  return {
    ...look,
    shape: look.shape === "whale" ? "gumdrop" : look.shape,
    color: look.color === "deepseek" ? "blue" : look.color,
  };
}
export type BotMotion =
  | "idle"
  | "working"
  | "thinking"
  | "searching"
  | "waiting";
export function colorStyle(color: string): CSSProperties {
  const hex = /^#[0-9a-f]{6}$/i.test(color) ? color : undefined;
  const [light, dark] = inks[color] ?? [
    hex || inks.blue[0],
    hex || inks.blue[1],
  ];
  return { "--bot-color": light, "--bot-dark": dark } as CSSProperties;
}
export function BotCharacter({
  bot,
  look: requestedLook,
  photo,
  size = 32,
  state = "idle",
  admin = false,
  badges = true,
  animatedPortrait = true,
}: {
  bot?: WorkspaceBot;
  look?: BotAppearance;
  photo?: string | null;
  size?: number;
  state?: BotMotion;
  admin?: boolean;
  badges?: boolean;
  animatedPortrait?: boolean;
}) {
  const { t } = useTranslation();
  const look = requestedLook
    ? visibleAppearance(requestedLook, bot?.is_main)
    : appearanceOf(bot);
  const id = "bot-" + useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const seed = bot?.agent_id || look.shape + look.color;
  const phase = Array.from(seed).reduce(
    (n, c) => (n * 31 + c.charCodeAt(0)) >>> 0,
    0,
  );
  const def = shapes[look.shape] ?? shapes.gumdrop;
  const url =
    look.source === "photo"
      ? resolveExpertAvatarUrl(photo ?? bot?.icon_url)
      : null;
  const { src } = useAuthImageSrc(url ?? "");
  const [failed, setFailed] = useState("");
  const showPhoto = Boolean(src && src !== failed);
  const badge = !badges
    ? null
    : state === "waiting"
    ? "waiting"
    : state !== "idle"
    ? "working"
    : admin
    ? "admin"
    : bot?.is_main
    ? "chief"
    : null;
  return (
    <span
      data-bot-avatar={bot?.agent_id}
      data-shape={look.shape}
      data-ink={
        look.shape === octopCharacter.shape ? octopCharacter.color : look.color
      }
      data-motion={state}
      data-compact={size < 24 || undefined}
      className={styles.mark}
      style={
        {
          ...colorStyle(look.color),
          width: size,
          height: size,
          "--bot-phase": `-${phase % 5039}ms`,
          "--bot-breath": `${3800 + (phase % 1100)}ms`,
        } as CSSProperties
      }
    >
      {showPhoto ? (
        <img
          className={styles.photo}
          src={src}
          alt=""
          draggable={false}
          onError={() => setFailed(src)}
        />
      ) : look.shape === octopCharacter.shape ? (
        size >= 48 && animatedPortrait ? (
          <picture className={styles.mascotPortrait}>
            <source
              media="(prefers-reduced-motion: no-preference)"
              srcSet={`${import.meta.env.BASE_URL}octop-mascot-${
                state === "working" ? "type" : "peek"
              }.webp`}
            />
            <img
              className={styles.mascot}
              src={octopMascot}
              alt=""
              draggable={false}
            />
          </picture>
        ) : (
          <img
            className={styles.mascot}
            src={octopMascot}
            alt=""
            draggable={false}
          />
        )
      ) : (
        <svg className={styles.model} viewBox="0 0 100 100" aria-hidden="true">
          <defs>
            {look.color === "aurora" && (
              <linearGradient
                id={id + "g"}
                gradientUnits="userSpaceOnUse"
                x1="18"
                y1="10"
                x2="78"
                y2="92"
              >
                {data.gradients.aurora.map(([offset, color]) => (
                  <stop
                    key={offset}
                    offset={offset}
                    stopColor={String(color)}
                  />
                ))}
              </linearGradient>
            )}
          </defs>
          <g fillRule="evenodd">
            <path
              d={def.body}
              fill={look.color === "aurora" ? `url(#${id}g)` : "currentColor"}
            />
            {def.paints?.map(([d, color, opacity], i) => (
              <path
                key={i}
                d={String(d)}
                fill={String(color)}
                fillOpacity={opacity}
              />
            ))}
            <path d={def.shade} fill="#000" fillOpacity=".07" />
            {def.light && <path d={def.light} fill="#fff" fillOpacity=".36" />}
          </g>
          <g className={styles.face}>
            {def.eyes.map(([x, y, w, h, angle], i) => (
              <g key={i} transform={`translate(${x} ${y}) rotate(${angle})`}>
                <g className={styles.eye}>
                  <rect
                    width={w}
                    height={h}
                    x={-w / 2}
                    y={-h / 2}
                    rx={w / 2}
                    fill="#fffcf5"
                  />
                  {size >= 24 && (
                    <ellipse
                      className={styles.pupil}
                      cx={w * 0.07}
                      cy={h * 0.05}
                      rx={w * 0.28}
                      ry={h * 0.22}
                      fill="#2d2833"
                    />
                  )}
                </g>
              </g>
            ))}
          </g>
        </svg>
      )}
      {badge && (
        <span
          className={styles.badge}
          data-badge={badge}
          role="img"
          aria-label={t(
            badge === "admin" ? "octopBot.admin" : "octopBot.avatar." + badge,
          )}
        >
          {badge === "waiting" ? (
            "?"
          ) : badge === "working" ? null : (
            <Star size={Math.max(8, size * 0.27)} fill="currentColor" />
          )}
        </span>
      )}
    </span>
  );
}
export function GroupCharacter({
  members,
  size = 36,
}: {
  members: WorkspaceBot[];
  size?: number;
}) {
  const count = members.length === 1 ? 2 : Math.max(1, members.length);
  const side =
    count === 1
      ? size
      : count === 2
      ? (size * 2) / 3
      : count === 3
      ? (size * 5) / 9
      : size / 2;
  const rest = size - side;
  const seats =
    count <= 2
      ? [
          [0, 0],
          [rest, rest],
        ]
      : count === 3
      ? [
          [rest / 2, 0],
          [0, rest],
          [rest, rest],
        ]
      : [
          [0, 0],
          [rest, 0],
          [0, rest],
          [rest, rest],
        ];
  return (
    <span
      className={styles.cluster}
      data-group-avatar=""
      style={{ width: size, height: size }}
    >
      {seats.slice(0, Math.min(4, count)).map(([left, top], i) => (
        <span
          key={i}
          className={styles.seat}
          style={{ left, top, width: side, height: side }}
        >
          {i === 3 && members.length > 4 ? (
            <small>+{members.length - 3}</small>
          ) : members[i] ? (
            <BotCharacter
              bot={members[i]}
              size={side}
              badges={false}
              animatedPortrait={false}
            />
          ) : (
            <UserRound size={side * 0.8} />
          )}
        </span>
      ))}
    </span>
  );
}
