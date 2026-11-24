import { useEffect, useRef, useState, type ReactNode } from "react";
import { Button, Input } from "antd";
import { useTranslation } from "react-i18next";
import { parseApiError } from "../../utils/apiError";
import styles from "./LynxceSignInForm.module.less";

const RESEND_SECONDS = 60;
const CODE = /^\d{6}$/;
const MIN_PASSWORD = 8;

type Mode = "code" | "password";

export interface LynxceSignInFormProps {
  /** Prefix for input ids, unique per page. */
  idPrefix: string;
  busy: boolean;
  submitLabel: ReactNode;
  /** Shown under the password field (e.g. "the password is not kept"). */
  passwordHint?: ReactNode;
  autoFocus?: boolean;
  /** Ask Lynxce to text or email a code; resolves to where it went. */
  sendCode: (target: string) => Promise<"phone" | "email">;
  /**
   * Sign in with the code; the caller shows any error, and resolves with it.
   * `password` is set only after Lynxce asked for one to create a new (email) account.
   */
  onCode: (target: string, code: string, password?: string) => Promise<unknown>;
  onPassword: (account: string, password: string) => Promise<unknown>;
  onError: (error: unknown) => void;
  onClearError: () => void;
  children?: ReactNode;
}

/**
 * Lynxce sign-in: a one-time code by default (works for accounts that never
 * set a password, and creates new accounts), with the password as a fallback.
 */
export default function LynxceSignInForm({
  idPrefix,
  busy,
  submitLabel,
  passwordHint,
  autoFocus,
  sendCode,
  onCode,
  onPassword,
  onError,
  onClearError,
  children,
}: LynxceSignInFormProps) {
  const { t } = useTranslation();
  const [mode, setMode] = useState<Mode>("code");
  const [target, setTarget] = useState("");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  // Lynxce creates a new email account only with a password; asked after the first try.
  const [askPassword, setAskPassword] = useState(false);
  const [newPassword, setNewPassword] = useState("");
  const [sending, setSending] = useState(false);
  const [sentTo, setSentTo] = useState<"phone" | "email" | null>(null);
  const [wait, setWait] = useState(0);
  const tried = useRef("");

  useEffect(() => {
    if (wait <= 0) return;
    const timer = window.setTimeout(() => setWait((s) => s - 1), 1000);
    return () => window.clearTimeout(timer);
  }, [wait]);

  const send = async () => {
    if (sending || wait > 0 || !target.trim()) return;
    setSending(true);
    onClearError();
    try {
      setSentTo(await sendCode(target.trim()));
      setWait(RESEND_SECONDS);
      setCode("");
      setAskPassword(false);
      tried.current = "";
      document.getElementById(`${idPrefix}-code`)?.focus();
    } catch (err) {
      onError(err);
    } finally {
      setSending(false);
    }
  };

  const passwordReady =
    !askPassword || newPassword.trim().length >= MIN_PASSWORD;

  const submitCode = (value: string) => {
    if (busy || !target.trim() || !CODE.test(value) || !passwordReady) return;
    tried.current = value;
    onClearError();
    void onCode(
      target.trim(),
      value,
      askPassword ? newPassword : undefined,
    ).then((failure) => {
      if (parseApiError(failure)?.code === "LYNXCE_SIGNUP_PASSWORD_REQUIRED") {
        setAskPassword(true);
        // The code is still good: only the password is missing.
        window.setTimeout(
          () => document.getElementById(`${idPrefix}-new-password`)?.focus(),
        );
      }
    });
  };

  const submit = () => {
    if (busy) return;
    if (mode === "code") {
      submitCode(code);
      return;
    }
    if (!target.trim() || !password) return;
    onClearError();
    void onPassword(target.trim(), password);
  };

  const choose = (next: Mode) => {
    if (next === mode) return;
    setMode(next);
    onClearError();
  };

  return (
    <form
      className={styles.form}
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <div
        className={styles.tabs}
        role="group"
        aria-label={t("lynxceSignIn.methods")}
      >
        {(["code", "password"] as const).map((value) => (
          <button
            key={value}
            type="button"
            aria-pressed={mode === value}
            onClick={() => choose(value)}
          >
            {t(
              value === "code"
                ? "lynxceSignIn.tabCode"
                : "lynxceSignIn.tabPassword",
            )}
          </button>
        ))}
      </div>
      <label htmlFor={`${idPrefix}-target`}>
        {t(mode === "code" ? "lynxceSignIn.target" : "lynxceSignIn.account")}
      </label>
      <Input
        id={`${idPrefix}-target`}
        autoComplete="username"
        autoFocus={autoFocus}
        required
        maxLength={200}
        value={target}
        onChange={(e) => {
          setTarget(e.target.value);
          setSentTo(null);
          setAskPassword(false);
        }}
        placeholder={t(
          mode === "code"
            ? "lynxceSignIn.targetPlaceholder"
            : "lynxceSignIn.accountPlaceholder",
        )}
      />
      {mode === "code" ? (
        <>
          <label htmlFor={`${idPrefix}-code`}>{t("lynxceSignIn.code")}</label>
          <div className={styles.codeRow}>
            <Input
              id={`${idPrefix}-code`}
              autoComplete="one-time-code"
              inputMode="numeric"
              maxLength={6}
              value={code}
              placeholder={t("lynxceSignIn.codePlaceholder")}
              onChange={(e) => {
                const next = e.target.value.replace(/\D/g, "").slice(0, 6);
                setCode(next);
                if (CODE.test(next) && next !== tried.current) submitCode(next);
              }}
            />
            <Button
              className={styles.send}
              loading={sending}
              disabled={!target.trim() || wait > 0 || busy}
              onClick={() => void send()}
            >
              {wait > 0
                ? t("lynxceSignIn.resendIn", { seconds: wait })
                : t(sentTo ? "lynxceSignIn.resend" : "lynxceSignIn.send")}
            </Button>
          </div>
          <small>
            {sentTo
              ? t(
                  sentTo === "email"
                    ? "lynxceSignIn.sentEmail"
                    : "lynxceSignIn.sentPhone",
                )
              : t("lynxceSignIn.newAccountHint")}
          </small>
          {askPassword && (
            <>
              <label htmlFor={`${idPrefix}-new-password`}>
                {t("lynxceSignIn.newPassword")}
              </label>
              <Input.Password
                id={`${idPrefix}-new-password`}
                autoComplete="new-password"
                maxLength={256}
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
              />
              <small>{t("lynxceSignIn.newPasswordHint")}</small>
            </>
          )}
        </>
      ) : (
        <>
          <label htmlFor={`${idPrefix}-password`}>
            {t("lynxceSignIn.password")}
          </label>
          <Input.Password
            id={`${idPrefix}-password`}
            autoComplete="current-password"
            maxLength={256}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          {passwordHint && <small>{passwordHint}</small>}
        </>
      )}
      <Button
        type="primary"
        size="large"
        htmlType="submit"
        loading={busy}
        disabled={
          !target.trim() ||
          (mode === "code" ? !CODE.test(code) || !passwordReady : !password)
        }
      >
        {submitLabel}
      </Button>
      {children}
    </form>
  );
}
