import { useEffect, useState } from "react";
import { Alert, Button, Input, Spin } from "antd";
import { ArrowRight } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { authApi, isMfaChallenge } from "../../api/modules/auth";
import { setAuthToken } from "../../api/request";
import { BOT_HOME } from "../../utils/botClientRoute";
import { apiErrorMessage } from "../../utils/apiError";
import { BotCharacter, octopCharacter } from "./BotCharacter";
import LynxceSignInForm from "./LynxceSignInForm";
import intro from "./BotClientSetup.module.less";

type Mode = "loading" | "lynxce" | "local";

/** Bot web build sign-in: the bound Lynxce account, or the local owner's password. */
export default function BotLogin() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const [mode, setMode] = useState<Mode>("loading");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let mounted = true;
    Promise.all([authApi.getAuthStatus(), authApi.getLynxceIdentityStatus()])
      .then(([status, lynxce]) => {
        if (!mounted) return;
        if (status.setup_required) {
          navigate("/setup", { replace: true });
          return;
        }
        setMode(lynxce.enabled && lynxce.claimed ? "lynxce" : "local");
      })
      .catch(() => mounted && setMode("local"));
    return () => {
      mounted = false;
    };
  }, [navigate]);

  const locale = i18n.language.startsWith("zh") ? "zh" : "en";
  const lynxceSignIn = async (
    attempt: () => Promise<{ access_token: string }>,
  ) => {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      setAuthToken((await attempt()).access_token);
      navigate(BOT_HOME, { replace: true });
    } catch (e) {
      setError(apiErrorMessage(e, t("octopBot.failed"), t));
    } finally {
      setBusy(false);
    }
  };

  const submit = async () => {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const result = await authApi.login("local", password);
      if (isMfaChallenge(result)) {
        // The Bot client has no MFA step; an owner who enabled it elsewhere
        // must sign in through the full Octop dashboard.
        throw new Error(t("octopBot.failed"));
      }
      setAuthToken(result.access_token);
      navigate(BOT_HOME, { replace: true });
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
          <h1>{t("botOnboarding.loginTitle")}</h1>
          {mode === "loading" ? (
            <Spin />
          ) : (
            <>
              <p>
                {t(
                  mode === "lynxce"
                    ? "botOnboarding.loginLynxceBody"
                    : "botOnboarding.loginLocalBody",
                )}
              </p>
              {error && <Alert type="error" message={error} showIcon />}
              {mode === "lynxce" ? (
                <div className={intro.webForms}>
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
                    onCode={(target, code) =>
                      lynxceSignIn(() =>
                        authApi.lynxceCodeLogin(target, code, locale),
                      )
                    }
                    onPassword={(account, password) =>
                      lynxceSignIn(() =>
                        authApi.lynxceLogin(account, password, locale),
                      )
                    }
                    onError={(e) =>
                      setError(apiErrorMessage(e, t("octopBot.failed"), t))
                    }
                    onClearError={() => setError("")}
                  />
                </div>
              ) : (
                <form
                  className={`${intro.form} ${intro.webForms}`}
                  onSubmit={(event) => {
                    event.preventDefault();
                    void submit();
                  }}
                >
                  <label htmlFor="bot-login-password">
                    {t("botOnboarding.password")}
                  </label>
                  <Input.Password
                    id="bot-login-password"
                    autoComplete="current-password"
                    autoFocus
                    required
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                  />
                  <Button
                    type="primary"
                    size="large"
                    htmlType="submit"
                    loading={busy}
                    disabled={!password}
                  >
                    {t("botOnboarding.loginTitle")}
                    <ArrowRight size={16} aria-hidden="true" />
                  </Button>
                </form>
              )}
            </>
          )}
        </section>
      </div>
    </main>
  );
}
