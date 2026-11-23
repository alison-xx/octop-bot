import { useEffect, useRef, useState } from "react";
import { Alert, Button, Input, Spin } from "antd";
import { ArrowRight } from "lucide-react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  authApi,
  invalidateAuthStatusCache,
  type AuthStatus,
} from "../../api/modules/auth";
import { botCloudApi } from "../../api/modules/botCloud";
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
import LynxceSignInForm from "./LynxceSignInForm";
import styles from "./index.module.less";
import intro from "./BotClientSetup.module.less";

type Busy = "lynxce" | "local" | "admin";

/** One silent device-session renewal per page load, so a refusing server cannot loop. */
let desktopRenewTried = false;

/**
 * Octop Bot start page: first run and sign-in for both Bot builds.
 *
 * Desktop: two ways in and no setup steps. "Lynxce" signs in to a Lynxce account (credits,
 * cloud computers) on top of the local owner; "local" uses this computer without signing in.
 * Both create the local owner silently on first run. Web: the Lynxce account is the only way in.
 */
export default function BotClientSetup() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const [search] = useSearchParams();
  const desktop = isDesktopShell();
  const [addLocalAccount, setAddLocalAccount] = useState(
    search.get("localAccount") === "1" && desktop,
  );
  const headingRef = useRef<HTMLHeadingElement>(null);
  const [status, setStatus] = useState<AuthStatus | null>(null);
  const [verified, setVerified] = useState(false);
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState<Busy | null>(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
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
        if (mounted) setError(apiErrorMessage(e, t("octopBot.failed"), t));
      });
    return () => {
      mounted = false;
    };
    // addLocalAccount is derived here on desktop; reading it once per load is enough.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [desktop, navigate, retry, t]);
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

  const firstRun = !!status && (status.setup_required || addLocalAccount);
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
      throw new Error(t("botOnboarding.localFailed"));
    }
    setAuthToken(issued.access_token, true);
    localReady.current = true;
  };

  const enterWithoutSignIn = async () => {
    if (!status || busy) return;
    setBusy("local");
    setError("");
    try {
      const fresh = firstRun;
      await enterLocal(status);
      navigate(fresh ? BOT_GUIDE : BOT_HOME, {
        replace: true,
        state: fresh ? { step: "team" } : undefined,
      });
    } catch (e) {
      setError(apiErrorMessage(e, t("octopBot.failed"), t));
    } finally {
      setBusy(null);
    }
  };

  /** Desktop: the Lynxce account rides on the local owner (wallet, models, cloud computers). */
  const signInDesktopLynxce = async (attempt: () => Promise<unknown>) => {
    if (!status || busy) return;
    setBusy("lynxce");
    setError("");
    try {
      const fresh = firstRun;
      await enterLocal(status);
      await attempt();
      navigate(fresh ? BOT_SETTINGS : BOT_HOME, {
        replace: true,
        state: fresh ? { source: "lynxce", from: BOT_GUIDE } : undefined,
      });
    } catch (e) {
      setError(apiErrorMessage(e, t("octopBot.failed"), t));
    } finally {
      setBusy(null);
    }
  };

  const signInWithLynxce = async (
    attempt: () => Promise<{ access_token: string }>,
  ) => {
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

  const workbuddyLogin = getDesktopBridge()?.workbuddyLogin;
  const desktopStart = (
    <div className={intro.webForms}>
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
        sendCode={async (target) => {
          // Lynxce account calls go through the local owner's session.
          if (status) await enterLocal(status);
          return (await botCloudApi.sendCode(target, locale)).channel;
        }}
        onCode={(target, code) =>
          signInDesktopLynxce(() => botCloudApi.codeLogin(target, code))
        }
        onPassword={(account, secret) =>
          signInDesktopLynxce(() => botCloudApi.login(account, secret))
        }
        onError={(e) => setError(apiErrorMessage(e, t("octopBot.failed"), t))}
        onClearError={() => setError("")}
      />
      {workbuddyLogin && (
        <Button
          size="large"
          disabled={!!busy}
          onClick={() =>
            void signInDesktopLynxce(async () => {
              const result = await workbuddyLogin();
              if (!result.ok) {
                throw new Error(
                  t(
                    result.reason === "denied"
                      ? "botCloud.workbuddyDenied"
                      : "botCloud.workbuddyFailed",
                  ),
                );
              }
              return botCloudApi.loginWorkbuddy(result.code);
            })
          }
        >
          {t("botCloud.workbuddySignIn")}
        </Button>
      )}
      <div className={intro.or} role="separator">
        <span>{t("botOnboarding.or")}</span>
      </div>
      <Button
        size="large"
        loading={busy === "local"}
        disabled={!!busy && busy !== "local"}
        onClick={() => void enterWithoutSignIn()}
      >
        {t("botOnboarding.useLocal")}
      </Button>
      <small className={intro.localHint}>
        {t("botOnboarding.useLocalHint")}
      </small>
    </div>
  );

  const webForms = (
    <div className={intro.webForms}>
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
        onCode={(target, code) =>
          signInWithLynxce(() => authApi.lynxceCodeLogin(target, code, locale))
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
        <aside className={intro.identity}>
          <BotCharacter
            look={{ ...octopCharacter, source: "character" }}
            size={108}
            badges={false}
          />
          <strong>{t("botOnboarding.chiefName")}</strong>
          <span>{t("botClient.profile.chief")}</span>
        </aside>
        <section className={intro.copy} aria-live="polite">
          <h1 ref={headingRef} tabIndex={-1}>
            {t(desktop ? "botOnboarding.startTitle" : "botClient.welcome")}
          </h1>
          <p>
            {t(
              desktop
                ? "botOnboarding.startBody"
                : status?.lynxce_login
                ? "botOnboarding.webBody"
                : "botOnboarding.desktopBody",
            )}
          </p>
          {error && <Alert type="error" message={error} showIcon />}
          {status ? (
            needsWizardPassword ? (
              <PasswordStep
                onVerified={() => {
                  setVerified(true);
                  setError("");
                }}
              />
            ) : status.lynxce_login ? (
              webForms
            ) : desktop ? (
              desktopStart
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
