// Backtest & Analytics: run a backtest (history or recording), then show the
// scorecard (with learn tooltips) and equity / inventory / price charts.

import { useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { BacktestResult, StrategyParams, SummaryRow } from "../api/types";
import { useSelection } from "../state/SelectionContext";
import { useToast } from "../components/Toast";
import SeriesChart from "../components/SeriesChart";
import InfoTip from "../components/InfoTip";
import { explainResult } from "../content/explain";

const DEFAULTS: StrategyParams = { spread: 0.02, size: 100, skew: 0.005, widen: 0.005, requote: 0.002 };
const r4 = (x: number) => Math.round(x * 1e4) / 1e4;

export default function Analytics() {
  const { tokenId } = useSelection();
  const toast = useToast();
  const [src, setSrc] = useState("history");
  const [interval, setIntervalV] = useState("1d");
  const [fidelity, setFidelity] = useState(30);
  const [recording, setRecording] = useState("");
  const [params, setParams] = useState<StrategyParams>(DEFAULTS);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [running, setRunning] = useState(false);
  const [err, setErr] = useState("");

  const recordings = useQuery({ queryKey: ["recordings"], queryFn: api.recordings });

  const run = async () => {
    setErr(""); setRunning(true);
    try {
      const res = src === "history"
        ? await api.backtestHistory(tokenId!, interval, fidelity, params)
        : await api.backtestRecording(recording, params);
      setResult(res);
      toast("Backtest complete", "success");
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  };

  const rows = result
    ? result.series.t.map((t, i) => ({
        t: Math.round(t),
        total: r4(result.series.total[i]),
        realized: r4(result.series.realized[i]),
        unrealized: r4(result.series.unrealized[i]),
        position: r4(result.series.position[i]),
        mid: result.series.mid[i],
      }))
    : [];

  const canRun = !running && (src === "history" ? !!tokenId : !!recording);

  return (
    <div className="col">
      <h1>Backtest & Analytics</h1>
      <p className="muted small">Optimistic touch-cross fill model — use P&L to compare settings, not as a promise.</p>

      <div className="card col">
        <div className="row center wrap">
          <Seg value={src} onChange={setSrc} options={[["history", "History"], ["recording", "Recording"]]} />
          {src === "history" ? (
            <>
              <span className="small muted">token: {tokenId ? `${tokenId.slice(0, 14)}…` : "select a market in Explorer"}</span>
              <Field label="interval">
                <select value={interval} onChange={(e) => setIntervalV(e.target.value)}>
                  {["1h", "6h", "1d", "1w", "max"].map((o) => <option key={o}>{o}</option>)}
                </select>
              </Field>
              <Field label="fidelity (min)">
                <input type="number" value={fidelity} min={1} max={60} style={{ width: 80 }}
                       onChange={(e) => setFidelity(+e.target.value)} />
              </Field>
            </>
          ) : (
            <Field label="recording">
              <select value={recording} onChange={(e) => setRecording(e.target.value)}>
                <option value="">choose…</option>
                {(recordings.data ?? []).map((rec) => <option key={rec.name} value={rec.name}>{rec.name}</option>)}
              </select>
            </Field>
          )}
        </div>

        <div className="row wrap">
          <NumField label="spread" term="spread" value={params.spread} step={0.002} onChange={(v) => setParams({ ...params, spread: v })} />
          <NumField label="size" value={params.size} step={10} onChange={(v) => setParams({ ...params, size: v })} />
          <NumField label="skew" term="skew" value={params.skew} step={0.001} onChange={(v) => setParams({ ...params, skew: v })} />
          <NumField label="widen" term="widen" value={params.widen} step={0.001} onChange={(v) => setParams({ ...params, widen: v })} />
          <NumField label="requote" term="requote" value={params.requote} step={0.001} onChange={(v) => setParams({ ...params, requote: v })} />
        </div>

        <div className="row center">
          <button className="btn btn-primary" disabled={!canRun} onClick={run}>{running ? "Running…" : "Run backtest"}</button>
          {err && <span className="neg small">{err}</span>}
        </div>
      </div>

      {result && (
        <>
          <Scorecard s={result.summary} />
          <div className="card" style={{ borderLeft: "3px solid var(--accent)" }}>
            <h2>💡 What happened?</h2>
            <p className="muted" style={{ margin: 0, fontSize: 14, lineHeight: 1.5 }}>{explainResult(result.summary, result.series)}</p>
          </div>
          <div className="card">
            <h2>Equity curve</h2>
            <SeriesChart data={rows} lines={[
              { key: "total", color: "var(--text)", name: "total" },
              { key: "realized", color: "var(--green)", name: "realized" },
              { key: "unrealized", color: "var(--amber)", name: "unrealized" },
            ]} />
          </div>
          <div className="row wrap">
            <div className="card" style={{ flex: 1, minWidth: 300 }}>
              <h2>Inventory</h2>
              <SeriesChart data={rows} height={200} lines={[{ key: "position", color: "var(--accent)", name: "position" }]} />
            </div>
            <div className="card" style={{ flex: 1, minWidth: 300 }}>
              <h2>Mid price</h2>
              <SeriesChart data={rows} height={200} lines={[{ key: "mid", color: "var(--accent)", name: "mid" }]} />
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function Scorecard({ s }: { s: SummaryRow }) {
  const cell = (label: ReactNode, value: string, cls?: string) => (
    <div className="card" style={{ padding: "var(--s3) var(--s4)" }}>
      <div className="small muted">{label}</div>
      <div className={cls} style={{ fontSize: 20, fontWeight: 700 }}>{value}</div>
    </div>
  );
  const sign = (x: number) => `${x >= 0 ? "+" : ""}${x.toFixed(4)}`;
  return (
    <div className="grid" style={{ gridTemplateColumns: "repeat(4, 1fr)" }}>
      {cell("Total P&L", sign(s.total_pnl), s.total_pnl >= 0 ? "pos" : "neg")}
      {cell(<>Realized P&L <InfoTip term="realized-pnl" /></>, sign(s.realized_pnl))}
      {cell(<>Unrealized <InfoTip term="unrealized-pnl" /></>, sign(s.unrealized_pnl))}
      {cell(<>Fills <InfoTip term="fill" /></>, String(s.fills))}
      {cell(<>Win rate <InfoTip term="win-rate" /></>, `${Math.round(s.win_rate * 100)}%`)}
      {cell("Spread captured", s.avg_spread_captured.toFixed(5))}
      {cell(<>Max drawdown <InfoTip term="drawdown" /></>, s.max_drawdown.toFixed(4))}
      {cell(<>Sharpe <InfoTip term="sharpe" /></>, s.sharpe.toFixed(3))}
    </div>
  );
}

function Seg({ value, onChange, options }: { value: string; onChange: (v: string) => void; options: [string, string][] }) {
  return (
    <div className="row" style={{ gap: 6 }}>
      {options.map(([v, label]) => (
        <button key={v} className={`btn ${value === v ? "btn-primary" : ""}`} onClick={() => onChange(v)}>{label}</button>
      ))}
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return <div><label>{label}</label>{children}</div>;
}

function NumField({ label, term, value, step, onChange }:
  { label: string; term?: string; value: number; step: number; onChange: (v: number) => void }) {
  return (
    <div>
      <label>{label}{term && <InfoTip term={term} />}</label>
      <input type="number" value={value} step={step} style={{ width: 96 }} onChange={(e) => onChange(+e.target.value)} />
    </div>
  );
}
