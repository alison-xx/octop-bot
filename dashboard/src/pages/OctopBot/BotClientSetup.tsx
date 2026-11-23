import { useEffect, useRef, useState } from "react";
import { Alert, Button, Input, Segmented, Spin } from "antd";
import { ArrowRight } from "lucide-react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  authApi,
  invalidateAuthStatusCache,
  type AuthStatus,
} from "../../api/modules/auth";
import { getAuthToken, setAuthToken } from "../../api/request";
import { BOT_GUIDE, BOT_HOME, BOT_SETTINGS } from "../../utils/botClientRoute";
import { apiErrorMessage } from "../../utils/apiError";
import { isDesktopShell } from "../../utils/desktopBridge";
import {
  resolveSetupProbeToken,
  wizardApi,
  wizardSession,
} from "../Setup/wizardClient";
import PasswordStep from "../Setup/steps/PasswordStep";
import { BotCharacter, octopCharacter } from "./BotCharacter";
import LynxceRegistration from "./LynxceRegistration";
import LynxceSignInForm from "./LynxceSignInForm";
import styles from "./index.module.less";
import intro from "./BotClientSetup.module.less";

type Choice = "lynxce" | "other" | "later";
type WebMode = "lynxce" | "local";

export default function BotClientSetup() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const [search] = useSearchParams();
  const addLocalAccount =
    search.get("localAccount") === "1" && isDesktopShell();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const [status, setStatus] = useState<AuthStatus | null>(null);
  const [verified, setVerified] = useState(false);
  const [password, setPassword] = useState("");
  const [webMode, setWebMode] = useState<WebMode>("lynxce");
  const [busy, setBusy] = useState<Choice | WebMode | null>(null);
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
        if (
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
  }, [addLocalAccount, navigate, retry, t]);
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

  const proceed = (choice: Choice) => {
    if (choice === "later") {
      navigate(BOT_GUIDE, { replace: true, state: { step: "team" } });
      return;
    }
    navigate(BOT_SETTINGS, {
      replace: true,
      state: { source: choice, from: BOT_GUIDE },
    });
  };

  const choose = async (choice: Choice) => {
    if (!status || busy) return;
    setBusy(choice);
    setError("");
    try {
      await createLocalOwner(status);
      proceed(choice);
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
      proceed("other");
    } catch (e) {
      setError(apiErrorMessage(e, t("octopBot.failed"), t));
    } finally {
      setBusy(null);
    }
  };

  const createWebOwner = async () => {
    if (!status || busy) return;
    setBusy("local");
    setError("");
    try {
      await createLocalOwner(status);
      proceed("other");
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

  const desktopChoices = (
    <div className={intro.choices}>
      <Button
        type="primary"
        size="large"
        loading={busy === "lynxce"}
        disabled={!!busy && busy !== "lynxce"}
        onClick={() => void choose("lynxce")}
      >
        {t("botClient.lynxce.source")}
        <ArrowRight size={16} aria-hidden="true" />
      </Button>
      <Button
        size="large"
        loading={busy === "other"}
        disabled={!!busy && busy !== "other"}
        onClick={() => void choose("other")}
      >
        {t("botClient.lynxce.other")}
      </Button>
      <Button
        type="text"
        size="large"
        loading={busy === "later"}
        disabled={!!busy && busy !== "later"}
        onClick={() => void choose("later")}
      >
        {t("botClient.later")}
      </Button>
    </div>
  );

  const webForms = (
    <div className={intro.webForms}>
      <Segmented<WebMode>
        block
        value={webMode}
        onChange={(value) => {
          setWebMode(value);
          setError("");
        }}
        options={[
          { value: "lynxce", label: t("botOnboarding.lynxceTab") },
          { value: "local", label: t("botOnboarding.localTab") },
        ]}
      />
      {webMode === "lynxce" ? (
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
            signInWithLynxce(() =>
              authApi.lynxceCodeLogin(target, code, locale),
            )
          }
          onPassword={(account, password) =>
            signInWithLynxce(() =>
              authApi.lynxceLogin(account, password, locale),
            )
          }
          onError={(e) => setError(apiErrorMessage(e, t("octopBot.failed"), t))}
          onClearError={() => setError("")}
        />
      ) : (
        <form
          className={intro.form}
          onSubmit={(event) => {
            event.preventDefault();
            void createWebOwner();
          }}
        >
          <label htmlFor="bot-local-password">
            {t("botOnboarding.localPassword")}
          </label>
          <Input.Password
            id="bot-local-password"
            autoComplete="new-password"
            autoFocus
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <small>{t("botOnboarding.localHint")}</small>
          <Button
            type="primary"
            size="large"
            htmlType="submit"
            loading={busy === "local"}
            disabled={!password}
          >
            {t("botOnboarding.localSubmit")}
            <ArrowRight size={16} aria-hidden="true" />
          </Button>
        </form>
      )}
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
            {t("botClient.welcome")}
          </h1>
          <p>
            {t(
              status?.lynxce_login
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
            ) : status.wizard_password_required ? (
              <form
                className={styles.introActions}
                onSubmit={(event) => {
                  event.preventDefault();
                  void choose("other");
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
            ) : status.lynxce_login ? (
              webForms
            ) : (
              <>
                {desktopChoices}
                <LynxceRegistration />
              </>
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
