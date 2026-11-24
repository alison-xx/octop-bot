import { useEffect, useMemo, useState } from "react";
import { Alert, Button, Input, Modal, Radio, Select, Spin } from "antd";
import { ArrowLeft, CheckCircle2, ExternalLink, Plus } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  ownModelKeysApi,
  type OwnKey,
  type OwnKeyList,
  type OwnKeyVendor,
  type OwnKeyVendors,
} from "../../api/modules/ownModelKeys";
import {
  customProviderLogo,
  getProviderDocs,
  getProviderLogo,
  getProviderName,
} from "../../assets/providers";
import { apiErrorMessage } from "../../utils/apiError";
import styles from "./modelSources.module.less";

/** Companies shown first, in this order; the rest sit behind "More vendors". */
export const FEATURED_COMPANIES = [
  "tencent",
  "aliyun",
  "volcengine",
  "deepseek",
  "zhipu",
  "kimi",
  "minimax",
  "siliconflow",
];
/** The plan picked first when a company sells several. */
const PREFERRED_PLAN: Record<string, string> = {
  tencent: "tencent-tokenhub",
  aliyun: "dashscope",
  volcengine: "volcengine-cn",
  zhipu: "zhipu-cn",
  kimi: "kimi-cn",
  minimax: "minimax-cn",
  siliconflow: "siliconflow-cn",
};
const CUSTOM = "custom";

type Company = { id: string; plans: OwnKeyVendor[] };
type Step = "pick" | "key" | "done";

export function groupCompanies(vendors: OwnKeyVendor[]): Company[] {
  const byCompany = new Map<string, OwnKeyVendor[]>();
  for (const v of vendors) {
    const plans = byCompany.get(v.vendor) ?? [];
    plans.push(v);
    byCompany.set(v.vendor, plans);
  }
  const rank = (id: string) => {
    const i = FEATURED_COMPANIES.indexOf(id);
    return i < 0 ? FEATURED_COMPANIES.length : i;
  };
  return [...byCompany.entries()]
    .map(([id, plans]) => {
      const preferred = PREFERRED_PLAN[id];
      return {
        id,
        plans: [...plans].sort(
          (a, b) => Number(b.id === preferred) - Number(a.id === preferred),
        ),
      };
    })
    .sort((a, b) => rank(a.id) - rank(b.id));
}

function useCompanyName() {
  const { t } = useTranslation();
  return (company: Company) => {
    const key = `botModels.company.${company.id}`;
    const named = t(key);
    return named === key
      ? getProviderName(company.plans[0].id, company.plans[0].name, t)
      : named;
  };
}

function VendorLogo({ id, size = 28 }: { id: string; size?: number }) {
  const src = id === CUSTOM ? customProviderLogo : getProviderLogo(id);
  return src ? (
    <img className={styles.logo} src={src} alt="" width={size} height={size} />
  ) : (
    <span
      className={styles.logo}
      style={{ width: size, height: size }}
      aria-hidden="true"
    >
      {id.slice(0, 2).toUpperCase()}
    </span>
  );
}

export { VendorLogo };

/**
 * Add one of the user's own vendor API keys: pick a company, then its plan and the key,
 * then the model to chat on. Lynxce checks nothing here; the vendor's /models does.
 */
