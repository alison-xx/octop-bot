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
import styles from "./index.module.less";
import intro from "./BotClientSetup.module.less";

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
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
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
    if (ready) headingRef.current?.focus();
  }, [ready]);
  const start = async () => {
    if (!status || busy) return;
    setBusy(true);
    setError("");
    try {
      let jwt = wizardSession.loadSetupJwt();
      if (!jwt) {
        let token = wizardSession.loadToken();
        if (token && !(await wizardApi.validateToken(token)).valid) {
          wizardSession.clearToken();
          token = null;
        }
        if (!token && !status.wizard_password_required) {
          token = (await wizardApi.begin()).wizard_token;
          wizardSession.saveToken(token);
        }
        if (!token) {
          setVerified(false);
          throw new Error(t("wizard.sessionExpired"));
        }
        if (!status.database_bound) {
          await wizardApi.applyDatabase({
            driver: "sqlite",
            sqlite_path: "octop.db",
          });
          setStatus({ ...status, database_bound: true });
        }
        const created = await wizardApi.createAdmin(
          {
            username: "local",
            display_name: null,
            locale: i18n.language.startsWith("zh") ? "zh" : "en",
            ...(status.wizard_password_required ? { password } : {}),
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
        !status.wizard_password_required &&
        finishToken === jwt
      ) {
        finishToken = (await wizardApi.begin()).wizard_token;
        wizardSession.saveToken(finishToken);
      }
      await wizardApi.finish({ provider_draft: null }, finishToken ?? jwt);
      wizardSession.clearAll();
      setReady(true);
    } catch (e) {
      setError(apiErrorMessage(e, t("octopBot.failed"), t));
    } finally {
      setBusy(false);
    }
  };
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
          <strong>Chief</strong>
          <span>{t("botClient.profile.chief")}</span>
        </aside>
        <section className={intro.copy} aria-live="polite">
          <ol className={intro.steps} aria-label={t("wizard.title")}>
            <li aria-current={ready ? undefined : "step"}>
              {t("botClient.meet")}
            </li>
            <li aria-current={ready ? "step" : undefined}>
              {t("botClient.connectStep")}
            </li>
          </ol>
          <h1 ref={headingRef} tabIndex={-1}>
            {t(ready ? "botClient.nextTitle" : "botClient.welcome")}
          </h1>
          <p>{t(ready ? "botClient.nextBody" : "botClient.welcomeBody")}</p>
          {error && <Alert type="error" message={error} showIcon />}
          {ready ? (
            <div className={styles.introActions}>
              <Button
                type="primary"
                size="large"
                onClick={() =>
                  navigate(BOT_SETTINGS, {
                    replace: true,
                    state: { source: "lynxce", from: BOT_GUIDE },
                  })
                }
              >
                {t("botClient.lynxce.source")}
              </Button>
              <Button
                size="large"
                onClick={() =>
                  navigate(BOT_SETTINGS, {
                    replace: true,
                    state: { source: "other", from: BOT_GUIDE },
                  })
                }
              >
                {t("botClient.lynxce.other")}
              </Button>
              <Button
                type="text"
                size="large"
                onClick={() =>
                  navigate(BOT_GUIDE, {
                    replace: true,
                    state: { step: "team" },
                  })
                }
              >
                {t("botClient.later")}
              </Button>
            </div>
          ) : status ? (
            status.wizard_password_required &&
            !verified &&
            !wizardSession.loadSetupJwt() ? (
              <PasswordStep
                onVerified={() => {
                  setVerified(true);
                  setError("");
                }}
              />
            ) : (
              <form
                className={styles.introActions}
                onSubmit={(event) => {
                  event.preventDefault();
                  void start();
                }}
              >
                {status.wizard_password_required &&
                  !wizardSession.loadSetupJwt() && (
                    <div className={intro.password}>
                      <label htmlFor="bot-admin-password">
                        {t("wizard.admin.password")}
                      </label>
                      <Input.Password
                        id="bot-admin-password"
                        aria-describedby="bot-password-hint"
                        autoComplete="new-password"
                        autoFocus
                        required
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                      />
                      <small id="bot-password-hint">
                        {t("wizard.admin.passwordHint")}
                      </small>
                    </div>
                  )}
                <Button
                  type="primary"
                  size="large"
                  loading={busy}
                  disabled={
                    status.wizard_password_required &&
                    !wizardSession.loadSetupJwt() &&
                    !password
                  }
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
          {ready && <LynxceRegistration />}
        </section>
      </div>
    </main>
  );
}
