import { useEffect, useState } from "react";
import { Alert, Button, Empty, Spin } from "antd";
import { Check, Clock3, Coins, RefreshCw, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { lynxceWalletApi } from "../../api/modules/lynxceWallet";
import {
  getAccountUsage,
  type BotUsageSummary,
} from "../../api/modules/botUsage";
import { apiErrorMessage } from "../../utils/apiError";
import { message } from "@/utils/antdMessage";
import { isBotOnlyDesktop } from "../../utils/desktopBridge";
import { formatExactCount } from "../Control/TokenUsage/formatUsageCount";
import { checkoutUrl } from "./WalletBalance";
import {
  formatCredits,
  isLowCredits,
  LOW_CREDITS,
  refreshCredits,
  rememberCheckout,
  useLynxceCredits,
  type CreditsState,
} from "./useLynxceCredits";
import styles from "./creditsWidgets.module.less";

/** Lynxce's recharge page; signs the visitor in first if needed. */
export const LYNXCE_RECHARGE_SITE = "https://admin.lynxce.cn/recharge";
/** Lynxce's account centre, where a key's daily limit is changed. */
export const LYNXCE_ACCOUNT_SITE = "https://admin.lynxce.cn";

/** Open Lynxce's hosted checkout for the account whose balance is shown. */
export function useRecharge() {
  const { t } = useTranslation();
  const credits = useLynxceCredits();
  const [opening, setOpening] = useState(false);
  const recharge = async () => {
    const wallet = credits.wallet;
    if (!wallet || opening) return;
    // Browsers only allow a new tab during the click; open it now, fill it in after.
    const tab = isBotOnlyDesktop()
      ? null
      : window.open("about:blank", "_blank");
    if (tab) tab.opener = null;
    setOpening(true);
    try {
      const link = await lynxceWalletApi.recharge(wallet);
      const url = checkoutUrl(link.url, link.expires_at, wallet.source);
      if (!url) throw new Error(t("botCredits.openFailed"));
      rememberCheckout(wallet, link.expires_at);
      if (tab) tab.location.href = url;
      else window.open(url, "_blank", "noopener,noreferrer");
    } catch (e) {
      tab?.close();
      message.error(apiErrorMessage(e, t("botCredits.openFailed"), t));
      void refreshCredits();
    } finally {
      setOpening(false);
    }
  };
  return { recharge, opening, available: !!credits.wallet };
}

/** "12,800 积分", or nothing while unknown. */
export function CreditsAmount({ credits }: { credits: CreditsState }) {
  const { t, i18n } = useTranslation();
  if (!credits.wallet) return null;
  return (
    <span
      className={styles.amount}
      data-low={isLowCredits(credits) || undefined}
    >
      {t("botCredits.amount", {
        value: formatCredits(credits.wallet.credits, i18n.language),
      })}
    </span>
  );
}

/** Settings → 账号与积分: balance and recharge beside the last 30 days of usage. */
export function CreditsPanel() {
  const { t, i18n } = useTranslation();
  const credits = useLynxceCredits();
  const { recharge, opening } = useRecharge();
  const low = isLowCredits(credits);
  if (credits.status === "none") return null;
  return (
    <div className={styles.panel}>
      <section
        className={styles.balanceCard}
        data-low={low || undefined}
        aria-labelledby="bot-credits-title"
      >
        <div className={styles.balanceHead}>
          <h3 id="bot-credits-title">{t("botCredits.walletTitle")}</h3>
          <Button
            type="text"
            size="small"
            aria-label={t("botCredits.refresh")}
            title={t("botCredits.refresh")}
            loading={credits.status === "loading"}
            icon={<RefreshCw size={14} />}
            onClick={() => void refreshCredits()}
          />
        </div>
        <div className={styles.big} role="status" aria-live="polite">
          {credits.wallet ? (
            <>
              <strong>
                {formatCredits(credits.wallet.credits, i18n.language)}
              </strong>
              <span>{t("botCredits.unit")}</span>
            </>
          ) : credits.status === "error" ? (
            <span className={styles.muted}>—</span>
          ) : (
            <Spin size="small" aria-label={t("botCredits.loading")} />
          )}
        </div>
        {credits.status === "error" && (
          <Alert
            type="warning"
            showIcon
            message={t(
              credits.wallet ? "botCredits.stale" : "botCredits.loadFailed",
            )}
            action={
              <Button size="small" onClick={() => void refreshCredits()}>
                {t("botCredits.retry")}
              </Button>
            }
          />
        )}
        {low ? (
          <p className={styles.lowNote}>{t("botCredits.lowNote")}</p>
        ) : (
          <p className={styles.muted}>{t("botCredits.rate")}</p>
        )}
        <div className={styles.balanceActions}>
          <Button
            type="primary"
            size="large"
            autoInsertSpace={false}
            disabled={!credits.wallet}
            loading={opening}
            onClick={() => void recharge()}
          >
            {t("botCredits.recharge")}
          </Button>
          <Button
            size="large"
            autoInsertSpace={false}
            href={LYNXCE_ACCOUNT_SITE}
            target="_blank"
            rel="noopener noreferrer"
          >
            {t("botCredits.accountCentre")}
          </Button>
        </div>
        <small className={styles.muted}>{t("botCredits.shared")}</small>
      </section>
      <AccountUsage language={i18n.language} />
    </div>
  );
}

function AccountUsage({ language }: { language: string }) {
  const { t } = useTranslation();
  const [data, setData] = useState<{
    bots: BotUsageSummary;
    models: BotUsageSummary;
  } | null>(null);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const [group, setGroup] = useState<"bots" | "models">("bots");
  useEffect(() => {
    let current = true;
    setError("");
    Promise.all([
      getAccountUsage("by_agent"),
      getAccountUsage("by_model"),
    ]).then(
      ([bots, models]) => current && setData({ bots, models }),
      (e) => current && setError(apiErrorMessage(e, t("octopBot.failed"), t)),
    );
    return () => {
      current = false;
    };
  }, [revision, t]);
  const rows = (summary: BotUsageSummary) =>
    [...summary.buckets]
      .filter((b) => b.total_tokens > 0)
      .sort((a, b) => b.total_tokens - a.total_tokens);
  const list = data ? rows(data[group]) : [];
  const top = list[0]?.total_tokens ?? 0;
  return (
    <section className={styles.usage} aria-labelledby="bot-usage-title">
      <div className={styles.usageHead}>
        <h3 id="bot-usage-title">{t("botCredits.usageTitle")}</h3>
        <div
          className={styles.segmented}
          role="group"
          aria-label={t("botCredits.usageGroup")}
        >
          {(
            [
              ["bots", "botCredits.byBot"],
              ["models", "botCredits.byModel"],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              aria-pressed={group === value}
              onClick={() => setGroup(value)}
            >
              {t(label)}
            </button>
          ))}
        </div>
      </div>
      {error ? (
        <Alert
          type="error"
          showIcon
          message={error}
          action={
            <Button size="small" onClick={() => setRevision((n) => n + 1)}>
              {t("botCredits.retry")}
            </Button>
          }
        />
      ) : !data ? (
        <Spin />
      ) : data.bots.total_tokens === 0 && data.bots.model_calls === 0 ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={t("botCredits.noUsage")}
        />
      ) : (
        <>
          <dl className={styles.stats}>
            <div>
              <dt>{t("botCredits.tokens")}</dt>
              <dd>{formatExactCount(data.bots.total_tokens, language)}</dd>
            </div>
            <div>
              <dt>{t("botCredits.calls")}</dt>
              <dd>{formatExactCount(data.bots.model_calls, language)}</dd>
            </div>
          </dl>
          <ul className={styles.rows} aria-label={t("botCredits.usageTitle")}>
            {list.map((row) => (
              <li key={row.key}>
                <span>{row.label || row.key}</span>
                <span className={styles.bar} aria-hidden="true">
                  <span
                    style={{
                      width: `${Math.max(
                        2,
                        top ? (row.total_tokens / top) * 100 : 0,
                      )}%`,
                    }}
                  />
                </span>
                <b>{formatExactCount(row.total_tokens, language)}</b>
              </li>
            ))}
          </ul>
          <small className={styles.muted}>{t("botCredits.usageHint")}</small>
        </>
      )}
    </section>
  );
}

