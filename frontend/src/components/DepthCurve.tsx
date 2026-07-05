// Classic cumulative depth chart: for each price, how much size you'd sweep.
// Bids (green) rise toward the mid from the left; asks (magenta) from the right —
// the "valley" between them is the spread.

import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Level } from "../api/types";

export default function DepthCurve({ bids, asks, height = 220 }: { bids: Level[]; asks: Level[]; height?: number }) {
  // Bids: cumulate from the best (highest) price downward.
  const b = [...bids].sort((x, z) => z[0] - x[0]);
  let cb = 0;
  const bidPts = b.map(([p, s]) => ({ price: p, bid: (cb += s) }));
  // Asks: cumulate from the best (lowest) price upward.
  const a = [...asks].sort((x, z) => x[0] - z[0]);
  let ca = 0;
  const askPts = a.map(([p, s]) => ({ price: p, ask: (ca += s) }));

  const data = [...bidPts, ...askPts].sort((x, z) => x.price - z.price);
  if (data.length < 2) return <p className="muted small">Not enough depth to chart yet.</p>;

  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -6 }}>
        <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
        <XAxis dataKey="price" type="number" domain={["dataMin", "dataMax"]}
               tick={{ fill: "var(--text-muted)", fontSize: 11 }} stroke="var(--border)"
               tickFormatter={(v) => Number(v).toFixed(3)} />
        <YAxis tick={{ fill: "var(--text-muted)", fontSize: 11 }} stroke="var(--border)" width={48} />
        <Tooltip contentStyle={{ background: "var(--surface)", border: "1px solid var(--border-strong)", borderRadius: 8, fontSize: 12 }}
                 labelFormatter={(v) => `price ${Number(v).toFixed(3)}`} />
        <Area type="stepAfter" dataKey="bid" name="bid depth" stroke="var(--green)" fill="var(--green-weak)" connectNulls={false} isAnimationActive={false} />
        <Area type="stepBefore" dataKey="ask" name="ask depth" stroke="var(--red)" fill="var(--red-weak)" connectNulls={false} isAnimationActive={false} />
      </AreaChart>
    </ResponsiveContainer>
  );
}
