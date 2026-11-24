import { useEffect, useRef, useState, type ReactNode } from "react";
import { Button, Input } from "antd";
import { Check, LockKeyhole, Mail, Smartphone, UserRound } from "lucide-react";
import { useTranslation } from "react-i18next";
import { parseApiError } from "../../utils/apiError";
import styles from "./LynxceSignInForm.module.less";

const RESEND_SECONDS = 60;
const CODE = /^\d{6}$/;
const MIN_PASSWORD = 8;

type Mode = "code" | "password";
type Missing = "target" | "code" | "password" | "newPassword";

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

/** An email address once it has an "@" or any letter; otherwise a phone number. */
export function looksLikeEmail(value: string): boolean {
  return /@|[a-z]/i.test(value);
}

/**
 * Lynxce sign-in: one field for a phone number or an email, a one-time code by
 * default (works for accounts that never set a password, and creates new
 * accounts), and the password behind a link. The button stays clickable: an
 * empty field is pointed at instead of greying the button out.
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
  const [missing, setMissing] = useState<Missing | null>(null);
  // Bumped on every refused submit so the field shakes again.
  const [nudge, setNudge] = useState(0);
  const tried = useRef("");

  useEffect(() => {
    if (wait <= 0) return;
    const timer = window.setTimeout(() => setWait((s) => s - 1), 1000);
    return () => window.clearTimeout(timer);
  }, [wait]);

  const id = (field: string) => `${idPrefix}-${field}`;
  const focus = (field: string) =>
    window.setTimeout(() => document.getElementById(id(field))?.focus());

  const require = (field: Missing) => {
    setMissing(field);
    setNudge((n) => n + 1);
    focus(field === "newPassword" ? "new-password" : field);
  };

  const send = async () => {
    if (sending || wait > 0) return;
    if (!target.trim()) {
      require("target");
      return;
    }
    setSending(true);
    setMissing(null);
    onClearError();
    try {
      setSentTo(await sendCode(target.trim()));
      setWait(RESEND_SECONDS);
      setCode("");
      setAskPassword(false);
      tried.current = "";
      focus("code");
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
    setMissing(null);
    onClearError();
    void onCode(
      target.trim(),
      value,
      askPassword ? newPassword : undefined,
    ).then((failure) => {
      if (parseApiError(failure)?.code === "LYNXCE_SIGNUP_PASSWORD_REQUIRED") {
        setAskPassword(true);
        // The code is still good: only the password is missing.
        focus("new-password");
      }
    });
  };

  const submit = () => {
    if (busy) return;
    if (!target.trim()) return require("target");
    if (mode === "code") {
      if (!CODE.test(code)) return require("code");
      if (!passwordReady) return require("newPassword");
      submitCode(code);
      return;
    }
    if (!password) return require("password");
    setMissing(null);
    onClearError();
    void onPassword(target.trim(), password);
  };

  const choose = (next: Mode) => {
    setMode(next);
    setMissing(null);
    onClearError();
    focus(next === "code" && target.trim() ? "code" : "target");
  };

  const status = (field: Missing) =>
    missing === field ? ("error" as const) : undefined;
  // Two identical animations, alternated, replay the shake on every refused submit.
  const shake = (field: Missing) =>
    missing === field
      ? nudge % 2
        ? styles.shake
        : styles.shakeAgain
      : undefined;
  const email = looksLikeEmail(target);
  const TargetIcon =
    mode === "password" ? UserRound : email ? Mail : Smartphone;
  const hint =
    missing === "target"
      ? t("lynxceSignIn.missingTarget")
      : missing === "code"
      ? t("lynxceSignIn.missingCode")
      : missing === "password"
      ? t("lynxceSignIn.missingPassword")
      : mode === "password"
      ? passwordHint
      : sentTo
      ? t(
          sentTo === "email"
            ? "lynxceSignIn.sentEmail"
            : "lynxceSignIn.sentPhone",
        )
      : t("lynxceSignIn.newAccountHint");
  const hintIsError = missing !== null && missing !== "newPassword";

  return (
    <form
      className={styles.form}
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <label className={styles.srOnly} htmlFor={id("target")}>
        {t(mode === "code" ? "lynxceSignIn.target" : "lynxceSignIn.account")}
      </label>
      <Input
        id={id("target")}
        className={shake("target")}
        status={status("target")}
        size="large"
        autoComplete="username"
        autoFocus={autoFocus}
        maxLength={200}
        inputMode={mode === "code" && !email ? "tel" : "email"}
        prefix={
          <TargetIcon
            size={17}
            aria-hidden="true"
            className={target.trim() ? styles.iconActive : styles.icon}
          />
        }
        value={target}
        onChange={(e) => {
          setTarget(e.target.value);
          setSentTo(null);
          setAskPassword(false);
          if (missing === "target") setMissing(null);
        }}
        placeholder={t(
          mode === "code"
            ? "lynxceSignIn.targetPlaceholder"
            : "lynxceSignIn.accountPlaceholder",
        )}
      />
      {mode === "code" ? (
        <>
          <label className={styles.srOnly} htmlFor={id("code")}>
            {t("lynxceSignIn.code")}
          </label>
          <Input
            id={id("code")}
            className={[styles.code, shake("code")].filter(Boolean).join(" ")}
            status={status("code")}
            size="large"
            autoComplete="one-time-code"
            inputMode="numeric"
            maxLength={6}
            value={code}
            placeholder={t("lynxceSignIn.codePlaceholder")}
            prefix={
              <Check size={17} aria-hidden="true" className={styles.icon} />
            }
            suffix={
              <Button
                type="link"
                className={styles.send}
                loading={sending}
                disabled={wait > 0 || busy}
                onClick={() => void send()}
              >
                {wait > 0
                  ? t("lynxceSignIn.resendIn", { seconds: wait })
                  : t(sentTo ? "lynxceSignIn.resend" : "lynxceSignIn.send")}
              </Button>
            }
            onChange={(e) => {
              const next = e.target.value.replace(/\D/g, "").slice(0, 6);
              setCode(next);
              if (missing === "code") setMissing(null);
              if (CODE.test(next) && next !== tried.current) submitCode(next);
            }}
          />
        </>
      ) : (
        <>
          <label className={styles.srOnly} htmlFor={id("password")}>
            {t("lynxceSignIn.password")}
          </label>
          <Input.Password
            id={id("password")}
            className={shake("password")}
            status={status("password")}
            size="large"
            autoComplete="current-password"
            maxLength={256}
            placeholder={t("lynxceSignIn.password")}
            prefix={
              <LockKeyhole
                size={17}
                aria-hidden="true"
                className={styles.icon}
              />
            }
            value={password}
            onChange={(e) => {
              setPassword(e.target.value);
              if (missing === "password") setMissing(null);
            }}
          />
        </>
      )}
      <div className={styles.hintRow}>
        <small
          className={hintIsError ? styles.error : undefined}
          role={hintIsError ? "alert" : undefined}
        >
          {hint}
        </small>
        <button
          type="button"
          className={styles.switch}
          onClick={() => choose(mode === "code" ? "password" : "code")}
        >
          {t(
            mode === "code"
              ? "lynxceSignIn.usePassword"
              : "lynxceSignIn.useCode",
          )}
        </button>
      </div>
      {mode === "code" && askPassword && (
        <div className={styles.newPassword}>
          <label htmlFor={id("new-password")}>
            {t("lynxceSignIn.newPassword")}
          </label>
          <Input.Password
            id={id("new-password")}
            className={shake("newPassword")}
            status={status("newPassword")}
            size="large"
            autoComplete="new-password"
            maxLength={256}
            value={newPassword}
            onChange={(e) => {
              setNewPassword(e.target.value);
              if (missing === "newPassword") setMissing(null);
            }}
          />
          <small
            className={missing === "newPassword" ? styles.error : undefined}
          >
            {t("lynxceSignIn.newPasswordHint")}
          </small>
        </div>
      )}
      <Button
        type="primary"
        size="large"
        htmlType="submit"
        className={styles.submit}
        loading={busy}
      >
        {submitLabel}
      </Button>
      {children}
    </form>
  );
}