function dismissKey(credits: CreditsState) {
  const wallet = credits.wallet;
  return wallet
    ? "octop.lowCredits.dismissed." +
        (wallet.account_id ?? wallet.connection_id)
    : "";
}

/** Chat top bar when fewer than 100 credits are left; dismissed until it recovers. */
export function LowCreditsBanner() {
  const { t, i18n } = useTranslation();
  const credits = useLynxceCredits();
  const { recharge, opening } = useRecharge();
  const key = dismissKey(credits);
  const low = isLowCredits(credits);
  const [dismissed, setDismissed] = useState(false);
  useEffect(() => {
    if (!key) return;
    try {
      if (!low) localStorage.removeItem(key);
      setDismissed(low && localStorage.getItem(key) === "1");
    } catch {
      setDismissed(false);
    }
  }, [key, low]);
  if (!low || dismissed || !credits.wallet) return null;
  return (
    <div className={styles.banner} role="status">
      <Coins size={15} aria-hidden />
      <span>
        {t("botCredits.lowBanner", {
          value: formatCredits(credits.wallet.credits, i18n.language),
        })}
      </span>
      <Button
        size="small"
        type="primary"
        autoInsertSpace={false}
        loading={opening}
        onClick={() => void recharge()}
      >
        {t("botCredits.recharge")}
      </Button>
      <Button
        size="small"
        type="text"
        aria-label={t("botCredits.dismiss")}
        title={t("botCredits.dismiss")}
        icon={<X size={14} />}
        onClick={() => {
          try {
            localStorage.setItem(key, "1");
          } catch {
            /* Private mode: hide for this page only. */
          }
          setDismissed(true);
        }}
      />
    </div>
  );
}

