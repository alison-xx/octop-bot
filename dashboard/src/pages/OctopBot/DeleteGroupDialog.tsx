import { useState } from "react";
import { Alert, Modal } from "antd";
import { useTranslation } from "react-i18next";
import { octopBotApi, type BotGroup } from "../../api/modules/octopBot";
import { apiErrorMessage } from "../../utils/apiError";

export default function DeleteGroupDialog({
  group,
  onClose,
  onDeleted,
}: {
  group: BotGroup;
  onClose: () => void;
  onDeleted: () => void;
}) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const remove = async () => {
    setBusy(true);
    setError("");
    try {
      await octopBotApi.deleteGroup(group.group_id);
    } catch (e) {
      setError(apiErrorMessage(e, t("octopBot.failed"), t));
      setBusy(false);
      return;
    }
    onDeleted();
  };
  return (
    <Modal
      open
      title={t("octopBot.deleteGroupTitle", { name: group.name })}
      okText={t("octopBot.deleteGroup")}
      cancelText={t("common.cancel")}
      okButtonProps={{ danger: true }}
      cancelButtonProps={{ disabled: busy }}
      confirmLoading={busy}
      closable={!busy}
      keyboard={!busy}
      maskClosable={!busy}
      onCancel={onClose}
      onOk={remove}
    >
      <p>{t("octopBot.deleteGroupHint")}</p>
      {error && <Alert type="error" message={error} />}
    </Modal>
  );
}
