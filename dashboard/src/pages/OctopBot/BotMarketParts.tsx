import { useState } from "react";
import { Button } from "antd";
import { ArrowUpRight, Plus } from "lucide-react";
import { useTranslation } from "react-i18next";
import { marketAvatarUrl, type MarketCard } from "../../api/modules/botMarket";
import { BotCharacter } from "./BotCharacter";
import styles from "./botMarket.module.less";

/** The generated portrait, or the template's SVG character when it has none. */
export function MarketAvatar({
  card,
  size,
}: {
  card: Pick<MarketCard, "avatar" | "look">;
  size: number;
}) {
  const [failed, setFailed] = useState(false);
  return (
    <span
      className={styles.avatar}
      style={{ width: size, height: size }}
      aria-hidden
    >
      {card.avatar && !failed ? (
        <img
          src={marketAvatarUrl(card.avatar)}
          alt=""
          loading="lazy"
          onError={() => setFailed(true)}
        />
      ) : (
        <BotCharacter
          size={Math.round(size * 0.7)}
          badges={false}
          look={{ ...card.look, source: "character" }}
        />
      )}
    </span>
  );
}

export function MarketCardView({
  card,
  added,
  canAdd,
  onOpen,
  onAdd,
}: {
  card: MarketCard;
  added: boolean;
  canAdd: boolean;
  onOpen: () => void;
  onAdd: () => void;
}) {
  const { t } = useTranslation();
  return (
    <article className={styles.card}>
      <button type="button" className={styles.cardMain} onClick={onOpen}>
        <MarketAvatar card={card} size={56} />
        <span className={styles.cardText}>
          <strong>{card.name}</strong>
          <small>{t("botMarket.byTeam")}</small>
          <span>{card.tagline}</span>
        </span>
      </button>
      {canAdd && (
        <Button
          size="small"
          className={styles.cardAdd}
          icon={added ? <ArrowUpRight size={14} /> : <Plus size={14} />}
          aria-label={t(added ? "botMarket.openNamed" : "botMarket.addNamed", {
            name: card.name,
          })}
          onClick={onAdd}
        >
          {added ? t("botMarket.open") : t("botMarket.add")}
        </Button>
      )}
    </article>
  );
}
