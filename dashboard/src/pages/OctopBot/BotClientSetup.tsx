import { useEffect, useRef, useState } from "react";
import { Alert, Button, Input, Spin } from "antd";
import { ArrowRight, ChevronRight, LockKeyhole } from "lucide-react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  authApi,
  invalidateAuthStatusCache,
  type AuthStatus,
} from "../../api/modules/auth";
import { ApiResponseError } from "../../api/responseError";
import {
  desktopLocalAutoLoginHeld,
  isLocalDesktopUser,
  releaseDesktopLocalAutoLogin,
  renewDesktopSession,
} from "../../api/desktopSession";
import { getAuthToken, setAuthToken } from "../../api/request";
import { BOT_GUIDE, BOT_HOME, BOT_SETTINGS } from "../../utils/botClientRoute";
import { apiErrorMessage } from "../../utils/apiError";
import { getDesktopBridge, isDesktopShell } from "../../utils/desktopBridge";
import {
  resolveSetupProbeToken,
  wizardApi,
  wizardSession,
} from "../Setup/wizardClient";
import PasswordStep from "../Setup/steps/PasswordStep";
import { BotCharacter, octopCharacter } from "./BotCharacter";
import BotStartHero from "./BotStartHero";
import lynxceLogo from "../../assets/providers/lynxce.png";
import LynxceSignInForm from "./LynxceSignInForm";
import ThirdPartySignIn from "./ThirdPartySignIn";
import styles from "./index.module.less";
import intro from "./BotClientSetup.module.less";

type Busy = "lynxce" | "local" | "admin";

/** One silent device-session renewal per page load, so a refusing server cannot loop. */
let desktopRenewTried = false;

/**
 * Octop Bot start page: first run and sign-in for both Bot builds.
 *
 * Hosted sign-in uses the cloud account directly. Only local mode creates or renews
 * the owner of this computer’s workspace.
 */
