import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { lynxceBotApi, type LynxceStatus } from "../api/modules/lynxceBot";
import { apiErrorMessage } from "../utils/apiError";
import { useCurrentUser } from "./useCurrentUser";

const changed = "octop-bot:lynxce-model-changed";

export function refreshBotModels() {
  window.dispatchEvent(new Event(changed));
}

export function useLynxceStatus(enabled: boolean) {
  const { t } = useTranslation();
  const owner = useCurrentUser()?.username;
  const [status, setStatus] = useState<LynxceStatus | null>(null);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const reload = useCallback(() => setRevision((n) => n + 1), []);
  useEffect(() => {
    setStatus(null);
    setError("");
    if (!enabled || !owner) return;
    window.addEventListener(changed, reload);
    window.addEventListener("focus", reload);
    return () => {
      window.removeEventListener(changed, reload);
      window.removeEventListener("focus", reload);
    };
  }, [enabled, owner, reload]);
  useEffect(() => {
    if (!enabled || !owner) return;
    let current = true;
    setError("");
    lynxceBotApi.status().then(
      (s) => {
        if (current) setStatus(s);
      },
      (e) => {
        if (current) setError(apiErrorMessage(e, t("octopBot.failed"), t));
      },
    );
    return () => {
      current = false;
    };
  }, [enabled, owner, revision, t]);
  // The server resolves both Lynxce models and models selected with a personal vendor key.
  const workspaceModel = enabled ? status?.selected_model ?? null : null;
  return { status, workspaceModel, error, reload };
}
