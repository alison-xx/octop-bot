import { useEffect, useRef, useState } from "react";
import { Modal, Segmented } from "antd";
import { useTranslation } from "react-i18next";
import {
  desktopComputerApi,
  type ComputerTarget,
  reverifyComputerEvent,
} from "../../api/modules/botCloudComputer";
import { apiErrorMessage, parseApiError } from "../../utils/apiError";
import LynxceSignInForm from "./LynxceSignInForm";

export default function ComputerTargetPicker({
  id,
  target,
  onChanged,
}: {
  id: string;
  target: ComputerTarget;
  onChanged(): void;
}) {
  const { t } = useTranslation();
  const [dialog, setDialog] = useState<"confirm" | "verify" | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const failed = (e: unknown) =>
    setError(apiErrorMessage(e, t("octopBot.failed"), t));
  async function change(next: ComputerTarget) {
    setBusy(true);
    setError("");
    try {
      await desktopComputerApi.set(id, next);
      setDialog(null);
      onChanged();
    } catch (e) {
      if (
        next === "cloud" &&
        parseApiError(e)?.code === "BOT_CLOUD_REVERIFY_REQUIRED"
      )
        setDialog("verify");
      else failed(e);
    } finally {
      setBusy(false);
    }
  }
  const close = () => {
    if (!busy) {
      setDialog(null);
      setError("");
    }
  };
  return (
    <>
      <Segmented
        value={target}
        disabled={busy}
        options={[
          { value: "local", label: t("cloudComputer.targetLocal") },
          { value: "cloud", label: t("cloudComputer.targetCloud") },
        ]}
        onChange={(value) =>
          value === "cloud" ? setDialog("confirm") : void change("local")
        }
      />
      <Modal
        title={t("cloudComputer.targetCloud")}
        open={dialog === "confirm"}
        onCancel={close}
        onOk={() => void change("cloud")}
        confirmLoading={busy}
      >
        <p>{t("cloudComputer.targetConsent")}</p>
        {error && <p role="alert">{error}</p>}
      </Modal>
      <VerifyDialog
        open={dialog === "verify"}
        finish={(ok) => {
          setDialog(null);
          if (ok) void change("cloud");
        }}
      />
      {!dialog && error && <p role="alert">{error}</p>}
    </>
  );
}

function VerifyDialog({
  open,
  finish,
}: {
  open: boolean;
  finish(ok: boolean): void;
}) {
  const { t, i18n } = useTranslation();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const failed = (e: unknown) =>
    setError(apiErrorMessage(e, t("octopBot.failed"), t));
  async function verify(login: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await login();
      finish(true);
    } catch (e) {
      failed(e);
      return e;
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      title={t("cloudComputer.targetVerify")}
      open={open}
      footer={null}
      onCancel={() => {
        if (!busy) finish(false);
      }}
      destroyOnClose
    >
      <LynxceSignInForm
        idPrefix="cloud-computer-verify"
        busy={busy}
        submitLabel={t("cloudComputer.verifyContinue")}
        sendCode={async (target) =>
          (await desktopComputerApi.sendCode(target, i18n.language)).channel
        }
        onCode={(target, code, password) =>
          verify(() => desktopComputerApi.codeLogin(target, code, password))
        }
        onPassword={(account, password) =>
          verify(() => desktopComputerApi.login(account, password))
        }
        onError={failed}
        onClearError={() => setError("")}
      />
      {error && <p role="alert">{error}</p>}
    </Modal>
  );
}

export function ComputerReverification() {
  const waiting = useRef(new Set<(ok: boolean) => void>());
  const [open, setOpen] = useState(false);
  function finish(ok: boolean) {
    for (const settle of waiting.current) settle(ok);
    waiting.current.clear();
    setOpen(false);
  }
  useEffect(() => {
    const requests = waiting.current;
    const handle = (event: Event) => {
      event.preventDefault();
      requests.add((event as CustomEvent<(ok: boolean) => void>).detail);
      setOpen(true);
    };
    window.addEventListener(reverifyComputerEvent, handle);
    return () => {
      window.removeEventListener(reverifyComputerEvent, handle);
      for (const settle of requests) settle(false);
      requests.clear();
    };
  }, []);
  return open ? <VerifyDialog open finish={finish} /> : null;
}
