// P&L heatmap for a sweep: spread (rows) × skew (columns), each cell coloured by
// total P&L (green = profit, red = loss, intensity = magnitude). Best cell glows.

import type { SweepRow } from "../api/types";
import styles from "./Heatmap.module.css";

export default function Heatmap({ rows }: { rows: SweepRow[] }) {
  const spreads = [...new Set(rows.map((r) => r.spread))].sort((a, b) => a - b);
  const skews = [...new Set(rows.map((r) => r.skew))].sort((a, b) => a - b);

  const map = new Map<string, number>();
  for (const r of rows) {
    const k = `${r.spread}|${r.skew}`;
    const cur = map.get(k);
    map.set(k, cur === undefined ? r.total_pnl : Math.max(cur, r.total_pnl));
  }
  const vals = [...map.values()];
  if (vals.length === 0) return null;
  const maxAbs = Math.max(1e-9, ...vals.map((v) => Math.abs(v)));
  const best = Math.max(...vals);

  const color = (v: number) => {
    const a = 0.12 + 0.8 * Math.min(1, Math.abs(v) / maxAbs);
    return v >= 0 ? `rgba(31,160,90,${a})` : `rgba(214,69,63,${a})`;
  };

  return (
    <div className={styles.wrap} style={{ gridTemplateColumns: `90px repeat(${skews.length}, 1fr)` }}>
      <div className={styles.corner}>spread \ skew</div>
      {skews.map((sk) => <div key={`h${sk}`} className={styles.colh}>{sk}</div>)}
      {spreads.map((sp) => (
        [
          <div key={`r${sp}`} className={styles.rowh}>{sp}</div>,
          ...skews.map((sk) => {
            const v = map.get(`${sp}|${sk}`);
            return (
              <div key={`${sp}-${sk}`}
                className={`${styles.cell} ${v !== undefined && v === best ? styles.best : ""}`}
                style={{ background: v === undefined ? "var(--surface-2)" : color(v) }}
                title={v === undefined ? "" : `spread ${sp}, skew ${sk} → ${v.toFixed(2)} pUSD`}>
                {v === undefined ? "—" : v.toFixed(1)}
              </div>
            );
          }),
        ]
      ))}
    </div>
  );
}
