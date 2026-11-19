import { useEffect, useRef, useState } from "react";
import { Alert, Button, Empty, Modal, Spin } from "antd";
import { useTranslation } from "react-i18next";
import {
  botCloudApi,
  type CloudImportPreview,
} from "../../api/modules/botCloud";
import { apiErrorMessage } from "../../utils/apiError";
import styles from "./cloud.module.less";

export default function CloudImport({
  accountId,
  botId,
  threadId,
  model,
  onClose,
  onDone,
}: {
  accountId: string;
  botId: string;
  threadId: string;
  model: string;
  onClose: () => void;
  onDone: (id: string) => void;
}) {
  const { t } = useTranslation();
  const [preview, setPreview] = useState<CloudImportPreview | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [revision, setRevision] = useState(0);
  const lock = useRef(false);
  useEffect(() => {
    let live = true;
    setPreview(null);
    setError("");
    botCloudApi
      .previewImport(botId, threadId)
      .then((result) => {
        if (live) setPreview(result);
      })
      .catch((err) => {
        if (live) setError(apiErrorMessage(err, t("octopBot.failed"), t));
      });
    return () => {
      live = false;
    };
  }, [botId, threadId, revision, t]);
  const submit = async () => {
    if (!preview?.items.length || !model || lock.current) return;
    lock.current = true;
    setLoading(true);
    setError("");
    try {
      const result = await botCloudApi.importChat(
        botId,
        threadId,
        accountId,
        preview.revision,
        model,
      );
      onDone(result.session_id);
    } catch (err) {
      setError(apiErrorMessage(err, t("octopBot.failed"), t));
    } finally {
      lock.current = false;
      setLoading(false);
    }
  };
  return (
    <Modal
      open
      centered
      title={t("botCloud.importChat")}
      onCancel={() => {
        if (!lock.current) onClose();
      }}
      onOk={() => void submit()}
      okText={t("botCloud.confirmImport")}
      confirmLoading={loading}
      okButtonProps={{ disabled: !preview?.items.length || !model }}
      cancelButtonProps={{ disabled: loading }}
    >
      <p className={styles.hint}>{t("botCloud.importHint")}</p>
      {error && (
        <Alert
          type="error"
          showIcon
          message={error}
          action={
            <Button size="small" onClick={() => setRevision((n) => n + 1)}>
              {t("common.refresh")}
            </Button>
          }
        />
      )}
      {!preview ? (
        !error && <Spin />
      ) : preview.items.length ? (
        <>
          <h3>{preview.title}</h3>
          <div className={styles.preview}>
            {preview.items.map((m, i) => (
              <article key={i}>
                <strong>
                  {t(m.role === "user" ? "octopBot.you" : "botCloud.bot")}
                </strong>
                <p>{m.content}</p>
              </article>
            ))}
          </div>
          {!model && (
            <Alert type="info" message={t("botCloud.importNeedsModel")} />
          )}
        </>
      ) : (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={t("botCloud.noText")}
        />
      )}
    </Modal>
  );
}
