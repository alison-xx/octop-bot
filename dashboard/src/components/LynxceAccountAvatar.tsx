import { useState } from "react";
import styles from "../pages/OctopBot/accountMenu.module.less";

export function LynxceAccountAvatar({
  name,
  url,
  className = styles.avatar,
}: {
  name: string;
  url?: string | null;
  className?: string;
}) {
  const [failed, setFailed] = useState<string | null>(null);
  return (
    <span className={className}>
      {url && url !== failed ? (
        <img
          className={styles.accountPhoto}
          src={url}
          alt=""
          referrerPolicy="no-referrer"
          onError={() => setFailed(url)}
        />
      ) : (
        Array.from(name.trim())[0]?.toLocaleUpperCase() || "?"
      )}
    </span>
  );
}