export default function AddModelKeyDialog({
  open,
  cloud,
  onClose,
  onChanged,
}: {
  open: boolean;
  /** Octop Bot cloud: keys are kept in the account, and custom URLs are not offered. */
  cloud: boolean;
  onClose: () => void;
  /** A key was added or a model chosen; the caller reloads its list. */
  onChanged: (list?: OwnKeyList) => void;
}) {
  const { t } = useTranslation();
  const companyName = useCompanyName();
  const [catalog, setCatalog] = useState<OwnKeyVendors | null>(null);
  const [loadError, setLoadError] = useState("");
  const [reload, setReload] = useState(0);
  const [step, setStep] = useState<Step>("pick");
  const [more, setMore] = useState(false);
  const [company, setCompany] = useState<Company | null>(null);
  const [planId, setPlanId] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [added, setAdded] = useState<OwnKey | null>(null);
  const [model, setModel] = useState("");

  useEffect(() => {
    if (!open) return;
    let current = true;
    setLoadError("");
    ownModelKeysApi.vendors().then(
      (data) => current && setCatalog(data),
      (e) =>
        current && setLoadError(apiErrorMessage(e, t("octopBot.failed"), t)),
    );
    return () => {
      current = false;
    };
  }, [open, reload, t]);

  const companies = useMemo(
    () => groupCompanies(catalog?.vendors ?? []),
    [catalog],
  );
  const featured = companies.filter((c) => FEATURED_COMPANIES.includes(c.id));
  const others = companies.filter((c) => !FEATURED_COMPANIES.includes(c.id));
  const custom = company?.id === CUSTOM;
  const plan = company?.plans.find((p) => p.id === planId) ?? null;

  const choose = (next: Company) => {
    setCompany(next);
    setPlanId(next.plans[0]?.id ?? "");
    setApiKey("");
    setBaseUrl("");
    setLabel("");
    setError("");
    setStep("key");
  };

  const save = async () => {
    if (busy || !apiKey.trim() || (custom && !baseUrl.trim())) return;
    setBusy(true);
    setError("");
    try {
      const key = await ownModelKeysApi.add(
        custom
          ? {
              vendor: CUSTOM,
              api_key: apiKey.trim(),
              base_url: baseUrl.trim(),
              ...(label.trim() ? { name: label.trim() } : {}),
            }
          : { vendor: planId, api_key: apiKey.trim() },
      );
      setAdded(key);
      setModel(key.models[0]?.id ?? "");
      setStep("done");
      onChanged();
    } catch (e) {
      setError(apiErrorMessage(e, t("octopBot.failed"), t));
    } finally {
      setBusy(false);
    }
  };

  const applyChosenModel = async () => {
    if (!added || !model || busy) return;
    setBusy(true);
    setError("");
    try {
      onChanged(await ownModelKeysApi.useModel(added.id, model));
      onClose();
    } catch (e) {
      setError(apiErrorMessage(e, t("octopBot.failed"), t));
    } finally {
      setBusy(false);
    }
  };

  const tile = (c: Company) => (
    <button
      key={c.id}
      type="button"
      className={styles.vendorTile}
      onClick={() => choose(c)}
    >
      <VendorLogo id={c.plans[0].logo_id} />
      <span>{companyName(c)}</span>
    </button>
  );

  const title =
    step === "pick"
      ? t("botModels.add.title")
      : step === "done"
      ? t("botModels.add.doneTitle")
      : custom
      ? t("botModels.add.customTitle")
      : t("botModels.add.vendorTitle", {
          name: company ? companyName(company) : "",
        });
  const docs = plan
    ? getProviderDocs(plan.id) ?? getProviderDocs(plan.logo_id)
    : undefined;

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      width={560}
      destroyOnClose
      className={styles.dialog}
      title={
        <span className={styles.dialogTitle}>
          {step === "key" && (
            <Button
              type="text"
              size="small"
              icon={<ArrowLeft size={16} />}
              aria-label={t("botModels.add.back")}
              onClick={() => {
                setStep("pick");
                setError("");
              }}
            />
          )}
          {step !== "pick" && company && (
            <VendorLogo
              id={custom ? CUSTOM : company.plans[0].logo_id}
              size={26}
            />
          )}
          {title}
        </span>
      }
    >
      {step === "pick" &&
        (loadError ? (
          <Alert
            type="error"
            message={loadError}
            action={
              <Button onClick={() => setReload((n) => n + 1)}>
                {t("octopBot.retry")}
              </Button>
            }
          />
        ) : !catalog ? (
          <Spin />
        ) : (
          <div className={styles.pick}>
            <p className={styles.muted}>
              {t(cloud ? "botModels.add.hintCloud" : "botModels.add.hintLocal")}
            </p>
            <div className={styles.vendorGrid}>{featured.map(tile)}</div>
            {others.length > 0 &&
              (more ? (
                <div className={styles.vendorGrid}>{others.map(tile)}</div>
              ) : (
                <Button type="link" onClick={() => setMore(true)}>
                  {t("botModels.add.more", { count: others.length })}
                </Button>
              ))}
            {catalog.custom_allowed && (
              <button
                type="button"
                className={`${styles.vendorTile} ${styles.customTile}`}
                onClick={() => choose({ id: CUSTOM, plans: [] })}
              >
                <Plus size={20} aria-hidden="true" />
                <span>{t("botModels.add.custom")}</span>
              </button>
            )}
          </div>
        ))}

      {step === "key" && company && (
        <form
          className={styles.keyForm}
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
          {!custom && company.plans.length > 1 && (
            <>
              <label htmlFor="own-key-plan">{t("botModels.add.plan")}</label>
              <Select
                id="own-key-plan"
                value={planId}
                onChange={setPlanId}
                options={company.plans.map((p) => ({
                  value: p.id,
                  label: getProviderName(p.id, p.name, t),
                }))}
              />
            </>
          )}
          {custom && (
            <>
              <label htmlFor="own-key-url">{t("botModels.add.baseUrl")}</label>
              <Input
                id="own-key-url"
                required
                inputMode="url"
                placeholder="https://api.example.com/v1"
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
              />
              <label htmlFor="own-key-name">{t("botModels.add.name")}</label>
              <Input
                id="own-key-name"
                maxLength={60}
                value={label}
                onChange={(e) => setLabel(e.target.value)}
              />
            </>
          )}
          <label htmlFor="own-key-secret">API Key</label>
          <Input.Password
            id="own-key-secret"
            autoFocus
            required
            autoComplete="off"
            maxLength={4096}
            placeholder={plan?.api_key_prefix ? `${plan.api_key_prefix}…` : ""}
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
          />
          <small className={styles.muted}>
            {t(cloud ? "botModels.add.keptCloud" : "botModels.add.keptLocal")}
          </small>
          {!custom && plan && (
            <small className={styles.muted}>
              {t("botModels.add.endpoint")} <code>{plan.base_url}</code>
              {docs && (
                <>
                  {" · "}
                  <a href={docs} target="_blank" rel="noreferrer">
                    {t("botModels.add.getKey")}
                    <ExternalLink size={12} aria-hidden="true" />
                  </a>
                </>
              )}
            </small>
          )}
          {error && <Alert type="error" showIcon message={error} />}
          <div className={styles.dialogActions}>
            <Button onClick={onClose}>{t("common.cancel")}</Button>
            <Button
              type="primary"
              htmlType="submit"
              loading={busy}
              disabled={!apiKey.trim() || (custom && !baseUrl.trim())}
            >
              {t("botModels.add.verify")}
            </Button>
          </div>
        </form>
      )}

      {step === "done" && added && (
        <div className={styles.keyForm}>
          <div className={styles.success} role="status">
            <CheckCircle2 size={18} aria-hidden="true" />
            {t("botModels.add.found", { count: added.models.length })}
          </div>
          {added.models.length > 0 && (
            <Radio.Group
              className={styles.modelChoices}
              aria-label={t("botModels.add.chooseModel")}
              value={model}
              onChange={(e) => setModel(e.target.value)}
            >
              {added.models.map((m) => (
                <Radio key={m.id} value={m.id}>
                  {m.name || m.id}
                </Radio>
              ))}
            </Radio.Group>
          )}
          {error && <Alert type="error" showIcon message={error} />}
          <div className={styles.dialogActions}>
            <Button onClick={onClose}>{t("botModels.add.later")}</Button>
            <Button
              type="primary"
              loading={busy}
              disabled={!model}
              onClick={() => void applyChosenModel()}
            >
              {t("botModels.add.useModel")}
            </Button>
          </div>
        </div>
      )}
    </Modal>
  );
}
