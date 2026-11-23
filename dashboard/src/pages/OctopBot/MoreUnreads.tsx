import { useEffect, useRef, useState } from "react";
import { ArrowDown } from "lucide-react";
import { useTranslation } from "react-i18next";
import directory from "./directory.module.less";

/**
 * Floating pill at the foot of the contact list while an unread contact is
 * scrolled out of view below. `watch` re-checks when unread counts change.
 */
export default function MoreUnreads({ watch }: { watch: unknown }) {
  const { t } = useTranslation();
  const ref = useRef<HTMLButtonElement>(null);
  const [below, setBelow] = useState<HTMLElement | null>(null);
  useEffect(() => {
    const list = ref.current?.parentElement;
    if (!list) return;
    const check = () => {
      const edge = list.getBoundingClientRect().bottom;
      const hidden = Array.from(
        list.querySelectorAll<HTMLElement>('[data-unread="true"]'),
      ).find((row) => row.getBoundingClientRect().top > edge - 12);
      setBelow(hidden ?? null);
    };
    check();
    list.addEventListener("scroll", check, { passive: true });
    window.addEventListener("resize", check);
    return () => {
      list.removeEventListener("scroll", check);
      window.removeEventListener("resize", check);
    };
  }, [watch]);
  return (
    <button
      ref={ref}
      type="button"
      className={directory.moreUnreads}
      hidden={!below}
      onClick={() => below?.scrollIntoView({ block: "center" })}
    >
      <ArrowDown size={13} aria-hidden />
      {t("octopBot.moreUnreads")}
    </button>
  );
}
