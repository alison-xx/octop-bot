import { useCallback, useEffect, useRef, useState } from "react";
import { Button, Spin } from "antd";
import { Coins, ExternalLink, RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  lynxceWalletApi,
  type LynxceWallet,
  type WalletSource,
} from "../../api/modules/lynxceWallet";
import { parseApiError } from "../../utils/apiError";
import styles from "./LynxceWallet.module.less";

/** The hosted checkout, only if it is exactly Lynxce's recharge page with a fresh ticket. */
export function checkoutUrl(raw: string, expiry: string, source: WalletSource) {
  const left = Date.parse(expiry) - Date.now();
  if (!(left > 0 && left <= 16 * 60_000)) return null;
  try {
    const url = new URL(raw);
    const params = [...url.searchParams];
    const tokenFormat =
      source === "model"
        ? /^mcrt1\.[A-Za-z0-9_-]{40,4090}$/
        : /^(?!mcrt1\.)[A-Za-z0-9_-]{1,4096}\.[A-Za-z0-9_-]{43}$/;
    if (
      url.origin === "https://admin.lynxce.cn" &&
      url.pathname === "/recharge" &&
      !url.username &&
      !url.password &&
      !url.hash &&
      params.length === 1 &&
      params[0][0] === "token" &&
      tokenFormat.test(params[0][1])
    )
      return url.href;
  } catch {
    /* Invalid checkout response. */
  }
  return null;
}

function identity(wallet: LynxceWallet | null) {
  if (!wallet || wallet.recharge_mode !== "ticket") return null;
  return wallet.source === "model" ? wallet.connection_id : wallet.account_id;
}

type WalletProps = {
  source: WalletSource;
  accountId?: string;
  onAuthorize?: (binding: string) => Promise<void>;
  resumeCheckout?: string;
  onResumeHandled?: () => void;
};

export default function WalletBalance({
  source,
  accountId,
  onAuthorize,
  resumeCheckout,
  onResumeHandled,
}: WalletProps) {
  const { t, i18n } = useTranslation();
  const [wallet, setWallet] = useState<LynxceWallet | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [opening, setOpening] = useState(false);
  const [reauthorized, setReauthorized] = useState(false);
  const [problem, setProblem] = useState<"open" | "grant" | null>(null);
  const query = useRef<AbortController>();
  const checkout = useRef<AbortController>();
  const binding = useRef<string | null>(null);

  const applyWallet = useCallback((next: LynxceWallet | null) => {
    const newIdentity = identity(next);
    if (binding.current !== newIdentity) {
      setReauthorized(false);
      checkout.current?.abort();
      checkout.current = undefined;
      setOpening(false);
      setProblem(null);
    }
    binding.current = newIdentity;
    setWallet(next);
  }, []);
  const refresh = useCallback(async () => {
    if (query.current) return;
    const controller = new AbortController();
    query.current = controller;
    setLoading(true);
    try {
      const next = await lynxceWalletApi.balance(source, controller.signal);
      if (controller.signal.aborted) return;
      if (
        next.source !== source ||
        next.status !== "available" ||
        !Number.isFinite(next.credits) ||
        (source === "cloud" && next.account_id !== accountId)
      ) {
        applyWallet(null);
        setLoadError(true);
      } else {
        applyWallet(next);
        setLoadError(false);
      }
    } catch (err) {
      if (!controller.signal.aborted) {
        if (
          err instanceof Error &&
          /Request failed: (401|403)\b/.test(err.message)
        )
          applyWallet(null);
        setLoadError(true);
      }
    } finally {
      if (query.current === controller) {
        query.current = undefined;
        setLoading(false);
      }
    }
  }, [accountId, source, applyWallet]);

  useEffect(() => {
    applyWallet(null);
    setLoadError(false);
    setProblem(null);
    void refresh();
    const onFocus = () => void refresh();
    const onVisible = () => {
      if (document.visibilityState === "visible") void refresh();
    };
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      query.current?.abort();
      query.current = undefined;
      checkout.current?.abort();
      checkout.current = undefined;
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [refresh, applyWallet]);

  const recharge = useCallback(async () => {
    if (!wallet || !identity(wallet) || checkout.current) return;
    const controller = new AbortController();
    checkout.current = controller;
    setReauthorized(false);
    setOpening(true);
    setProblem(null);
    try {
      const result = await lynxceWalletApi.recharge(wallet, controller.signal);
      if (controller.signal.aborted) return;
      const url = checkoutUrl(result.url, result.expires_at, source);
      if (url) window.open(url, "_blank", "noopener,noreferrer");
      else setProblem("open");
    } catch (err) {
      if (controller.signal.aborted) return;
      if (
        source === "model" &&
        parseApiError(err)?.code === "BOT_LYNXCE_RECHARGE_AUTH_REQUIRED"
      ) {
        setProblem("grant");
      } else {
        setProblem("open");
        if (
          err instanceof Error &&
          /Request failed: (401|403|409)\b/.test(err.message)
        )
          void refresh();
      }
    } finally {
      if (checkout.current === controller) {
        checkout.current = undefined;
        setOpening(false);
      }
    }
  }, [wallet, source, refresh]);

  useEffect(() => {
    if (!resumeCheckout || !identity(wallet)) return;
    onResumeHandled?.();
    if (resumeCheckout === identity(wallet)) void recharge();
    else setReauthorized(true);
  }, [wallet, resumeCheckout, onResumeHandled, recharge]);

  const needsGrant = problem === "grant" && !!onAuthorize;
  return (
    <div className={styles.wallet}>
      <div className={styles.line}>
        <span className={styles.amount} role="status" aria-live="polite">
          <Coins size={15} aria-hidden /> {t("botWallet.balance")}
          {wallet ? (
            <strong>
              {new Intl.NumberFormat(i18n?.language, {
                maximumSignificantDigits: 16,
              }).format(wallet.credits)}
            </strong>
          ) : loading ? (
            <Spin size="small" aria-label={t("botWallet.loading")} />
          ) : (
            <span>{t("botWallet.unavailable")}</span>
          )}
        </span>
        <Button
          size="small"
          type="text"
          aria-label={t("botWallet.refresh")}
          title={t("botWallet.refresh")}
          loading={loading}
          icon={<RefreshCw size={14} />}
          onClick={() => void refresh()}
        />
        {wallet && (
          <Button
            size="small"
            type="link"
            icon={<ExternalLink size={13} />}
            disabled={!identity(wallet)}
            loading={opening}
            onClick={() => {
              if (needsGrant) {
                setOpening(true);
                void onAuthorize(identity(wallet)!).finally(() =>
                  setOpening(false),
                );
              } else void recharge();
            }}
          >
            {t(needsGrant ? "botWallet.authorize" : "botWallet.recharge")}
          </Button>
        )}
      </div>
      {loadError && (
        <small role="alert">
          {t(wallet ? "botWallet.stale" : "botWallet.loadFailed")}
        </small>
      )}
      {wallet && !identity(wallet) && (
        <small>{t("botWallet.refreshRequired")}</small>
      )}
      {problem === "open" && (
        <small role="alert">{t("botWallet.openFailed")}</small>
      )}
      {needsGrant && <small>{t("botWallet.grantHint")}</small>}
      {reauthorized && !problem && (
        <small>{t("botWallet.authorizedHint")}</small>
      )}
    </div>
  );
}
