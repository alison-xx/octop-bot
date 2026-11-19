import { useState } from "react";
import { Alert, Empty, Input, List, Modal, Button } from "antd";
import { useTranslation } from "react-i18next";
import { octopBotApi, type ChatReference } from "../../api/modules/octopBot";
import { apiErrorMessage } from "../../utils/apiError";
import styles from "./index.module.less";
import { useHistorySearch } from "./useHistorySearch";

export default function ReferenceDialog({
  onClose,
  onPick,
}: {
  onClose: () => void;
  onPick: (text: string) => void;
}) {
  const { t } = useTranslation();
  const [q, setQ] = useState("");
  const { rows, pending, error: searchError, retry } = useHistorySearch(q);
  const [inserting, setInserting] = useState(false);
  const [error, setError] = useState("");
  const insert = async (row: ChatReference) => {
    setInserting(true);
    setError("");
    try {
      const ref = await octopBotApi.reference(row);
      onPick(ref.text);
      onClose();
    } catch (e) {
      setError(apiErrorMessage(e, t("octopBot.failed"), t));
    } finally {
      setInserting(false);
    }
  };
  return (
    <Modal
      open
      title={t("octopBot.reference")}
      onCancel={onClose}
      footer={null}
    >
      <Input
        aria-label={t("octopBot.searchHistory")}
        autoFocus
        value={q}
        maxLength={160}
        onChange={(e) => {
          setError("");
          setQ(e.target.value);
        }}
        placeholder={t("octopBot.searchHistory")}
      />
      {error && <Alert type="error" showIcon message={error} />}
      {searchError && (
        <Alert
          type="error"
          showIcon
          message={searchError}
          action={<Button onClick={retry}>{t("octopBot.retry")}</Button>}
        />
      )}
      {q.trim() && (
        <List<ChatReference>
          loading={pending && rows.length === 0}
          locale={{
            emptyText: (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={t("octopBot.noMatches")}
              />
            ),
          }}
          dataSource={rows}
          renderItem={(row) => (
            <List.Item
              key={
                row.thread_id +
                ":" +
                String(row.message_seq ?? row.message_id ?? "")
              }
            >
              <Button
                className={styles.referenceRow}
                type="text"
                disabled={inserting}
                onClick={() => void insert(row)}
              >
                <strong>
                  {row.title || t("chatWelcome.newChat")}
                  {" · "}
                  {t("octopBot.historyPart", { number: row.part })}
                </strong>
                <small>{row.excerpt}</small>
              </Button>
            </List.Item>
          )}
        />
      )}
    </Modal>
  );
}
