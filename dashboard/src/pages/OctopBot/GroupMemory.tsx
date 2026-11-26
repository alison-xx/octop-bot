import { useEffect, useState } from "react";
import { Alert, Button, Drawer, Input, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { octopBotApi } from "../../api/modules/octopBot";
import { apiErrorMessage } from "../../utils/apiError";

export default function GroupMemory({
  id,
  onClose,
}: {
  id?: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let live = true;
    setError("");
    setText(null);
    void octopBotApi
      .memory(id)
      .then((v) => {
        if (live) setText(v.text);
      })
      .catch((e) => {
        if (live) setError(apiErrorMessage(e, t("octopBot.failed"), t));
      });
    return () => {
      live = false;
    };
  }, [id, t, attempt]);
  const save = async () => {
    if (text === null) return;
    setError("");
    setSaving(true);
    try {
      await octopBotApi.saveMemory(text, id);
      onClose();
    } catch (e) {
      setError(apiErrorMessage(e, t("octopBot.failed"), t));
    } finally {
      setSaving(false);
    }
  };
  const title = t(id ? "octopBot.groupMemory" : "octopBot.teamMemory");
  return (
    <Drawer
      open
      title={title}
      onClose={onClose}
      extra={
        <Button
          type="primary"
          disabled={text === null}
          loading={saving}
          onClick={() => void save()}
        >
          {t("octopBot.save")}
        </Button>
      }
    >
      <p>{t("octopBot.memoryScope")}</p>
      {error && (
        <Alert
          type="error"
          message={error}
          action={
            text === null && (
              <Button size="small" onClick={() => setAttempt((n) => n + 1)}>
                {t("octopBot.retry")}
              </Button>
            )
          }
        />
      )}
      {text === null ? (
        !error && <Spin />
      ) : (
        <Input.TextArea
          value={text}
          autoSize={{ minRows: 12 }}
          aria-label={title}
          onChange={(e) => setText(e.target.value)}
        />
      )}
    </Drawer>
  );
}
