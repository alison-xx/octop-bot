import { useEffect, useRef, useState } from "react";
import { Alert, Button, Spin } from "antd";
import { ExternalLink, RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import {
  lynxceBotApi,
  type LynxceAttempt,
  type LynxceModel,
  type LynxceStatus,
} from "../../api/modules/lynxceBot";
import { apiErrorMessage, isNotFoundApiError } from "../../utils/apiError";
import WalletBalance from "./WalletBalance";
import LynxceRegistration from "./LynxceRegistration";
import styles from "./BotClientSettings.module.less";
import ModelSelect from "./ModelSelect";
import { signOutBotClient } from "./AccountMenu";
import { CreditsAmount, useRecharge } from "./CreditsWidgets";
import { useLynxceCredits } from "./useLynxceCredits";

function externalUrl(value: string) {
  try {
    const url = new URL(value);
    if (
      url.origin === "https://api.lynxce.cn" &&
      url.pathname === "/api/oauth/mcp/authorize" &&
      !url.username &&
      !url.password
    )
      return url.href;
  } catch {
    /* Invalid server response. */
  }
  return null;
}

function savedAttempt(key: string): LynxceAttempt | null {
  try {
    const item = JSON.parse(sessionStorage.getItem(key) || "null");
    return typeof item?.attempt_id === "string" &&
      externalUrl(item.authorization_url)
      ? item
      : null;
  } catch {
    return null;
  }
}

export default function LynxceAccount({
  owner,
  compact = false,
  status,
  statusError,
  onReload,
  onSaved,
  onSwitch,
}: {
  owner: string;
  compact?: boolean;
  status: LynxceStatus | null;
  statusError: string;
  onReload: () => void;
  onSaved: () => void;
  onSwitch?: () => Promise<void>;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const credits = useLynxceCredits();
  const { recharge, opening } = useRecharge();
  // Signed in to Lynxce on the start page: models and wallet come with that account.
  const viaAccount = credits.wallet?.source === "cloud";
  const key = "octop-bot:lynxce-login:" + owner;
  const [attempt, setAttempt] = useState<LynxceAttempt | null>(() =>
    savedAttempt(key),
  );
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [pollError, setPollError] = useState("");
  const [pollRevision, setPollRevision] = useState(0);
  const [models, setModels] = useState<LynxceModel[] | null>(null);
  const [modelError, setModelError] = useState("");
  const [choice, setChoice] = useState<string>();
  const [revision, setRevision] = useState(0);
  const mounted = useRef(false);
  const pendingId = useRef(attempt?.attempt_id);
  const rechargeAttempt = useRef<{ id: string; binding: string }>();
  const [resumeCheckout, setResumeCheckout] = useState<string>();
  const refreshed = useRef(onSaved);
  useEffect(() => {
    refreshed.current = onSaved;
  }, [onSaved]);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    if (!attempt) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll(id: string) {
      try {
        const reply = await lynxceBotApi.poll(id, controller.signal);
        if (controller.signal.aborted || pendingId.current !== id) return;
        if (reply.state === "pending") {
          timer = setTimeout(() => void poll(id), 1500);
          return;
        }
        sessionStorage.removeItem(key);
        pendingId.current = undefined;
        setAttempt(null);
        if (reply.state === "failed")
          setError(reply.detail || t("botClient.lynxce.authFailed"));
        else {
          setResumeCheckout(
            rechargeAttempt.current?.id === id
              ? rechargeAttempt.current.binding
              : undefined,
          );
          refreshed.current();
        }
        rechargeAttempt.current = undefined;
      } catch (e) {
        if (controller.signal.aborted || pendingId.current !== id) return;
        if (isNotFoundApiError(e)) {
          sessionStorage.removeItem(key);
          pendingId.current = undefined;
          setAttempt(null);
          setError(t("botClient.lynxce.expired"));
          refreshed.current();
        } else setPollError(apiErrorMessage(e, t("octopBot.failed"), t));
      }
    }
    setPollError("");
    void poll(attempt.attempt_id);
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [attempt, key, pollRevision, t]);

  useEffect(() => {
    if (!status?.connected || attempt || compact) return;
    let current = true;
    setModelError("");
    setModels(null);
    setChoice(undefined);
    lynxceBotApi.models().then(
      ({ models: rows }) => {
        if (!current) return;
        setModels(rows);
        setChoice(
          rows.find((m) => m.id === status.selected_model)?.id ??
            (rows.length === 1 ? rows[0].id : undefined),
        );
      },
      (e) => {
        if (current) setModelError(apiErrorMessage(e, t("octopBot.failed"), t));
      },
    );
    return () => {
      current = false;
    };
  }, [status, attempt, revision, compact, t]);

  const run = async (action: string, work: () => Promise<void>) => {
    if (busy) return;
    setBusy(action);
    setError("");
    try {
      await work();
    } catch (e) {
      if (mounted.current)
        setError(apiErrorMessage(e, t("octopBot.failed"), t));
    } finally {
      if (mounted.current) setBusy("");
    }
  };
  const login = (rechargeBinding?: string) =>
    run("login", async () => {
      const result = await lynxceBotApi.login();
      const url = externalUrl(result.authorization_url);
      if (!url) {
        await lynxceBotApi.cancel(result.attempt_id);
        throw new Error(t("botClient.lynxce.invalidLink"));
      }
      sessionStorage.setItem(key, JSON.stringify(result));
      if (!mounted.current) return;
      pendingId.current = result.attempt_id;
      rechargeAttempt.current = rechargeBinding
        ? { id: result.attempt_id, binding: rechargeBinding }
        : undefined;
      setPollError("");
      setAttempt(result);
      window.open(url, "_blank", "noopener,noreferrer");
    });
  const cancel = () =>
    run("cancel", async () => {
      if (!attempt) return;
      pendingId.current = undefined;
      try {
        await lynxceBotApi.cancel(attempt.attempt_id);
      } catch (e) {
        if (!isNotFoundApiError(e)) {
          pendingId.current = attempt.attempt_id;
          if (mounted.current) setPollRevision((n) => n + 1);
          throw e;
        }
      }
      sessionStorage.removeItem(key);
      if (mounted.current) {
        setPollError("");
        setAttempt(null);
        onReload();
      }
    });
  const loginButton = (
    <Button
      type="link"
      loading={busy === "login"}
      disabled={!!busy}
      onClick={() => void login()}
    >
      {t(
        status?.connected
          ? "botClient.lynxce.relogin"
          : "botClient.lynxce.login",
      )}
    </Button>
  );
  const wallet = viaAccount ? (
    <div className={styles.accountActions}>
      <CreditsAmount credits={credits} />
      <Button
        size="small"
        type="link"
        icon={<ExternalLink size={13} />}
        loading={opening}
        onClick={() => void recharge()}
      >
        {t("botCredits.recharge")}
      </Button>
    </div>
  ) : (
    <WalletBalance
      source="model"
      onAuthorize={login}
      resumeCheckout={resumeCheckout}
      onResumeHandled={() => setResumeCheckout(undefined)}
    />
  );
  return (
    <div className={styles.form} data-lynxce-account>
      {(error || statusError) && (
        <Alert
          type="error"
          showIcon
          message={error || statusError}
          action={
            statusError && (
              <Button onClick={onReload}>{t("octopBot.retry")}</Button>
            )
          }
        />
      )}
      {attempt ? (
        <>
          <Alert
            type="info"
            showIcon
            message={t("botClient.lynxce.pending")}
            description={t("botClient.lynxce.waitHint")}
          />
          {pollError && (
            <Alert
              type="error"
              showIcon
              message={pollError}
              action={
                <Button onClick={() => setPollRevision((n) => n + 1)}>
                  {t("octopBot.retry")}
                </Button>
              }
            />
          )}
          <div className={styles.accountActions}>
            <Button
              href={attempt.authorization_url}
              target="_blank"
              rel="noopener noreferrer"
              icon={<ExternalLink size={15} />}
            >
              {t("botClient.lynxce.reopen")}
            </Button>
            <Button
              type="text"
              loading={busy === "cancel"}
              onClick={() => void cancel()}
            >
              {t("botClient.lynxce.cancel")}
            </Button>
          </div>
        </>
      ) : !status ? (
        !statusError && <Spin />
      ) : !status.connected ? (
        <>
          <p>{t("botClient.account.signInHint")}</p>
          <Button
            type="primary"
            onClick={() => void signOutBotClient(owner, navigate)}
          >
            {t("botClient.account.signIn")}
          </Button>
          {loginButton}
        </>
      ) : compact ? (
        wallet
      ) : (
        <>
          <div className={styles.accountHeading}>
            <strong>{t("botClient.lynxce.connected")}</strong>
            <Button
              type="text"
              title={t("botClient.lynxce.refresh")}
              aria-label={t("botClient.lynxce.refresh")}
              icon={<RefreshCw size={14} />}
              onClick={() => setRevision((n) => n + 1)}
            />
          </div>
          {wallet}
          {modelError ? (
            <Alert
              type="error"
              showIcon
              message={modelError}
              action={
                <Button onClick={() => setRevision((n) => n + 1)}>
                  {t("octopBot.retry")}
                </Button>
              }
            />
          ) : models === null ? (
            <Spin />
          ) : models.length === 0 ? (
            <Alert type="info" showIcon message={t("botClient.lynxce.empty")} />
          ) : (
            <>
              <label htmlFor="lynxce-personal-model">
                {t("botClient.lynxce.choose")}
              </label>
              <ModelSelect
                id="lynxce-personal-model"
                value={choice}
                placeholder={t("botClient.lynxce.choose")}
                disabled={!!busy}
                onChange={setChoice}
                items={models.map((m) => ({
                  value: m.id,
                  id: m.id,
                  name: m.name,
                }))}
              />
              <Button
                type="primary"
                disabled={!!busy || !choice || choice === status.selected_model}
                loading={busy === "apply"}
                onClick={() =>
                  void run("apply", async () => {
                    if (choice) {
                      await lynxceBotApi.select(choice);
                      onSaved();
                    }
                  })
                }
              >
                {t(
                  choice && choice === status.selected_model
                    ? "botClient.lynxce.inUse"
                    : "botClient.lynxce.apply",
                )}
              </Button>
            </>
          )}
          <div className={styles.accountActions}>
            {!viaAccount && loginButton}
            {!viaAccount && (
              <Button
                type="link"
                disabled={!!busy}
                loading={busy === "logout"}
                onClick={() =>
                  void run("logout", async () => {
                    await lynxceBotApi.logout();
                    onSaved();
                  })
                }
              >
                {t("botClient.lynxce.logout")}
              </Button>
            )}
          </div>
        </>
      )}
      {!status?.connected && (status || attempt) && <LynxceRegistration />}
      {onSwitch && !attempt && !compact && (
        <Button
          disabled={!!busy}
          loading={busy === "switch"}
          onClick={() => void run("switch", onSwitch)}
        >
          {t("botClient.lynxce.useOther")}
        </Button>
      )}
    </div>
  );
}
