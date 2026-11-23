import type { CSSProperties, ReactNode } from "react";
import { Select } from "antd";
import { Check } from "lucide-react";
import { useTranslation } from "react-i18next";
import ModelName, {
  modelBareId,
  modelDisplayName,
  modelVendor,
} from "./ModelName";
import styles from "./modelName.module.less";

export type ModelItem = {
  /** Select value (a channel id or a `provider/model` ref). */
  value: string;
  /** Model id used for the vendor, the friendly name and the secondary text. */
  id: string;
  name?: string | null;
};

type Props = {
  items: ModelItem[];
  value: string | undefined;
  onChange: (value: string) => void;
  /** Options above the vendor groups, e.g. "automatic". */
  lead?: { value: string; label: string }[];
  id?: string;
  className?: string;
  placeholder?: string;
  disabled?: boolean;
  loading?: boolean;
  "aria-label"?: string;
};

/**
 * Searchable model picker: closed it shows the current model's mark and
 * friendly name; open, the search box starts empty and models are grouped by
 * the vendor that made them, the current one ticked.
 */
export default function ModelSelect({
  items,
  value,
  onChange,
  lead = [],
  placeholder,
  ...rest
}: Props) {
  const { t } = useTranslation();
  const row = (key: string, label: ReactNode, sub?: string) => (
    <span className={styles.option}>
      <span className={styles.optionText}>
        <span className={styles.name}>{label}</span>
        {sub && <small>{sub}</small>}
      </span>
      {key === value && <Check className={styles.tick} size={15} />}
    </span>
  );
  const groups = new Map<string, { logo?: string; items: ModelItem[] }>();
  for (const item of items) {
    const vendor = modelVendor(`${item.id} ${item.name ?? ""}`);
    const key = vendor?.key ?? "other";
    if (!groups.has(key)) groups.set(key, { logo: vendor?.logo, items: [] });
    groups.get(key)!.items.push(item);
  }
  const ordered = [...groups].sort(
    ([a], [b]) => Number(a === "other") - Number(b === "other"),
  );
  const options = [
    ...lead.map((o) => ({
      value: o.value,
      search: o.label,
      label: row(o.value, o.label),
    })),
    ...ordered.map(([key, group]) => ({
      label: (
        <span className={styles.group}>
          {group.logo && <img src={group.logo} alt="" width={14} height={14} />}
          {t("octopBot.modelVendor." + key)}
        </span>
      ),
      title: t("octopBot.modelVendor." + key),
      options: group.items.map((item) => ({
        value: item.value,
        title: item.id,
        search: `${item.id} ${modelDisplayName(item.id, item.name)}`,
        label: row(
          item.value,
          modelDisplayName(item.id, item.name),
          modelBareId(item.id),
        ),
      })),
    })),
  ];
  const byValue = new Map(items.map((item) => [item.value, item]));
  return (
    <Select
      {...rest}
      // Open, the current value gives way to a "search models" hint (CSS) so
      // the search box reads empty instead of showing the value greyed out.
      className={[styles.picker, rest.className].filter(Boolean).join(" ")}
      style={
        {
          "--model-search": JSON.stringify(t("octopBot.searchModels")),
        } as CSSProperties
      }
      showSearch
      optionFilterProp="search"
      value={value}
      placeholder={placeholder}
      onChange={(next: string) => onChange(next)}
      options={options}
      labelRender={({ value: current }) => {
        const item = byValue.get(String(current));
        if (item) return <ModelName id={item.id} name={item.name} />;
        return lead.find((o) => o.value === current)?.label ?? String(current);
      }}
    />
  );
}