/** A reply that stopped because the Lynxce wallet ran dry: recharge, then continue. */
export function CreditsRequiredCard({
  onContinue,
  kind = "credits",
}: {
  onContinue?: () => void;
  /** limit: the wallet has credits but today's per-key cap is used up. */
  kind?: "credits" | "limit";
}) {
  const { t, i18n } = useTranslation();
  const credits = useLynxceCredits();
  const { recharge, opening, available } = useRecharge();
  useEffect(() => {
    void refreshCredits();
  }, []);
  if (kind === "limit")
    return (
      <div className={styles.outCard} role="alert" data-state="limit">
        <div className={styles.outHead}>
          <span className={styles.outIcon} aria-hidden>
            <Clock3 size={16} />
          </span>
          <strong>{t("botCredits.limitTitle")}</strong>
        </div>
        <p>{t("botCredits.limitBody")}</p>
        <small className={styles.muted}>
          {t("botCredits.limitLink")}{" "}
          <a
            href={LYNXCE_ACCOUNT_SITE}
            target="_blank"
            rel="noopener noreferrer"
          >
            {LYNXCE_ACCOUNT_SITE.replace("https://", "")}
          </a>
        </small>
        {onContinue && (
          <div className={styles.outActions}>
            <Button autoInsertSpace={false} onClick={onContinue}>
              {t("botCredits.continue")}
            </Button>
          </div>
        )}
      </div>
    );
  const enough =
    credits.status === "ready" &&
    !!credits.wallet &&
    credits.wallet.credits >= LOW_CREDITS;
  return (
    <div
      className={styles.outCard}
      role="alert"
      data-state={enough ? "ready" : "out"}
    >
      <div className={styles.outHead}>
        <span className={styles.outIcon} aria-hidden>
          {enough ? <Check size={16} /> : <Coins size={16} />}
        </span>
        <strong>
          {t(enough ? "botCredits.readyTitle" : "botCredits.outTitle")}
        </strong>
      </div>
      <p>{t(enough ? "botCredits.outReady" : "botCredits.outBody")}</p>
      {credits.wallet && (
        <small className={styles.muted}>
          {t("botCredits.balanceNow", {
            value: formatCredits(credits.wallet.credits, i18n.language),
          })}
        </small>
      )}
      {!enough && (
        <small className={styles.muted}>
          {t("botCredits.siteLabel")}{" "}
          <a
            href={LYNXCE_RECHARGE_SITE}
            target="_blank"
            rel="noopener noreferrer"
          >
            {LYNXCE_RECHARGE_SITE.replace("https://", "")}
          </a>
        </small>
      )}
      <div className={styles.outActions}>
        {!enough && available && (
          <Button
            type="primary"
            autoInsertSpace={false}
            loading={opening}
            onClick={() => void recharge()}
          >
            {t("botCredits.recharge")}
          </Button>
        )}
        {onContinue && (
          <Button
            type={enough ? "primary" : "default"}
            autoInsertSpace={false}
            onClick={onContinue}
          >
            {t("botCredits.continue")}
          </Button>
        )}
      </div>
    </div>
  );
}
