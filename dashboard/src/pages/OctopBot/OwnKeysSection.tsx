import { useCallback, useEffect, useState } from "react";
import { Alert, Button, Popconfirm, Select, Spin } from "antd";
import { Plus, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  ownModelKeysApi,
  type OwnKey,
  type OwnKeyList,
} from "../../api/modules/ownModelKeys";
import { getProviderName } from "../../assets/providers";
import { apiErrorMessage } from "../../utils/apiError";
import AddModelKeyDialog, { VendorLogo } from "./AddModelKeyDialog";
import ModelName from "./ModelName";
import styles from "./modelSources.module.less";

/**
 * "My API keys": the user's own vendor keys (Tencent Cloud, Bailian, Ark, DeepSeek…).
 * Chats on these are billed by the vendor, not in Lynxce credits.
 */
export default function OwnKeysSection({
  cloud,
  revision: outer = 0,
  onState,
  onChanged,
}: {
  cloud: boolean;
  /** Bumped by the page when the model in use may have changed elsewhere. */
  revision?: number;
  /** The loaded list, so the page knows which key (if any) is in use. */
  onState?: (list: OwnKeyList | null) => void;
  /** The model in use may have changed; the caller refreshes its summary. */
  onChanged: () => void;
}) {
  const { t } = useTranslation();
  const [list, setList] = useState<OwnKeyList | null>(null);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    let current = true;
    setError("");
    ownModelKeysApi.list().then(
      (data) => current && setList(data),
      (e) => current && setError(apiErrorMessage(e, t("octopBot.failed"), t)),
    );
    return () => {
      current = false;
    };
  }, [revision, outer, t]);

  useEffect(() => {
    onState?.(list);
  }, [list, onState]);

  const changed = useCallback(
    (next?: OwnKeyList) => {
      if (next) setList(next);
      else setRevision((n) => n + 1);
      onChanged();
    },
    [onChanged],
  );

  const use = async (key: OwnKey, model: string) => {
    setBusy(key.id);
    setActionError("");
    try {
      changed(await ownModelKeysApi.useModel(key.id, model));
    } catch (e) {
      setActionError(apiErrorMessage(e, t("octopBot.failed"), t));
    } finally {
      setBusy(null);
    }
  };

  const remove = async (key: OwnKey) => {
    setBusy(key.id);
    setActionError("");
    try {
      await ownModelKeysApi.remove(key.id);
      changed();
    } catch (e) {
      setActionError(apiErrorMessage(e, t("octopBot.failed"), t));
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className={styles.section} aria-labelledby="own-keys-title">
      <div className={styles.sectionHead}>
        <h2 id="own-keys-title">
          {t("botModels.keys.title")}
          <span className={styles.tag}>{t("botModels.keys.billing")}</span>
        </h2>
        <Button icon={<Plus size={15} />} onClick={() => setAdding(true)}>
          {t("botModels.keys.add")}
        </Button>
      </div>
      {error ? (
        <Alert
          type="error"
          message={error}
          action={
            <Button onClick={() => setRevision((n) => n + 1)}>
              {t("octopBot.retry")}
            </Button>
          }
        />
      ) : !list ? (
        <Spin />
      ) : list.keys.length === 0 ? (
        <button
          type="button"
          className={styles.emptyRow}
          onClick={() => setAdding(true)}
        >
          <strong>{t("botModels.keys.emptyTitle")}</strong>
          <span>{t("botModels.keys.emptyBody")}</span>
        </button>
      ) : (
        <ul className={styles.rows} aria-label={t("botModels.keys.title")}>
          {list.keys.map((key) => {
            const inUse = list.in_use === key.id;
            return (
              <li key={key.id}>
                <VendorLogo id={key.vendor} size={30} />
                <span className={styles.rowText}>
                  <strong>
                    {key.vendor === "custom"
                      ? key.name
                      : getProviderName(key.vendor, key.name, t)}
                  </strong>
                  <small>
                    {key.key_hint} ·{" "}
                    {t("botModels.keys.models", { count: key.models.length })}
                  </small>
                </span>
                {inUse && list.selected_model ? (
                  <span className={styles.inUse}>
                    <span aria-hidden="true" className={styles.dot} />
                    <ModelName id={list.selected_model} />
                  </span>
                ) : (
                  key.models.length > 0 && (
                    <Select
                      className={styles.useSelect}
                      aria-label={t("botModels.keys.use", { name: key.name })}
                      placeholder={t("botModels.keys.usePlaceholder")}
                      disabled={busy === key.id}
                      value={null}
                      onChange={(model: string) => void use(key, model)}
                      options={key.models.map((m) => ({
                        value: m.id,
                        label: m.name || m.id,
                      }))}
                      popupMatchSelectWidth={false}
                    />
                  )
                )}
                <Popconfirm
                  title={t("botModels.keys.removeConfirm")}
                  okText={t("botModels.keys.remove")}
                  cancelText={t("common.cancel")}
                  onConfirm={() => void remove(key)}
                >
                  <Button
                    type="text"
                    icon={<Trash2 size={15} />}
                    loading={busy === key.id}
                    aria-label={t("botModels.keys.removeNamed", {
                      name: key.name,
                    })}
                  />
                </Popconfirm>
              </li>
            );
          })}
        </ul>
      )}
      {actionError && <Alert type="error" showIcon message={actionError} />}
      <AddModelKeyDialog
        open={adding}
        cloud={cloud}
        onClose={() => setAdding(false)}
        onChanged={changed}
      />
    </section>
  );
}
