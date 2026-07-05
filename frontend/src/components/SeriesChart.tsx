// A small theme-aware line chart (recharts) used for equity / inventory / price.
// Colors come from CSS variables so it adapts to light/dark automatically.

import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

export interface LineDef { key: string; color: string; name: string; }

export default function SeriesChart({
  data, lines, height = 240,
}: {
  data: Record<string, number>[];
  lines: LineDef[];
  height?: number;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -10 }}>
        <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
        <XAxis dataKey="t" tick={{ fill: "var(--text-muted)", fontSize: 11 }} stroke="var(--border)" />
        <YAxis tick={{ fill: "var(--text-muted)", fontSize: 11 }} stroke="var(--border)" width={50} />
        <Tooltip
          contentStyle={{ background: "var(--surface)", border: "1px solid var(--border-strong)", borderRadius: 8, fontSize: 12 }}
          labelStyle={{ color: "var(--text-muted)" }}
        />
        {lines.map((l) => (
          <Line key={l.key} type="monotone" dataKey={l.key} name={l.name}
                stroke={l.color} dot={false} strokeWidth={2} isAnimationActive={false} />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}
