import type { CSSProperties, ReactNode } from "react";
import { Select } from "antd";
import { Check } from "lucide-react";
import { useTranslation } from "react-i18next";
import ModelName, { modelBareId, modelVendor } from "./ModelName";
import { choiceValue, groupModelItems } from "./modelLines";
import styles from "./modelName.module.less";

export type ModelItem = {
  /** Select value (a channel id or a `provider/model` ref). */
  value: string;
  /** Model id used for the vendor, the friendly name and the secondary text. */
  id: string;
  name?: string | null;
  /** Items only merge into one model with routes inside the same group (e.g. provider). */
  group?: string;
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
 * the vendor that made them, the current one ticked. A model served by
 * several routes is listed once; when it is the current one, 线路 1/2/3
 * below the picker switch between its routes (as in Lynxce's picker).
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
  const row = (selected: boolean, label: ReactNode, sub?: string) => (
    <span className={styles.option}>
      <span className={styles.optionText}>
        <span className={styles.name}>{label}</span>
        {sub && <small>{sub}</small>}
      </span>
      {selected && <Check className={styles.tick} size={15} />}
    </span>
  );
  const choices = groupModelItems(items);
  const groups = new Map<string, { logo?: string; choices: typeof choices }>();
  for (const choice of choices) {
    const first = choice.routes[0];
    if (!groups.has(choice.vendor))
      groups.set(choice.vendor, {
        logo: modelVendor(`${first.id} ${first.name ?? ""}`)?.logo,
        choices: [],
      });
    groups.get(choice.vendor)!.choices.push(choice);
  }
  const ordered = [...groups].sort(
    ([a], [b]) => Number(a === "other") - Number(b === "other"),
  );
  const options = [
    ...lead.map((o) => ({
      value: o.value,
      search: o.label,
      label: row(o.value === value, o.label),
    })),
    ...ordered.map(([key, group]) => ({
      label: (
        <span className={styles.group}>
          {group.logo && <img src={group.logo} alt="" width={14} height={14} />}
          {t("octopBot.modelVendor." + key)}
        </span>
      ),
      title: t("octopBot.modelVendor." + key),
      options: group.choices.map((choice) => {
        const multi = choice.routes.length > 1;
        return {
          value: choiceValue(choice, value),
          title: choice.name,
          search: [choice.name, ...choice.routes.map((r) => r.id)].join(" "),
          label: row(
            choice.routes.some((r) => r.value === value),
            choice.name,
            multi
              ? t("octopBot.modelRoutes", { n: choice.routes.length })
              : modelBareId(choice.routes[0].id),
          ),
        };
      }),
    })),
  ];
  const byValue = new Map(items.map((item) => [item.value, item]));
  const current = choices.find((c) => c.routes.some((r) => r.value === value));
  return (
    <>
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
        labelRender={({ value: shown }) => {
          const item = byValue.get(String(shown));
          if (item) return <ModelName id={item.id} name={item.name} />;
          return lead.find((o) => o.value === shown)?.label ?? String(shown);
        }}
      />
      {current && current.routes.length > 1 && (
        <span
          className={styles.routes}
          role="group"
          aria-label={t("octopBot.modelRoute")}
        >
          {current.routes.map((route, i) => (
            <button
              key={route.value}
              type="button"
              title={modelBareId(route.id)}
              aria-pressed={route.value === value}
              disabled={rest.disabled}
              onClick={() => route.value !== value && onChange(route.value)}
            >
              {t("octopBot.modelRouteN", { n: i + 1 })}
            </button>
          ))}
        </span>
      )}
    </>
  );
}
