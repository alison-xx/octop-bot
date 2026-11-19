import { useId, useMemo, useState } from "react";
import { Alert, InputNumber, Select, Slider, Switch } from "antd";
import {
  compileFormula,
  createScope,
  evaluate,
  show,
  type FormulaTree,
  type FormulaValue,
} from "../../../vendor/deep-view/formula.js";
import styles from "./BotViewRenderer.module.less";

interface Control {
  type: "number" | "slider" | "choice" | "toggle";
  id: string;
  label: string;
  value: FormulaValue;
  min?: number | null;
  max?: number | null;
  step?: number | null;
  options?: { label: string; value: FormulaValue }[];
}
interface Metric {
  label: string;
  value: { "=": string };
  unit?: string;
}
export interface CalculatorData {
  inputs: Control[];
  metrics: Metric[];
  let?: Record<string, string>;
}
const object = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value);
const scalar = (value: unknown) =>
  typeof value === "string" ||
  typeof value === "boolean" ||
  (typeof value === "number" && Number.isFinite(value));
export function validCalculator(
  data: Record<string, unknown>,
): data is Record<string, unknown> & CalculatorData {
  return (
    Array.isArray(data.inputs) &&
    data.inputs.every(
      (c) =>
        object(c) &&
        ["number", "slider", "choice", "toggle"].includes(String(c.type)) &&
        typeof c.id === "string" &&
        typeof c.label === "string" &&
        scalar(c.value) &&
        (c.options == null ||
          (Array.isArray(c.options) &&
            c.options.every(
              (o) =>
                object(o) && typeof o.label === "string" && scalar(o.value),
            ))),
    ) &&
    Array.isArray(data.metrics) &&
    data.metrics.every(
      (m) =>
        object(m) &&
        typeof m.label === "string" &&
        object(m.value) &&
        typeof m.value["="] === "string",
    ) &&
    (data.let == null ||
      (object(data.let) &&
        Object.values(data.let).every((value) => typeof value === "string")))
  );
}
export default function BotCalculator({ data }: { data: CalculatorData }) {
  const id = useId();
  const [edited, setEdited] = useState<Map<string, FormulaValue>>(
    () => new Map(),
  );
  const definitions = useMemo(() => {
    const trees = new Map<string, FormulaTree>();
    for (const [name, source] of Object.entries(data.let ?? {})) {
      const parsed = compileFormula(source);
      if ("error" in parsed) return { error: parsed.error };
      trees.set(name, parsed.tree);
    }
    return {
      trees,
      metrics: data.metrics.map((m) => compileFormula(m.value["="])),
    };
  }, [data]);
  const inputs = new Map(
    data.inputs.map((input) => [input.id, edited.get(input.id) ?? input.value]),
  );
  const change = (key: string, value: FormulaValue) =>
    setEdited((prev) => new Map(prev).set(key, value));
  if (!definitions.trees || !definitions.metrics)
    return <Alert type="error" message={definitions.error} />;
  const scope = createScope(inputs, definitions.trees);
  return (
    <div className={styles.calculator}>
      <div className={styles.controls}>
        {data.inputs.map((input) => {
          const labelId = id + input.id;
          const value = inputs.get(input.id)!;
          return (
            <div key={input.id}>
              <label id={labelId}>{input.label}</label>
              {input.type === "toggle" ? (
                <Switch
                  aria-labelledby={labelId}
                  checked={value === true}
                  onChange={(v) => change(input.id, v)}
                />
              ) : input.type === "choice" ? (
                <Select
                  aria-labelledby={labelId}
                  value={input.options?.findIndex(
                    (option) => option.value === value,
                  )}
                  options={input.options?.map((option, i) => ({
                    label: option.label,
                    value: i,
                  }))}
                  onChange={(i) => {
                    const v = input.options?.[i]?.value;
                    if (v !== undefined) change(input.id, v);
                  }}
                />
              ) : input.type === "slider" ? (
                <Slider
                  ariaLabelledByForHandle={labelId}
                  value={Number(value)}
                  min={input.min ?? 0}
                  max={input.max ?? 100}
                  step={input.step ?? 1}
                  onChange={(v) => change(input.id, v)}
                />
              ) : (
                <InputNumber
                  aria-labelledby={labelId}
                  value={Number(value)}
                  min={input.min ?? undefined}
                  max={input.max ?? undefined}
                  step={input.step ?? 1}
                  onChange={(v) => {
                    if (typeof v === "number") change(input.id, v);
                  }}
                />
              )}
            </div>
          );
        })}
      </div>
      <dl className={styles.metrics} aria-live="polite">
        {data.metrics.map((metric, i) => {
          const parsed = definitions.metrics[i],
            result = "error" in parsed ? parsed : evaluate(parsed.tree, scope);
          return (
            <div key={i}>
              <dt>{metric.label}</dt>
              <dd>
                {"error" in result ? (
                  <small>{result.error}</small>
                ) : (
                  <>
                    {show(result.value)}
                    <small>{metric.unit}</small>
                  </>
                )}
              </dd>
            </div>
          );
        })}
      </dl>
    </div>
  );
}
