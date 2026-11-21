import { useState } from "react";
import { Alert, Modal } from "antd";
import { useTranslation } from "react-i18next";
import { octopAgentsApi } from "../../api/modules/octopAgents";
import type { BotGroup, WorkspaceBot } from "../../api/modules/octopBot";
import { apiErrorMessage } from "../../utils/apiError";

export default function DeleteBotDialog({
  bot,
  groups,
  onClose,
  onDeleted,
}: {
  bot: WorkspaceBot;
  groups: BotGroup[];
  onClose: () => void;
  onDeleted: () => void;
}) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const memberships = groups.filter((group) =>
    group.member_ids.includes(bot.agent_id),
  );
  const remove = async () => {
    setBusy(true);
    setError("");
    try {
      await octopAgentsApi.remove(bot.agent_id);
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
      title={t("experts.confirmDelete", { name: bot.name })}
      okText={t("octopBot.deleteBot")}
      cancelText={t("common.cancel")}
      okButtonProps={{ danger: true, disabled: memberships.length > 0 }}
      cancelButtonProps={{ disabled: busy }}
      confirmLoading={busy}
      closable={!busy}
      keyboard={!busy}
      maskClosable={!busy}
      onCancel={onClose}
      onOk={remove}
    >
      <p>
        {t(
          bot.is_private
            ? "octopBot.deletePrivateHint"
            : "octopBot.deleteBotHint",
        )}
      </p>
      {memberships.length > 0 && (
        <Alert
          type="warning"
          message={t("octopBot.deleteGroupMemberHint", {
            groups: memberships.map((group) => group.name).join(", "),
          })}
        />
      )}
      {error && <Alert type="error" message={error} />}
    </Modal>
  );
}
