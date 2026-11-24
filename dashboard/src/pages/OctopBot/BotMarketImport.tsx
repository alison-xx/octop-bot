import { useRef, useState } from "react";
import { Alert, Checkbox, Input, Modal } from "antd";
import { CalendarClock, Plug } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  botMarketApi,
  type MarketDetail,
  type MarketImport,
} from "../../api/modules/botMarket";
import { apiErrorMessage } from "../../utils/apiError";
import { MarketAvatar } from "./BotMarketParts";
import styles from "./botMarket.module.less";

/** Confirm the name and routines, then create the Bot. */
export default function BotMarketImport({
  template,
  onClose,
  onImported,
}: {
  template: MarketDetail;
  onClose: () => void;
  onImported: (result: MarketImport) => void;
}) {
  const { t } = useTranslation();
  const [name, setName] = useState(template.name);
  const [routines, setRoutines] = useState(
    template.routines.filter((r) => r.suggested).map((r) => r.id),
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const busy = useRef(false);
  const submit = async () => {
    if (busy.current || !name.trim()) return;
    busy.current = true;
    setSaving(true);
    setError("");
    try {
      onImported(
        await botMarketApi.install(template.slug, name.trim(), routines),
      );
    } catch (e) {
      setError(apiErrorMessage(e, t("octopBot.failed"), t));
    } finally {
      busy.current = false;
      setSaving(false);
    }
  };
  return (
    <Modal
      open
      centered
      width={520}
      title={t("botMarket.importTitle")}
      okText={t("botMarket.importConfirm")}
      onOk={submit}
      okButtonProps={{ disabled: !name.trim() }}
      confirmLoading={saving}
      onCancel={saving ? undefined : onClose}
      closable={!saving}
      maskClosable={!saving}
      cancelButtonProps={{ disabled: saving }}
      className={styles.importDialog}
    >
      <div className={styles.importHead}>
        <MarketAvatar card={template} size={56} />
        <label>
          <span>{t("botMarket.nameLabel")}</span>
          <Input
            value={name}
            maxLength={64}
            onChange={(e) => setName(e.target.value)}
            onPressEnter={submit}
            disabled={saving}
          />
        </label>
      </div>
      <p className={styles.importIncludes}>
        {t("botMarket.importIncludes", {
          skills: template.skills.length,
          memories: template.memories.length,
          starters: template.starters.length,
        })}
      </p>
      {template.routines.length > 0 && (
        <fieldset className={styles.importRoutines}>
          <legend>
            <CalendarClock size={15} />
            {t("botMarket.routinesPick")}
          </legend>
          <Checkbox.Group
            value={routines}
            onChange={(v) => setRoutines(v as string[])}
            disabled={saving}
          >
            {template.routines.map((r) => (
              <Checkbox key={r.id} value={r.id}>
                <strong>{r.name}</strong>
                <span>{r.when}</span>
              </Checkbox>
            ))}
          </Checkbox.Group>
          <small>{t("botMarket.routinesHint")}</small>
        </fieldset>
      )}
      {template.integrations.length > 0 && (
        <p className={styles.importConnect}>
          <Plug size={15} />
          {t("botMarket.integrationsAfter", {
            names: template.integrations
              .map((i) => i.name)
              .join(t("botMarket.listJoin")),
          })}
        </p>
      )}
      {error && <Alert type="error" message={error} />}
    </Modal>
  );
}
