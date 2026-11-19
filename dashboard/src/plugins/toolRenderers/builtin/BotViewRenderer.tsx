import { lazy, Suspense } from "react";
import { useTranslation } from "react-i18next";
import type { ToolRenderProps } from "../types";
import { BuiltinOctopUiFallback } from "./BuiltinOctopUiFallback";
import styles from "./BotViewRenderer.module.less";
import BotCalculator, { validCalculator } from "./BotCalculator";
import BotHtmlView from "./BotHtmlView";

const BotChart = lazy(() => import("./BotViewChart"));
export type ChartSeries = { name: string; values: number[] };
type Cell = string | number | boolean | null;
const record = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);
const cell = (v: unknown): v is Cell =>
  v === null ||
  typeof v === "string" ||
  typeof v === "boolean" ||
  (typeof v === "number" && Number.isFinite(v));
const textItems = (v: unknown): v is string[] =>
  Array.isArray(v) && v.every((x) => typeof x === "string");
const seriesItem = (v: unknown): v is ChartSeries =>
  record(v) &&
  typeof v.name === "string" &&
  Array.isArray(v.values) &&
  v.values.every((n) => typeof n === "number" && Number.isFinite(n));

export default function BotViewRenderer(props: ToolRenderProps) {
  const { data } = props,
    { t } = useTranslation();
  if (!record(data)) return <BuiltinOctopUiFallback {...props} />;
  const title = typeof data.title === "string" ? data.title : props.displayName;
  let content: React.ReactNode;
  switch (data.kind) {
    case "html":
      if (typeof data.html === "string")
        content = (
          <BotHtmlView html={data.html} title={title || props.toolName} />
        );
      break;
    case "calculator":
      if (validCalculator(data)) content = <BotCalculator data={data} />;
      break;
    case "metrics": {
      if (!Array.isArray(data.metrics)) break;
      const entries = data.metrics.filter(record);
      content = (
        <dl className={styles.metrics}>
          {entries.map((m, i) => (
            <div key={i}>
              <dt>{typeof m.label === "string" ? m.label : ""}</dt>
              <dd>
                {cell(m.value) ? String(m.value ?? "") : ""}
                {typeof m.unit === "string" && <small>{m.unit}</small>}
              </dd>
            </div>
          ))}
        </dl>
      );
      break;
    }
    case "table": {
      if (!textItems(data.columns) || !Array.isArray(data.rows)) break;
      const columns = data.columns,
        rows = data.rows.filter(
          (r): r is Cell[] => Array.isArray(r) && r.every(cell),
        );
      content = (
        <div className={styles.tableScroll}>
          <table aria-label={title}>
            <thead>
              <tr>
                {columns.map((c, i) => (
                  <th scope="col" key={i}>
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>
                  {columns.map((_, j) => (
                    <td key={j}>{String(r[j] ?? "")}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
      break;
    }
    case "chart": {
      if (
        !textItems(data.labels) ||
        !Array.isArray(data.series) ||
        !data.series.every(seriesItem)
      )
        break;
      const labels = data.labels,
        series = data.series;
      content = (
        <>
          <Suspense fallback={null}>
            <BotChart
              labels={labels}
              series={series}
              kind={data.chart_type === "line" ? "line" : "bar"}
            />
          </Suspense>
          <details className={styles.chartData}>
            <summary>{t("octopBot.chartData")}</summary>
            <div className={styles.tableScroll}>
              <table>
                <thead>
                  <tr>
                    <th />
                    {series.map((s, i) => (
                      <th scope="col" key={i}>
                        {s.name}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {labels.map((label, i) => (
                    <tr key={i}>
                      <th scope="row">{label}</th>
                      {series.map((s, j) => (
                        <td key={j}>{s.values[i]}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </>
      );
      break;
    }
    case "form": {
      if (!Array.isArray(data.questions)) break;
      const answers = Array.isArray(data.answers) ? data.answers : [];
      content = (
        <dl className={styles.answers}>
          {data.questions.map((q, i) =>
            record(q) && typeof q.question === "string" ? (
              <div key={i}>
                <dt>{q.question}</dt>
                <dd>
                  {cell(answers[i])
                    ? String(answers[i] ?? "")
                    : t("octopBot.unanswered")}
                </dd>
              </div>
            ) : null,
          )}
        </dl>
      );
      break;
    }
  }
  if (!content) return <BuiltinOctopUiFallback {...props} />;
  return (
    <section className={styles.card} data-octop-view={String(data.kind)}>
      {title && <h3>{title}</h3>}
      {content}
    </section>
  );
}
