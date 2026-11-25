import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Button, Input } from "antd";
import { useTranslation } from "react-i18next";
import {
  botWebLogin,
  CLOUD_LOGIN,
  type Provider,
} from "../../api/modules/botWebLogin";
import { authApi } from "../../api/modules/auth";
import ThirdPartySignIn from "./ThirdPartySignIn";
import styles from "./BotLogin.module.less";

const KEY = "octop.cloud.web.login.v1";
type Callback = { provider: Provider; state: string; code: string };
type Result = { access_token: string } | { bind_token: string };

function takeCallback(): Callback | "cancelled" | "expired" | null {
  const params = new URLSearchParams(location.hash.slice(1));
  const provider = params.get("provider");
  if (!provider) {
    if (!sessionStorage.getItem(KEY)) return null;
    sessionStorage.removeItem(KEY);
    return "cancelled";
  }
  history.replaceState(history.state, "", location.pathname);
  const saved = sessionStorage.getItem(KEY);
  sessionStorage.removeItem(KEY);
  if (!saved || (provider !== "wechat" && provider !== "workbuddy"))
    return "expired";
  try {
    const attempt = JSON.parse(saved);
    const age = Date.now() - attempt.time;
    if (
      attempt.provider !== provider ||
      !attempt.state ||
      !Number.isFinite(age) ||
      age < 0 ||
      age > 600000 ||
      (provider === "wechat" &&
        params.get("state") !== (attempt.callbackState ?? attempt.state))
    )
      return "expired";
    if (params.has("error"))
      return ["authorize_denied", "access_denied"].includes(
        params.get("error")!,
      )
        ? "cancelled"
        : "expired";
    const code = params.get("code");
    return code ? { provider, code, state: attempt.state } : "expired";
  } catch {
    return "expired";
  }
}

export function useBotLoginSocial(
  cloud: boolean,
  locale: string,
  signedIn: (token: string) => void,
  formBusy: boolean,
) {
  const { t } = useTranslation();
  const [waiting, setWaiting] = useState(false);
  const [bindToken, setBindToken] = useState("");
  const [message, setMessage] = useState("");
  const [available, setAvailable] = useState<
    Partial<Record<Provider, boolean>>
  >({});
  const startRequest = useRef<AbortController | null>(null);
  useLayoutEffect(() => () => startRequest.current?.abort(), []);
  const finish = useRef(signedIn);
  finish.current = signedIn;
  const callback = useRef<Promise<Result> | null>(null);
  useEffect(() => {
    if (
      !cloud ||
      (location.origin !== new URL(CLOUD_LOGIN).origin && !import.meta.env.DEV)
    )
      return;
    let active = true;
    for (const provider of ["wechat", "workbuddy"] as const) {
      void botWebLogin
        .config(provider)
        .then((config) => config.enabled)
        .catch(() => false)
        .then((ok) => {
          if (active)
            setAvailable((previous) => ({ ...previous, [provider]: ok }));
        });
    }
    // The fragment stays out of server logs. A replay or a callback in another tab cannot
    // spend this tab's saved attempt. Keep one promise across React StrictMode effect replay.
    const result = callback.current ? null : takeCallback();
    if (result === "cancelled" || result === "expired") setMessage(result);
    else if (result) {
      callback.current = botWebLogin.exchange(
        result.provider,
        result.code,
        result.state,
        locale,
      );
    }
    const pending = callback.current;
    if (pending) {
      setWaiting(true);
      void pending
        .then((outcome) => {
          if (!active) return;
          if ("bind_token" in outcome) setBindToken(outcome.bind_token);
          else finish.current(outcome.access_token);
        })
        .catch(() => {
          if (active) setMessage("expired");
        })
        .finally(() => {
          if (active) {
            callback.current = null;
            setWaiting(false);
          }
        });
    }
    function onBack(event: PageTransitionEvent) {
      if (event.persisted) {
        sessionStorage.removeItem(KEY);
        setWaiting(false);
        setMessage("cancelled");
      }
    }
    window.addEventListener("pageshow", onBack);
    return () => {
      active = false;
      startRequest.current?.abort();
      window.removeEventListener("pageshow", onBack);
    };
  }, [cloud, locale]);

  async function start(provider: Provider) {
    startRequest.current?.abort();
    const request = new AbortController();
    startRequest.current = request;
    setMessage("");
    setWaiting(true);
    try {
      const { enabled, url, state } = await botWebLogin.config(
        provider,
        request.signal,
      );
      if (request.signal.aborted) return;
      if (!enabled || !state || !url) throw new Error("Provider unavailable");
      sessionStorage.setItem(
        KEY,
        JSON.stringify({
          provider,
          state,
          time: Date.now(),
          // WeChat echoes its QR state. Its one-time exchange requires a separate
          // proof that only this originating tab received in the config response.
          callbackState:
            provider === "wechat"
              ? new URL(url).searchParams.get("state")
              : undefined,
        }),
      );
      window.location.assign(url);
    } catch {
      if (request.signal.aborted) return;
      setMessage("unavailable");
      setWaiting(false);
    }
  }
  const buttons = (
    <ThirdPartySignIn
      disabled={waiting || formBusy}
      wechatStatus={
        available.wechat
          ? undefined
          : t(
              available.wechat === undefined
                ? "botWebLogin.checking"
                : "botWebLogin.notReady",
            )
      }
      workbuddyStatus={
        available.workbuddy
          ? undefined
          : t(
              available.workbuddy === undefined
                ? "botWebLogin.checking"
                : "botWebLogin.notReady",
            )
      }
      onWechat={() => void start("wechat")}
      onWorkbuddy={() => void start("workbuddy")}
    />
  );
  return {
    buttons,
    waiting,
    bindToken,
    notice: message && t("botWebLogin." + message),
    clear: () => {
      setMessage("");
      sessionStorage.removeItem(KEY);
    },
    cancelBind: () => {
      setBindToken("");
      setMessage("cancelled");
    },
  };
}

