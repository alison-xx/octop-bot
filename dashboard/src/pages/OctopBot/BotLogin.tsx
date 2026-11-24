import { useEffect, useState } from "react";
import { Alert, Input, Spin } from "antd";
import { ArrowRight } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { authApi } from "../../api/modules/auth";
import { setAuthToken } from "../../api/request";
import { BOT_HOME } from "../../utils/botClientRoute";
import { apiErrorMessage } from "../../utils/apiError";
import { BotCharacter, octopCharacter } from "./BotCharacter";
import BotStartHero from "./BotStartHero";
import LynxceSignInForm from "./LynxceSignInForm";
import intro from "./BotClientSetup.module.less";

type Mode = "loading" | "lynxce" | "unavailable";

/**
 * Bot web build sign-in: Lynxce accounts only. An instance set up earlier with a local
 * password asks for that password once, to bind the Lynxce account to its owner.
 */
export default function BotLogin() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const [mode, setMode] = useState<Mode>("loading");
  const [legacyPassword, setLegacyPassword] = useState("");
  const [legacy, setLegacy] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // Octop Bot cloud: every Lynxce account signs in to an account of its own.
  const [cloud, setCloud] = useState(false);
  useEffect(() => {
    let mounted = true;
    Promise.all([authApi.getAuthStatus(), authApi.getLynxceIdentityStatus()])
      .then(([status, lynxce]) => {
        if (!mounted) return;
        if (status.setup_required) {
          navigate("/setup", { replace: true });
          return;
        }
        setCloud(lynxce.cloud === true);
        setLegacy(lynxce.legacy_owner === true);
        setMode(lynxce.enabled ? "lynxce" : "unavailable");
      })
      .catch(() => mounted && setMode("unavailable"));
    return () => {
      mounted = false;
    };
  }, [navigate]);

  const locale = i18n.language.startsWith("zh") ? "zh" : "en";
  /** Resolves with the error when sign-in failed (shown here, inspected by the form). */
  const lynxceSignIn = async (
    attempt: () => Promise<{ access_token: string }>,
  ): Promise<unknown> => {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      setAuthToken((await attempt()).access_token);
      navigate(BOT_HOME, { replace: true });
    } catch (e) {
      setError(apiErrorMessage(e, t("octopBot.failed"), t));
      return e;
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
        <BotStartHero />
        <section className={intro.copy} aria-live="polite">
          <h1>{t("botOnboarding.loginTitle")}</h1>
          {mode === "loading" ? (
            <Spin />
          ) : (
            <>
              <p>
                {t(
                  mode !== "lynxce"
                    ? "botOnboarding.loginUnavailable"
                    : cloud
                    ? "botOnboarding.loginCloudBody"
                    : legacy
                    ? "botOnboarding.loginLegacyBody"
                    : "botOnboarding.loginLynxceBody",
                )}
              </p>
              {error && <Alert type="error" message={error} showIcon />}
              {mode === "lynxce" && (
                <div className={`${intro.webForms} ${intro.lynxceCard}`}>
                  {legacy && (
                    <div className={intro.form}>
                      <label htmlFor="bot-login-legacy">
                        {t("botOnboarding.legacyPassword")}
                      </label>
                      <Input.Password
                        id="bot-login-legacy"
                        autoComplete="current-password"
                        value={legacyPassword}
                        onChange={(e) => setLegacyPassword(e.target.value)}
                      />
                    </div>
                  )}
                  <LynxceSignInForm
                    idPrefix="bot-login"
                    autoFocus
                    busy={busy}
                    submitLabel={
                      <>
                        {t("botOnboarding.loginTitle")}
                        <ArrowRight size={16} aria-hidden="true" />
                      </>
                    }
                    passwordHint={t("botOnboarding.lynxceHint")}
                    sendCode={async (target) =>
                      (await authApi.lynxceSendCode(target, locale)).channel
                    }
                    onCode={(target, code, password) =>
                      lynxceSignIn(() =>
                        authApi.lynxceCodeLogin(
                          target,
                          code,
                          locale,
                          legacyPassword,
                          password,
                        ),
                      )
                    }
                    onPassword={(account, password) =>
                      lynxceSignIn(() =>
                        authApi.lynxceLogin(
                          account,
                          password,
                          locale,
                          legacyPassword,
                        ),
                      )
                    }
                    onError={(e) =>
                      setError(apiErrorMessage(e, t("octopBot.failed"), t))
                    }
                    onClearError={() => setError("")}
                  />
                </div>
              )}
            </>
          )}
        </section>
      </div>
    </main>
  );
}
