// Up/Down Threshold Lab: a LIVE view of the offline analyzer. It polls the
// collected updown_*.jsonl data through /updown/grid and renders the edge grid
// (dip threshold × how early you entered) as a heatmap — green = profitable edge,
// red = loss. Click any cell to see that rule's cumulative-P&L (equity) curve.
// Auto-refreshes while the collector keeps writing, so the grid updates in place.
// SIMULATION ONLY — this analyses recorded data, it never trades.

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type UpDownParams } from "../api/client";
import SeriesChart from "../components/SeriesChart";
import styles from "./UpDownLab.module.css";

const REFRESH_MS = 8000;

export default function UpDownLab() {
  const [windowLen, setWindowLen] = useState(5);
  const [maxSpread, setMaxSpread] = useState(0.05);
  const [fillLag, setFillLag] = useState(0);
  const [minSize, setMinSize] = useState(0);
  const [file, setFile] = useState(""); // "" = newest
  const [auto, setAuto] = useState(true);
  const [sel, setSel] = useState<{ thr: number; win: number } | null>(null);

  const params: UpDownParams = { window_len: windowLen, max_spread: maxSpread, fill_lag: fillLag, min_size: minSize, file: file || undefined };

  const files = useQuery({ queryKey: ["updownFiles"], queryFn: api.updownFiles });
  const grid = useQuery({
    queryKey: ["updownGrid", params],
    queryFn: () => api.updownGrid(params),
    refetchInterval: auto ? REFRESH_MS : false,
  });
  const eq = useQuery({
    queryKey: ["updownEquity", params, sel],
    queryFn: () => api.updownEquity({ ...params, thr: sel!.thr, win: sel!.win }),
    enabled: !!sel,
    refetchInterval: auto && sel ? REFRESH_MS : false,
  });

  // On first data (or after a param change clears it), auto-select the best cell.
  useEffect(() => {
    const g = grid.data;
    if (!g || sel) return;
    let best: { thr: number; win: number } | null = null;
    let bestEdge = -Infinity;
    g.grid.forEach((row, i) =>
      row.forEach((c, j) => {
        if (c.edge !== null && c.bets >= g.min_sample && c.edge > bestEdge) {
          bestEdge = c.edge;
          best = { thr: g.thresholds[i], win: g.windows[j] };
        }
      }),
    );
    if (best) setSel(best);
  }, [grid.data, sel]);

  const changeWindow = (v: number) => { setWindowLen(v); setSel(null); }; // entry windows differ

  const maxAbs = useMemo(() => {
    if (!grid.data) return 1;
    const vals = grid.data.grid.flat().map((c) => c.edge).filter((e): e is number => e !== null).map(Math.abs);
    return Math.max(1e-9, ...vals, 1);
  }, [grid.data]);

  const color = (edge: number | null) => {
    if (edge === null) return "var(--surface-2)";
    const a = 0.12 + 0.8 * Math.min(1, Math.abs(edge) / maxAbs);
    return edge >= 0 ? `rgba(31,160,90,${a})` : `rgba(214,69,63,${a})`;
  };

  const g = grid.data;
  const bestKey = useMemo(() => {
    if (!g) return "";
    let k = "", bv = -Infinity;
    g.grid.forEach((row, i) => row.forEach((c, j) => {
      if (c.edge !== null && c.bets >= g.min_sample && c.edge > bv) { bv = c.edge; k = `${i}-${j}`; }
    }));
    return k;
  }, [g]);

  const eqData = eq.data ? eq.data.cum.map((v, i) => ({ t: i + 1, pnl: v, zero: 0 })) : [];

  return (
    <div className="col">
      <div className="row spread center wrap">
        <h1 style={{ margin: 0 }}>Up/Down Threshold Lab</h1>
        {g && (
          <span className={styles.live}>
            {auto && <span className={styles.dot} />}
            <span className="small muted">
              {g.file} · {g.buckets} buckets{g.base_up_rate !== null && ` · base Up ${(g.base_up_rate * 100).toFixed(1)}%`}
              {grid.isFetching && " · updating…"}
            </span>
          </span>
        )}
      </div>
      <p className="muted small">
        Live edge grid over your recorded data — edge = hit% − price paid, in points. Green = profitable, red = loss.
        Click a cell for its equity curve. Simulation only.
      </p>

      <div className="card col">
        <div className="row center wrap">
          <Field label="market length">
            <div className="row" style={{ gap: 6 }}>
              {[5, 15, 60].map((w) => (
                <button key={w} className={`btn ${windowLen === w ? "btn-primary" : ""}`} onClick={() => changeWindow(w)}>{w}m</button>
              ))}
            </div>
          </Field>
          <Field label="max spread"><input type="number" value={maxSpread} step={0.01} min={0} style={{ width: 90 }} onChange={(e) => setMaxSpread(+e.target.value)} /></Field>
          <Field label="fill lag (s)"><input type="number" value={fillLag} step={6} min={0} style={{ width: 80 }} onChange={(e) => setFillLag(+e.target.value)} /></Field>
          <Field label="min size"><input type="number" value={minSize} step={1} min={0} style={{ width: 80 }} onChange={(e) => setMinSize(+e.target.value)} /></Field>
          <Field label="data file">
            <select value={file} onChange={(e) => setFile(e.target.value)}>
              <option value="">newest</option>
              {(files.data ?? []).map((f) => <option key={f.name} value={f.name}>{f.name}</option>)}
            </select>
          </Field>
          <Field label="auto-refresh">
            <button className={`btn ${auto ? "btn-primary" : ""}`} onClick={() => setAuto((a) => !a)}>{auto ? "on" : "off"}</button>
          </Field>
        </div>
      </div>

      {grid.isError && <div className="card neg">Couldn't load data: {(grid.error as Error).message}</div>}
      {g && g.buckets === 0 && <div className="card muted">No {windowLen}-minute buckets in this file yet — let the collector run, or pick another length.</div>}

      {g && g.buckets > 0 && (
        <div className="card col">
          <div className="row spread center wrap">
            <h2 style={{ margin: 0 }}>Edge grid (pp)</h2>
            <div className={styles.legend}>
              <span>loss</span>
              <span className={styles.swatch} style={{ background: color(-maxAbs) }} />
              <span className={styles.swatch} style={{ background: "var(--surface-2)" }} />
              <span className={styles.swatch} style={{ background: color(maxAbs) }} />
              <span>profit · ★ best · click a cell</span>
            </div>
          </div>

          <div className="small muted">entered within (minutes into the bucket) →</div>
          <div className={styles.grid} style={{ gridTemplateColumns: `72px repeat(${g.windows.length}, 1fr)` }}>
            <div className={styles.corner}>dip ↓ / min →</div>
            {g.windows.map((w) => <div key={`h${w}`} className={styles.colh}>≤{w}m</div>)}
            {g.grid.map((row, i) => [
              <div key={`r${i}`} className={styles.rowh}>{g.thresholds[i].toFixed(2)}</div>,
              ...row.map((c, j) => {
                const isSel = sel?.thr === g.thresholds[i] && sel?.win === g.windows[j];
                const isEmpty = c.edge === null;
                return (
                  <div key={`${i}-${j}`}
                    className={`${styles.cell} ${isEmpty ? styles.empty : ""} ${isSel ? styles.sel : ""}`}
                    style={{ background: color(c.edge) }}
                    onClick={() => !isEmpty && setSel({ thr: g.thresholds[i], win: g.windows[j] })}
                    title={isEmpty ? "no bets" : `dip ≤ ${g.thresholds[i]}, entered ≤ ${g.windows[j]}m → edge ${c.edge!.toFixed(1)}pp over ${c.bets} bets`}>
                    {`${i}-${j}` === bestKey && <span className={styles.star}>★</span>}
                    <span>{isEmpty ? "—" : `${c.edge! >= 0 ? "+" : ""}${c.edge!.toFixed(1)}`}</span>
                    {!isEmpty && <span className={styles.n}>n={c.bets}</span>}
                  </div>
                );
              }),
            ])}
          </div>
          <div className="small muted">↑ dip threshold required · cells below {g.min_sample} bets are noisy</div>
        </div>
      )}

      {sel && eq.data && (
        <div className="card col">
          <div className="row spread center wrap">
            <h2 style={{ margin: 0 }}>Equity curve — dip ≤ {sel.thr}, entered ≤ {sel.win}m</h2>
            <span className="small muted">{eq.data.first} → {eq.data.last}</span>
          </div>
          <div className={styles.chips}>
            <Chip label="bets" value={String(eq.data.n)} />
            <Chip label="hit rate" value={eq.data.hit !== null ? `${eq.data.hit}%` : "—"} />
            <Chip label="final P&L" value={`${eq.data.final >= 0 ? "+" : ""}${eq.data.final.toFixed(1)}`} cls={eq.data.final >= 0 ? "pos" : "neg"} />
            <Chip label="worst drawdown" value={`-${eq.data.max_drawdown.toFixed(1)}`} cls="neg" />
          </div>
          <SeriesChart
            data={eqData}
            lines={[
              { key: "zero", color: "var(--border-strong)", name: "0" },
              { key: "pnl", color: eq.data.final >= 0 ? "var(--accent)" : "var(--red)", name: "cumulative P&L" },
            ]}
            height={260}
          />
          <div className="small muted">x = bet number in time order · y = cumulative P&L ($1 stakes). A real edge grinds upward; a random walk wanders across zero.</div>
        </div>
      )}
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return <div><label>{label}</label>{children}</div>;
}

function Chip({ label, value, cls }: { label: string; value: string; cls?: string }) {
  return (
    <div className={styles.chip}>
      <div className={styles.lbl}>{label}</div>
      <div className={`${styles.val} ${cls ?? ""}`}>{value}</div>
    </div>
  );
}
