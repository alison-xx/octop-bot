import { useCallback, useEffect, useMemo, useState } from "react";
import { Alert, Button, Empty, Input, Spin, message } from "antd";
import {
  ArrowLeft,
  BookOpen,
  CalendarClock,
  ListChecks,
  MessageCircle,
  Plug,
  Search,
  Sparkles,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import {
  botMarketApi,
  type MarketCard,
  type MarketCategory,
  type MarketDetail,
  type MarketImport,
} from "../../api/modules/botMarket";
import { useCurrentUser } from "../../hooks/useCurrentUser";
import { apiErrorMessage } from "../../utils/apiError";
import {
  BOT_CAPABILITIES,
  BOT_HOME,
  BOT_MARKET,
  botClientDestination,
  botMarketPath,
} from "../../utils/botClientRoute";
import { navAllowed } from "../../utils/permissions";
import BotMarketImport from "./BotMarketImport";
import { MarketAvatar, MarketCardView } from "./BotMarketParts";
import styles from "./botMarket.module.less";

const FEATURED = "featured";
const botPath = (id: string) => BOT_HOME + "/bots/" + encodeURIComponent(id);

function useMarket() {
  const [data, setData] = useState<{
    categories: MarketCategory[];
    templates: MarketCard[];
  } | null>(null);
  const [mine, setMine] = useState<Record<string, string[]>>({});
  const [error, setError] = useState<unknown>(null);
  const loadMine = useCallback(
    () =>
      botMarketApi
        .mine()
        .then((r) => setMine(r.imports))
        .catch(() => undefined),
    [],
  );
  useEffect(() => {
    let live = true;
    botMarketApi
      .list()
      .then((r) => live && setData(r))
      .catch((e) => live && setError(e));
    void loadMine();
    return () => {
      live = false;
    };
  }, [loadMine]);
  return { data, mine, error, loadMine };
}

function Section({
  icon,
  title,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className={styles.detailSection}>
      <h2>
        {icon}
        {title}
      </h2>
      {children}
    </section>
  );
}

function Detail({
  slug,
  added,
  canAdd,
  autoImport,
  onImported,
}: {
  slug: string;
  added: string[];
  canAdd: boolean;
  autoImport: boolean;
  onImported: (result: MarketImport) => void;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [detail, setDetail] = useState<MarketDetail | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [importing, setImporting] = useState(false);
  useEffect(() => {
    let live = true;
    setDetail(null);
    setError(null);
    botMarketApi
      .get(slug)
      .then((r) => {
        if (!live) return;
        setDetail(r);
        if (autoImport && canAdd) setImporting(true);
      })
      .catch((e) => live && setError(e));
    return () => {
      live = false;
    };
  }, [slug, autoImport, canAdd]);
  if (error)
    return (
      <Alert
        className={styles.center}
        type="error"
        message={apiErrorMessage(error, t("botMarket.loadFailed"), t)}
      />
    );
  if (!detail) return <Spin className={styles.center} />;
  return (
    <div className={styles.detail}>
      <div className={styles.hero}>
        <MarketAvatar card={detail} size={104} />
        <div className={styles.heroText}>
          <h1>{detail.name}</h1>
          <small>{t("botMarket.byTeam")}</small>
          <p className={styles.tagline}>{detail.tagline}</p>
          <p>{detail.description}</p>
          <div className={styles.heroActions}>
            {canAdd && (
              <Button type="primary" onClick={() => setImporting(true)}>
                {added.length
                  ? t("botMarket.importAgain")
                  : t("botMarket.import")}
              </Button>
            )}
            {added.length > 0 && (
              <Button onClick={() => navigate(botPath(added[0]))}>
                {t("botMarket.openMine")}
              </Button>
            )}
          </div>
        </div>
      </div>
      <div className={styles.detailGrid}>
        <Section
          icon={<MessageCircle size={16} />}
          title={t("botMarket.starters")}
        >
          <ul className={styles.starters}>
            {detail.starters.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
        </Section>
        <Section
          icon={<ListChecks size={16} />}
          title={t("botMarket.instructions")}
        >
          <p className={styles.role}>{detail.role}</p>
          <ul className={styles.rules}>
            {detail.instructions.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
        </Section>
        <Section icon={<BookOpen size={16} />} title={t("botMarket.memories")}>
          <p className={styles.sectionHint}>{t("botMarket.memoriesHint")}</p>
          <ul className={styles.rules}>
            {detail.memories.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
        </Section>
        {detail.skills.length > 0 && (
          <Section icon={<Sparkles size={16} />} title={t("botMarket.skills")}>
            <p className={styles.sectionHint}>{t("botMarket.skillsHint")}</p>
            <dl className={styles.items}>
              {detail.skills.map((s) => (
                <div key={s.id}>
                  <dt>{s.name}</dt>
                  <dd>{s.summary}</dd>
                </div>
              ))}
            </dl>
          </Section>
        )}
        {detail.routines.length > 0 && (
          <Section
            icon={<CalendarClock size={16} />}
            title={t("botMarket.routines")}
          >
            <p className={styles.sectionHint}>{t("botMarket.routinesHint")}</p>
            <dl className={styles.items}>
              {detail.routines.map((r) => (
                <div key={r.id}>
                  <dt>
                    {r.name}
                    <span className={styles.when}>{r.when}</span>
                  </dt>
                  <dd>{r.prompt}</dd>
                </div>
              ))}
            </dl>
          </Section>
        )}
        {detail.integrations.length > 0 && (
          <Section
            icon={<Plug size={16} />}
            title={t("botMarket.integrations")}
          >
            <p className={styles.sectionHint}>
              {t("botMarket.integrationsHint")}
            </p>
            <div className={styles.chips}>
              {detail.integrations.map((i) => (
                <span key={i.kind} className={styles.chip}>
                  <i style={{ background: i.color ?? undefined }} />
                  {i.name}
                </span>
              ))}
            </div>
          </Section>
        )}
      </div>
      {importing && (
        <BotMarketImport
          template={detail}
          onClose={() => setImporting(false)}
          onImported={onImported}
        />
      )}
    </div>
  );
}

export default function BotMarket() {
  const { t } = useTranslation();
  const user = useCurrentUser();
  const navigate = useNavigate();
  const location = useLocation();
  const { slug, action } = useParams<{ slug?: string; action?: string }>();
  const { data, mine, error, loadMine } = useMarket();
  const [query, setQuery] = useState("");
  const [tab, setTab] = useState<string>("all");
  const canAdd = navAllowed(user, "experts");
  const from: string | undefined = location.state?.from;
  const back =
    !from || from.startsWith(BOT_MARKET) || from.startsWith(BOT_CAPABILITIES)
      ? BOT_HOME
      : botClientDestination(from);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (data?.templates ?? []).filter(
      (c) =>
        !q ||
        c.name.toLowerCase().includes(q) ||
        c.tagline.toLowerCase().includes(q),
    );
  }, [data, query]);

  const onImported = (result: MarketImport) => {
    void loadMine();
    void message.success(
      t(
        result.preparing ? "botMarket.importedPreparing" : "botMarket.imported",
        {
          name: result.name,
        },
      ),
    );
    navigate(botPath(result.agent_id), {
      state: { marketImported: result },
    });
  };
  const open = (card: MarketCard) =>
    navigate(botMarketPath(card.slug), { state: { from } });
  const add = (card: MarketCard) => {
    const existing = mine[card.slug];
    if (existing?.length) navigate(botPath(existing[0]));
    else navigate(botMarketPath(card.slug, true), { state: { from } });
  };

  const renderGrid = (cards: MarketCard[]) => (
    <div className={styles.grid}>
      {cards.map((card) => (
        <MarketCardView
          key={card.slug}
          card={card}
          added={Boolean(mine[card.slug]?.length)}
          canAdd={canAdd}
          onOpen={() => open(card)}
          onAdd={() => add(card)}
        />
      ))}
    </div>
  );

  const body = () => {
    if (error)
      return (
        <Alert
          className={styles.center}
          type="error"
          message={apiErrorMessage(error, t("botMarket.loadFailed"), t)}
        />
      );
    if (!data) return <Spin className={styles.center} />;
    if (slug)
      return (
        <Detail
          slug={slug}
          added={mine[slug] ?? []}
          canAdd={canAdd}
          autoImport={action === "import"}
          onImported={onImported}
        />
      );
    const featured = visible.filter((c) => c.featured);
    const searching = query.trim().length > 0;
    const categories = data.categories.filter(
      (c) => tab === "all" || tab === c.id,
    );
    return (
      <div className={styles.home}>
        <div className={styles.intro}>
          <h1>{t("botMarket.heading")}</h1>
          <p>{t("botMarket.subheading")}</p>
        </div>
        <div className={styles.tabs} role="tablist">
          {[
            { id: "all", name: t("botMarket.all") },
            { id: FEATURED, name: t("botMarket.featured") },
            ...data.categories,
          ].map((c) => (
            <button
              key={c.id}
              type="button"
              role="tab"
              aria-selected={tab === c.id}
              className={styles.tab}
              onClick={() => setTab(c.id)}
            >
              {c.name}
            </button>
          ))}
        </div>
        {visible.length === 0 ? (
          <Empty description={t("botMarket.noMatch")} />
        ) : searching ? (
          renderGrid(visible)
        ) : (
          <>
            {(tab === "all" || tab === FEATURED) && featured.length > 0 && (
              <section className={styles.block}>
                <header>
                  <h2>{t("botMarket.featured")}</h2>
                  <p>{t("botMarket.featuredBlurb")}</p>
                </header>
                {renderGrid(featured)}
              </section>
            )}
            {tab !== FEATURED &&
              categories.map((c) => {
                const cards = visible.filter((v) => v.category === c.id);
                if (!cards.length) return null;
                return (
                  <section className={styles.block} key={c.id}>
                    <header>
                      <h2>{c.name}</h2>
                      <p>{c.blurb}</p>
                    </header>
                    {renderGrid(cards)}
                  </section>
                );
              })}
          </>
        )}
      </div>
    );
  };

  return (
    <section className={styles.root} data-bot-market>
      <header
        className={`${styles.header} octop-desktop-drag`}
        data-octop-chrome-end-pad
      >
        <Button
          type="text"
          icon={<ArrowLeft size={17} />}
          onClick={() =>
            slug
              ? navigate(BOT_MARKET, { state: { from } })
              : navigate(back, { replace: true })
          }
        >
          {slug ? t("botMarket.title") : t("common.backToChat")}
        </Button>
        {!slug && (
          <strong className={styles.headerTitle}>{t("botMarket.title")}</strong>
        )}
        {!slug && (
          <Input
            allowClear
            className={styles.search}
            prefix={<Search size={15} />}
            placeholder={t("botMarket.search")}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        )}
      </header>
      <main className={styles.scroll}>{body()}</main>
    </section>
  );
}
