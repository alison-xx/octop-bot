import { useId } from "react";
import { FILE_TYPE_COLORS, type FileTypeKind } from "./fileCardMeta";
import styles from "./FileCard.module.less";

/** A page with a folded corner; the bottom band carries the type color and label. */
export default function FileTypeIcon({
  kind,
  label,
  size = 40,
}: {
  kind: FileTypeKind;
  label: string;
  size?: number;
}) {
  const clip = useId();
  const page =
    "M7 1h19l11 11v31a4 4 0 0 1-4 4H7a4 4 0 0 1-4-4V5a4 4 0 0 1 4-4z";
  return (
    <svg
      className={styles.typeIcon}
      width={size}
      height={(size * 48) / 40}
      viewBox="0 0 40 48"
      aria-hidden
      data-kind={kind}
    >
      <defs>
        <clipPath id={clip}>
          <path d={page} />
        </clipPath>
      </defs>
      <path className={styles.typeIconPage} d={page} />
      <rect
        x="0"
        y="29"
        width="40"
        height="19"
        fill={FILE_TYPE_COLORS[kind]}
        clipPath={`url(#${clip})`}
      />
      <path className={styles.typeIconFold} d="M26 1v7a4 4 0 0 0 4 4h7z" />
      {label && (
        <text
          x="20"
          y="41.5"
          textAnchor="middle"
          className={styles.typeIconLabel}
          fontSize={label.length > 3 ? 7.5 : 9}
        >
          {label}
        </text>
      )}
    </svg>
  );
}
