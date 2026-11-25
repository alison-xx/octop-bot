import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Alert, Input, Modal, Spin } from "antd";
import { ArrowRight, Cloud, MonitorSmartphone, UsersRound } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { authApi } from "../../api/modules/auth";
import { setAuthToken } from "../../api/request";
import { BOT_HOME, loginDestination } from "../../utils/botClientRoute";
import { apiErrorMessage, parseApiError } from "../../utils/apiError";
import mascot from "../../assets/avatars/octop-mascot.webp";
import { BotLoginBind, useBotLoginSocial } from "./BotLoginSocial";
import LynxceSignInForm from "./LynxceSignInForm";
import BotLoginPreview from "./BotLoginPreview";
import styles from "./BotLogin.module.less";

type Mode = "loading" | "lynxce" | "unavailable";

/**
 * Bot web build sign-in: Lynxce accounts only. An instance set up earlier with a local
 * password asks for that password once, to bind the Lynxce account to its owner.
 */
export default function BotLogin() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [mode, setMode] = useState<Mode>("loading");
  const [legacy, setLegacy] = useState(false);
  // Octop Bot cloud: every Lynxce account signs in to an account of its own.
  const [open, setOpen] = useState(
    () =>
      new URLSearchParams(window.location.hash.slice(1)).has("provider") ||
      !!sessionStorage.getItem("octop.cloud.web.login.v1"),
  );
  const trigger = useRef<HTMLElement | null>(null);
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
        setCloud(lynxce.enabled && lynxce.cloud === true);
        setLegacy(lynxce.legacy_owner === true);
        setMode(lynxce.enabled ? "lynxce" : "unavailable");
      })
      .catch(() => mounted && setMode("unavailable"));
    return () => {
      mounted = false;
    };
  }, [navigate]);

  if (mode === "loading")
    return (
      <main className={styles.page}>
        <Spin aria-label={t("common.loading")} />
      </main>
    );
  const card = <LoginCard mode={mode} legacy={legacy} cloud={cloud} />;
  if (!cloud) return <main className={styles.page}>{card}</main>;

  return (
    <>
      <BotLoginPreview
        onUse={() => {
          trigger.current =
            document.activeElement instanceof HTMLElement
              ? document.activeElement
              : null;
          setOpen(true);
        }}
        modalOpen={open}
      />
      {open && (
        <Modal
          open
          centered
          width={900}
          className={styles.modal}
          rootClassName={styles.modalRoot}
          footer={null}
          title={
            <span className={styles.srOnly}>{t("botWebLogin.title")}</span>
          }
          onCancel={() => {
            setOpen(false);
            requestAnimationFrame(
              () => trigger.current?.focus({ preventScroll: true }),
            );
          }}
        >
          {card}
        </Modal>
      )}
    </>
  );
}

function LoginCard({
  mode,
  legacy,
  cloud,
}: {
  mode: Exclude<Mode, "loading">;
  legacy: boolean;
  cloud: boolean;
}) {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const mounted = useRef(true);
  useLayoutEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const [legacyPassword, setLegacyPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const locale = i18n.language.startsWith("zh") ? "zh" : "en";
  const signedIn = (token: string) => {
    if (!mounted.current) return;
    setAuthToken(token);
    navigate(loginDestination(BOT_HOME), { replace: true });
  };
  const social = useBotLoginSocial(cloud, locale, signedIn, busy);
  /** Resolves with the error when sign-in failed (shown here, inspected by the form). */
  const lynxceSignIn = async (
    attempt: () => Promise<{ access_token: string }>,
  ): Promise<unknown> => {
    if (busy || social.waiting) return;
    social.clear();
    setBusy(true);
    setError("");
    try {
      signedIn((await attempt()).access_token);
    } catch (e) {
      if (!mounted.current) return;
      if (parseApiError(e)?.code !== "LYNXCE_SIGNUP_PASSWORD_REQUIRED")
        setError(apiErrorMessage(e, t("octopBot.failed"), t));
      return e;
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className={styles.split} aria-labelledby="bot-login-title">
      <aside className={styles.identity}>
        <div className={styles.brand}>
          <img src={mascot} alt="" />
          <span>Octop Bot</span>
        </div>
        <div className={styles.story}>
          <img className={styles.mascot} src={mascot} alt="" />
          <h2>{t("botStart.heroTitle")}</h2>
          <p>{t("botStart.heroSub")}</p>
          <ul>
            {(
              [
                [UsersRound, "featureChief"],
                [MonitorSmartphone, "featureDevices"],
                [Cloud, "featureComputer"],
              ] as const
            ).map(([Icon, key]) => (
              <li key={key}>
                <Icon size={15} aria-hidden="true" />
                {t("botStart." + key)}
              </li>
            ))}
          </ul>
        </div>
      </aside>
      <div className={styles.card}>
        <h1 id="bot-login-title">
          {t(
            social.bindToken ? "botCloud.wechatBindTitle" : "botWebLogin.title",
          )}
        </h1>
        <p className={styles.description}>
          {t(
            social.bindToken
              ? "botCloud.wechatBindBody"
              : mode !== "lynxce"
              ? "botOnboarding.loginUnavailable"
              : cloud
              ? "botWebLogin.intro"
              : legacy
              ? "botOnboarding.loginLegacyBody"
              : "botOnboarding.loginLynxceBody",
          )}
        </p>
        {error && <Alert type="error" message={error} showIcon />}
        {social.notice && (
          <p role="status" className={styles.notice}>
            {social.notice}
          </p>
        )}
        {social.bindToken ? (
          <BotLoginBind
            token={social.bindToken}
            locale={locale}
            onDone={signedIn}
            onBack={social.cancelBind}
          />
        ) : (
          mode === "lynxce" && (
            <>
              {legacy && (
                <div className={styles.bind}>
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
                webLayout
                busy={busy || social.waiting}
                submitLabel={
                  <>
                    {t("botWebLogin.submit")}
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
                onClearError={() => {
                  setError("");
                  social.clear();
                }}
              />
              {cloud && social.buttons}
              {social.waiting && (
                <div className={styles.notice} role="status">
                  {t("botWebLogin.waiting")}
                </div>
              )}
            </>
          )
        )}
      </div>
    </section>
  );
}
