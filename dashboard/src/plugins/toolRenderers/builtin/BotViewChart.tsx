import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ChartSeries } from "./BotViewRenderer";

const colors = [
  "var(--fn-text-brand)",
  "#3182b8",
  "#6b59ba",
  "#168472",
  "#b16d19",
  "#b34768",
];
export default function BotViewChart({
  labels,
  series,
  kind,
}: {
  labels: string[];
  series: ChartSeries[];
  kind: "line" | "bar";
}) {
  const rows = labels.map((label, i) => ({
    label,
    ...Object.fromEntries(series.map((s, j) => ["v" + j, s.values[i]])),
  }));
  const Chart = kind === "line" ? LineChart : BarChart;
  return (
    <div style={{ width: "100%", minWidth: 0, height: 230 }}>
      <ResponsiveContainer width="100%" height="100%">
        <Chart data={rows} margin={{ top: 10, right: 16, left: 2, bottom: 3 }}>
          <CartesianGrid stroke="var(--fn-border-primary)" vertical={false} />
          <XAxis
            dataKey="label"
            tick={{ fontSize: 11, fill: "var(--fn-text-secondary)" }}
          />
          <YAxis
            width={54}
            tick={{ fontSize: 11, fill: "var(--fn-text-secondary)" }}
          />
          <Tooltip
            contentStyle={{
              background: "var(--fn-bg-elevated)",
              color: "var(--fn-text-primary)",
              borderColor: "var(--fn-border-primary)",
            }}
          />
          <Legend />
          {series.map((s, j) =>
            kind === "line" ? (
              <Line
                key={j}
                name={s.name}
                dataKey={"v" + j}
                stroke={colors[j % colors.length]}
                strokeWidth={2}
                isAnimationActive={false}
              />
            ) : (
              <Bar
                key={j}
                name={s.name}
                dataKey={"v" + j}
                fill={colors[j % colors.length]}
                maxBarSize={46}
                isAnimationActive={false}
              />
            ),
          )}
        </Chart>
      </ResponsiveContainer>
    </div>
  );
}