export function BotLoginBind({
  token,
  locale,
  onDone,
  onBack,
}: {
  token: string;
  locale: string;
  onDone: (token: string) => void;
  onBack: () => void;
}) {
  const { t } = useTranslation();
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [wait, setWait] = useState(0);
  const [message, setMessage] = useState("");
  useEffect(() => {
    if (!wait) return;
    const timer = window.setTimeout(() => setWait(wait - 1), 1000);
    return () => clearTimeout(timer);
  }, [wait]);
  async function send() {
    setBusy(true);
    setMessage("");
    try {
      await authApi.lynxceSendCode(phone, locale);
      setWait(60);
      setMessage(t("lynxceSignIn.sentPhone"));
    } catch {
      setMessage(t("botWebLogin.sendFailed"));
    } finally {
      setBusy(false);
    }
  }
  return (
    <form
      className={styles.bind}
      onSubmit={async (e) => {
        e.preventDefault();
        if (busy) return;
        setBusy(true);
        setMessage("");
        try {
          const grant = await botWebLogin.bind(token, phone, code, locale);
          onDone(grant.access_token);
        } catch {
          setMessage(t("botWebLogin.bindFailed"));
        } finally {
          setBusy(false);
        }
      }}
    >
      <label htmlFor="bind-phone">{t("botCloud.wechatPhone")}</label>
      <Input
        id="bind-phone"
        type="tel"
        autoComplete="tel"
        required
        maxLength={24}
        value={phone}
        onChange={(e) => {
          setPhone(e.target.value);
          setCode("");
        }}
      />
      <label htmlFor="bind-code">{t("lynxceSignIn.code")}</label>
      <Input
        id="bind-code"
        inputMode="numeric"
        autoComplete="one-time-code"
        required
        pattern="[0-9]{6}"
        maxLength={6}
        value={code}
        onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
        suffix={
          <Button
            type="link"
            disabled={busy || !!wait || !/^\+?[0-9][0-9 -]{5,22}$/.test(phone)}
            onClick={() => void send()}
          >
            {wait
              ? t("lynxceSignIn.resendIn", { seconds: wait })
              : t("lynxceSignIn.send")}
          </Button>
        }
      />
      <div role="status">{message}</div>
      <Button type="primary" htmlType="submit" loading={busy}>
        {t("botCloud.wechatSubmit")}
      </Button>
      <Button type="text" disabled={busy} onClick={onBack}>
        {t("botCloud.wechatBack")}
      </Button>
    </form>
  );
}