export default function BotClientSetup() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const workspaceChooser = useLocation().pathname === "/login/workspaces";
  const [search] = useSearchParams();
  const desktop = isDesktopShell();
  const [addLocalAccount, setAddLocalAccount] = useState(
    search.get("localAccount") === "1" && desktop,
  );
  const headingRef = useRef<HTMLHeadingElement>(null);
  const [status, setStatus] = useState<AuthStatus | null>(null);
  const [verified, setVerified] = useState(false);
  const [verifyLocalSetup, setVerifyLocalSetup] = useState(false);
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState<Busy | null>(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const [wechatBind, setWechatBind] = useState("");
  const [wechatPhone, setWechatPhone] = useState("");
  const [wechatCode, setWechatCode] = useState("");
  const [wechatWait, setWechatWait] = useState(0);
  useEffect(() => {
    if (!wechatWait) return;
    const timer = window.setTimeout(
      () => setWechatWait((value) => value - 1),
      1000,
    );
    return () => window.clearTimeout(timer);
  }, [wechatWait]);

  const locale = i18n.language.startsWith("zh") ? "zh" : "en";
  useEffect(() => {
    let mounted = true;
    authApi
      .getAuthStatus()
      .then(async (s) => {
        if (!mounted) return;
        const jwt = wizardSession.loadSetupJwt();
        if (desktop && !s.setup_required && !jwt) {
          // Signed out, or the device credential is gone: this page is the way back in.
          if (
            s.local_account &&
            !workspaceChooser &&
            !desktopLocalAutoLoginHeld() &&
            !desktopRenewTried
          ) {
            desktopRenewTried = true;
            const issued = await renewDesktopSession();
            if (!mounted) return;
            if (
              issued?.access_token &&
              isLocalDesktopUser(issued.access_token)
            ) {
              setAuthToken(issued.access_token, true);
              navigate(BOT_HOME, { replace: true });
              return;
            }
          }
          setAddLocalAccount(!s.local_account);
        } else if (
          !s.setup_required &&
          !jwt &&
          !(addLocalAccount && !s.local_account)
        ) {
          navigate(getAuthToken() ? BOT_HOME : "/login", { replace: true });
          return;
        }
        const token = wizardSession.loadToken();
        if (s.wizard_password_required && !jwt && token) {
          const { valid } = await wizardApi.validateToken(token);
          if (!mounted) return;
          if (!valid) wizardSession.clearToken();
          setVerified(valid);
        }
        setStatus(s);
      })
      .catch((e) => {
        if (mounted && !desktop)
          setError(apiErrorMessage(e, t("octopBot.failed"), t));
      });
    return () => {
      mounted = false;
    };
    // addLocalAccount is derived here on desktop; reading it once per load is enough.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [desktop, navigate, retry, t, workspaceChooser]);
  useEffect(() => {
    if (status) headingRef.current?.focus();
  }, [status]);

  const wizardToken = async (current: AuthStatus): Promise<string> => {
    let token = wizardSession.loadToken();
    if (token && !(await wizardApi.validateToken(token)).valid) {
      wizardSession.clearToken();
      token = null;
    }
    if (!token && !current.wizard_password_required) {
      token = (await wizardApi.begin()).wizard_token;
      wizardSession.saveToken(token);
    }
    if (!token) {
      setVerified(false);
      throw new Error(t("wizard.sessionExpired"));
    }
    return token;
  };

  /** A fresh install binds local SQLite; the route is open until setup ends. */
  const bindDatabase = async (current: AuthStatus) => {
    if (current.database_bound) return;
    await wizardApi.applyDatabase({
      driver: "sqlite",
      sqlite_path: "octop.db",
    });
    setStatus({ ...current, database_bound: true });
  };

  /** Create the local owner (no password on desktop) and close setup. */
  const createLocalOwner = async (current: AuthStatus) => {
    let jwt = wizardSession.loadSetupJwt();
    if (!jwt) {
      const token = await wizardToken(current);
      await bindDatabase(current);
      const created = await wizardApi.createAdmin(
        {
          username: "local",
          display_name: null,
          locale,
          ...(current.wizard_password_required || current.lynxce_login
            ? { password }
            : {}),
        },
        token,
      );
      jwt = created.access_token;
      wizardSession.saveSetupJwt(jwt);
      setAuthToken(jwt);
      invalidateAuthStatusCache();
    }
    let finishToken = await resolveSetupProbeToken();
    // After adding 'local' beside an existing account, finish requires the
    // desktop wizard token. A regular admin JWT only works for the first user.
    if (
      addLocalAccount &&
      !current.wizard_password_required &&
      finishToken === jwt
    ) {
      finishToken = (await wizardApi.begin()).wizard_token;
      wizardSession.saveToken(finishToken);
    }
    await wizardApi.finish({ provider_draft: null }, finishToken ?? jwt);
    wizardSession.clearAll();
  };

  // Set once the local owner is signed in here, so a retry or a second step never recreates it.
  const localReady = useRef(false);

  /** Desktop: make sure the local owner exists and is signed in on this device. */
  const enterLocal = async (current: AuthStatus) => {
    if (localReady.current) return;
    if (current.setup_required || addLocalAccount || !current.local_account) {
      await createLocalOwner(current);
      localReady.current = true;
      return;
    }
    releaseDesktopLocalAutoLogin();
    const issued = await renewDesktopSession();
    if (!issued?.access_token || !isLocalDesktopUser(issued.access_token)) {
      navigate("/login/local", { replace: true });
      return false;
    }
    setAuthToken(issued.access_token, true);
    localReady.current = true;
  };

  const enterWithoutSignIn = async () => {
    if (busy) return;
    setBusy("local");
    setError("");
    try {
      const current = status ?? (await authApi.getAuthStatus());
      if (
        current.wizard_password_required &&
        !verified &&
        !wizardSession.loadSetupJwt()
      ) {
        setStatus(current);
        setVerifyLocalSetup(true);
        return;
      }
      const fresh = current.setup_required || !current.local_account;
      if ((await enterLocal(current)) === false) return;
      // A fresh install picks its models first (local or its own API keys), then meets the team.
      navigate(fresh ? BOT_SETTINGS : BOT_HOME, {
        replace: true,
        state: fresh ? { from: BOT_GUIDE } : undefined,
      });
    } catch (e) {
      setError(apiErrorMessage(e, t("octopBot.failed"), t));
    } finally {
      setBusy(null);
    }
  };

  const bridge = getDesktopBridge();
  type CloudMethod = Parameters<
    NonNullable<NonNullable<typeof bridge>["workspaceLogin"]>
  >[0];
  async function cloudRequest(
    method: CloudMethod,
    body: Record<string, string>,
  ) {
    if (!bridge?.workspaceLogin)
      throw new Error(t("botOnboarding.loginUnavailable"));
    const { status: httpStatus, data } = await bridge.workspaceLogin(method, {
      ...body,
      locale,
    });
    if (httpStatus !== 200)
      throw new ApiResponseError(httpStatus, data?.error ?? null, null);
    return data;
  }
  async function sendCloudCode(target: string) {
    const { channel } = await cloudRequest("sendCode", { target });
    if (!channel) throw new Error(t("octopBot.failed"));
    return channel;
  }
  async function signInDesktopLynxce(
    method: CloudMethod,
    body: Record<string, string> = {},
  ) {
    if (busy) return;
    setBusy("lynxce");
    setError("");
    try {
      const result = await cloudRequest(method, body);
      if (result.cancelled) return;
      if (result.bind_token) {
        setWechatBind(result.bind_token);
        return;
      }
      if (
        !result.access_token ||
        !(await bridge?.useLynxceCloud?.(result.access_token))
      )
        throw new Error(t("botOnboarding.loginUnavailable"));
    } catch (e) {
      setError(apiErrorMessage(e, t("octopBot.failed"), t));
      return e;
    } finally {
      setBusy(null);
    }
  }

  const signInWithLynxce = async (
    attempt: () => Promise<{ access_token: string }>,
  ): Promise<unknown> => {
    if (!status || busy) return;
    setBusy("lynxce");
    setError("");
    try {
      await bindDatabase(status);
      const session = await attempt();
      setAuthToken(session.access_token);
      wizardSession.clearAll();
      // Lynxce's model authorization needs the desktop client; on the web
      // build the owner connects a model provider next.
      navigate(BOT_SETTINGS, {
        replace: true,
        state: { source: "other", from: BOT_GUIDE },
      });
    } catch (e) {
      setError(apiErrorMessage(e, t("octopBot.failed"), t));
      return e;
    } finally {
      setBusy(null);
    }
  };

  /** A web build without Lynxce sign-in still needs its owner's password. */
  const createAdminWithPassword = async () => {
    if (!status || busy) return;
    setBusy("admin");
    setError("");
    try {
      await createLocalOwner(status);
      navigate(BOT_SETTINGS, {
        replace: true,
        state: { source: "other", from: BOT_GUIDE },
      });
    } catch (e) {
      setError(apiErrorMessage(e, t("octopBot.failed"), t));
    } finally {
      setBusy(null);
    }
  };

  const needsWizardPassword =
    !!status?.wizard_password_required &&
    !verified &&
    !wizardSession.loadSetupJwt();

  const lynxceHead = (
    <div className={intro.cardHead}>
      <img src={lynxceLogo} alt="" />
      <span id="bot-start-lynxce">{t("botStart.lynxceAccount")}</span>
      <span className={intro.recommend}>{t("botStart.recommended")}</span>
    </div>
  );
  const desktopStart = (
    <div className={intro.webForms}>
      <section className={intro.lynxceCard} aria-labelledby="bot-start-lynxce">
        {lynxceHead}
        <LynxceSignInForm
          idPrefix="bot-start"
          autoFocus
          busy={busy === "lynxce"}
          submitLabel={
            <>
              {t("botOnboarding.lynxceStart")}
              <ArrowRight size={16} aria-hidden="true" />
            </>
          }
          passwordHint={t("botOnboarding.lynxceHint")}
          sendCode={sendCloudCode}
          onCode={(target, code, password) =>
            signInDesktopLynxce("code", {
              target,
              code,
              ...(password ? { password } : {}),
            })
          }
          onPassword={(account, password) =>
            signInDesktopLynxce("password", { account, password })
          }
          onError={(e) => setError(apiErrorMessage(e, t("octopBot.failed"), t))}
          onClearError={() => setError("")}
        />
        <ThirdPartySignIn
          disabled={!!busy}
          onWechat={
            bridge?.workspaceLogin && (() => void signInDesktopLynxce("wechat"))
          }
          onWorkbuddy={
            bridge?.workspaceLogin &&
            (() => void signInDesktopLynxce("workbuddy"))
          }
        />
      </section>
      <button
        type="button"
        className={intro.localOption}
        disabled={!!busy}
        aria-busy={busy === "local"}
        aria-labelledby="bot-start-local"
        aria-describedby="bot-start-local-hint"
        onClick={() => void enterWithoutSignIn()}
      >
        <span className={intro.localIcon} aria-hidden="true">
          {busy === "local" ? <Spin size="small" /> : <LockKeyhole size={18} />}
        </span>
        <span>
          <strong id="bot-start-local">{t("botOnboarding.useLocal")}</strong>
          <small id="bot-start-local-hint">
            {t("botOnboarding.useLocalHint")}
          </small>
        </span>
        <ChevronRight size={18} aria-hidden="true" />
      </button>
    </div>
  );

  const webForms = (
    <div className={`${intro.webForms} ${intro.lynxceCard}`}>
      {lynxceHead}
      <LynxceSignInForm
        idPrefix="bot-lynxce"
        autoFocus
        busy={busy === "lynxce"}
        submitLabel={
          <>
            {t("botOnboarding.lynxceSubmit")}
            <ArrowRight size={16} aria-hidden="true" />
          </>
        }
        passwordHint={t("botOnboarding.lynxceHint")}
        sendCode={async (target) => {
          if (status) await bindDatabase(status);
          return (await authApi.lynxceSendCode(target, locale)).channel;
        }}
        onCode={(target, code, password) =>
          signInWithLynxce(() =>
            authApi.lynxceCodeLogin(target, code, locale, undefined, password),
          )
        }
        onPassword={(account, secret) =>
          signInWithLynxce(() => authApi.lynxceLogin(account, secret, locale))
        }
        onError={(e) => setError(apiErrorMessage(e, t("octopBot.failed"), t))}
        onClearError={() => setError("")}
      />
    </div>
  );

  return (
    <main className={intro.window} data-bot-onboarding>
      <header className={intro.brand}>
        <BotCharacter
          look={{ ...octopCharacter, source: "character" }}
          size={25}
          badges={false}
        />
        <span>Octop Bot</span>
      </header>
      <div className={intro.welcome}>
        <BotStartHero />
        <section className={intro.copy} aria-live="polite">
          {wechatBind && (
            <button
              type="button"
              onClick={() => {
                setWechatBind("");
                setWechatCode("");
                setWechatPhone("");
                setWechatWait(0);
                setError("");
              }}
            >
              {t("botCloud.wechatBack")}
            </button>
          )}
          <h1 ref={headingRef} tabIndex={-1}>
            {wechatBind
              ? t("botCloud.wechatBindTitle")
              : t(desktop ? "botOnboarding.startTitle" : "botClient.welcome")}
          </h1>
          <p>
            {t(
              wechatBind
                ? "botCloud.wechatBindBody"
                : desktop
                ? "botOnboarding.startBody"
                : status?.lynxce_login
                ? "botOnboarding.webBody"
                : "botOnboarding.desktopBody",
            )}
          </p>
          {error && <Alert type="error" message={error} showIcon />}
          {desktop || status ? (
            wechatBind ? (
              <form
                className={intro.wechatBind}
                onSubmit={(event) => {
                  event.preventDefault();
                  void signInDesktopLynxce("bind", {
                    bind_token: wechatBind,
                    phone: wechatPhone,
                    code: wechatCode,
                  });
                }}
              >
                <Input
                  aria-label={t("botCloud.wechatPhone")}
                  size="large"
                  inputMode="tel"
                  autoComplete="tel"
                  placeholder={t("botCloud.wechatPhone")}
                  value={wechatPhone}
                  onChange={(e) => setWechatPhone(e.target.value)}
                />
                <Input
                  aria-label={t("lynxceSignIn.code")}
                  size="large"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  maxLength={6}
                  placeholder={t("lynxceSignIn.codePlaceholder")}
                  value={wechatCode}
                  onChange={(e) => setWechatCode(e.target.value)}
                  suffix={
                    <Button
                      type="link"
                      disabled={!!busy || wechatWait > 0 || !wechatPhone.trim()}
                      onClick={() => {
                        void sendCloudCode(wechatPhone)
                          .then(() => setWechatWait(60))
                          .catch((e) =>
                            setError(
                              apiErrorMessage(e, t("octopBot.failed"), t),
                            ),
                          );
                      }}
                    >
                      {wechatWait
                        ? t("lynxceSignIn.resendIn", { seconds: wechatWait })
                        : t("lynxceSignIn.send")}
                    </Button>
                  }
                />
                <small>{t("botCloud.wechatExpires")}</small>
                <Button
                  type="primary"
                  size="large"
                  htmlType="submit"
                  loading={busy === "lynxce"}
                  disabled={!wechatPhone.trim() || !wechatCode.trim()}
                >
                  {t("botCloud.wechatSubmit")}
                </Button>
              </form>
            ) : desktop &&
              !status?.lynxce_login &&
              !(needsWizardPassword && verifyLocalSetup) ? (
              desktopStart
            ) : needsWizardPassword ? (
              <PasswordStep
                onVerified={() => {
                  setVerified(true);
                  setError("");
                }}
              />
            ) : status?.lynxce_login ? (
              webForms
            ) : (
              <form
                className={styles.introActions}
                onSubmit={(event) => {
                  event.preventDefault();
                  void createAdminWithPassword();
                }}
              >
                <div className={intro.password}>
                  <label htmlFor="bot-admin-password">
                    {t("wizard.admin.password")}
                  </label>
                  <Input.Password
                    id="bot-admin-password"
                    autoComplete="new-password"
                    autoFocus
                    required
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                  />
                  <small>{t("wizard.admin.passwordHint")}</small>
                </div>
                <Button
                  type="primary"
                  size="large"
                  loading={!!busy}
                  disabled={!password}
                  htmlType="submit"
                >
                  {t("botClient.begin")}
                  <ArrowRight size={16} />
                </Button>
              </form>
            )
          ) : error ? (
            <Button
              onClick={() => {
                setError("");
                setRetry((n) => n + 1);
              }}
            >
              {t("octopBot.retry")}
            </Button>
          ) : (
            <Spin />
          )}
        </section>
      </div>
    </main>
  );
}
