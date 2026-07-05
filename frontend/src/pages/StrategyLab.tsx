// Strategy Lab: run the market-making sim against the LIVE book and watch P&L,
// inventory and fills stream in real time over /ws/sim. Simulation only.

import { useState, type ReactNode } from "react";
import type { StrategyParams } from "../api/types";
import { useSelection } from "../state/SelectionContext";
import { useSimStream } from "../hooks/useSimStream";
import MarketBar from "../components/MarketBar";
import SeriesChart from "../components/SeriesChart";
import AnimatedNumber from "../components/AnimatedNumber";
import InfoTip from "../components/InfoTip";

const DEFAULTS: StrategyParams = { spread: 0.02, size: 100, skew: 0.005, widen: 0.005, requote: 0.002 };
const r4 = (x: number) => Math.round(x * 1e4) / 1e4;

export default function StrategyLab() {
  const { tokenId, market, outcome } = useSelection();
  const [params, setParams] = useState<StrategyParams>(DEFAULTS);
  const [duration, setDuration] = useState(60);
  const [running, setRunning] = useState(false);
  const { frame, connected } = useSimStream(tokenId, params, duration, running, () => setRunning(false));

  if (!tokenId) {
    return <div><h1>Strategy Lab</h1><div className="card muted">Select a market in the Market Explorer first.</div></div>;
  }

  const s = frame?.summary;
  const series = frame?.series;
  const rows = series
    ? series.t.map((t, i) => ({
        t: Math.round(t), total: r4(series.total[i]), realized: r4(series.realized[i]),
        unrealized: r4(series.unrealized[i]), position: r4(series.position[i]),
      }))
    : [];

  return (
    <div className="col">
      <h1>Strategy Lab — live simulation</h1>
      <p className="muted small">Simulated fills against the REAL live book — no real orders. Optimistic fill model, so read P&L as indicative.</p>
      <div className="muted small">{market?.question} [{outcome}]</div>
      <MarketBar tokenId={tokenId} />

      <div className="card col">
        <div className="row wrap">
          <NumField label="spread" term="spread" value={params.spread} step={0.002} disabled={running} onChange={(v) => setParams({ ...params, spread: v })} />
          <NumField label="size" value={params.size} step={10} disabled={running} onChange={(v) => setParams({ ...params, size: v })} />
          <NumField label="skew" term="skew" value={params.skew} step={0.001} disabled={running} onChange={(v) => setParams({ ...params, skew: v })} />
          <NumField label="widen" term="widen" value={params.widen} step={0.001} disabled={running} onChange={(v) => setParams({ ...params, widen: v })} />
          <NumField label="requote" term="requote" value={params.requote} step={0.001} disabled={running} onChange={(v) => setParams({ ...params, requote: v })} />
          <Field label="duration (s, 0 = until Stop)">
            <input type="number" value={duration} min={0} max={3600} step={10} style={{ width: 130 }} disabled={running} onChange={(e) => setDuration(+e.target.value)} />
          </Field>
        </div>
        <div className="row center">
          {!running
            ? <button className="btn btn-primary" onClick={() => setRunning(true)}>▶ Start simulation</button>
            : <button className="btn btn-danger" onClick={() => setRunning(false)}>⏹ Stop</button>}
          <span className="small muted">{running ? (connected ? "🟢 live" : "connecting…") : "idle"}</span>
        </div>
      </div>

      {running && (!frame || frame.waiting) && <div className="card muted">Waiting for the first book update…</div>}

      {s && (
        <>
          <div className="grid" style={{ gridTemplateColumns: "repeat(5, 1fr)" }}>
            <Kpi label="Position" value={s.position.toFixed(0)} />
            <Kpi label={<>Realized <InfoTip term="realized-pnl" /></>} num={s.realized_pnl} />
            <Kpi label={<>Unrealized <InfoTip term="unrealized-pnl" /></>} num={s.unrealized_pnl} />
            <Kpi label="Total P&L" num={s.total_pnl} cls={s.total_pnl >= 0 ? "pos" : "neg"} />
            <Kpi label={<>Fills <InfoTip term="fill" /></>} value={String(s.fills)} />
          </div>

          {s.halted && <div className="card neg">‼ Halted: {s.halt_reason}</div>}

          <div className="card">
            <h2>Live equity curve</h2>
            <SeriesChart data={rows} lines={[
              { key: "total", color: "var(--text)", name: "total" },
              { key: "realized", color: "var(--green)", name: "realized" },
              { key: "unrealized", color: "var(--amber)", name: "unrealized" },
            ]} />
          </div>

          <div className="row wrap">
            <div className="card" style={{ flex: 1, minWidth: 300 }}>
              <h2>Inventory</h2>
              <SeriesChart data={rows} height={180} lines={[{ key: "position", color: "var(--accent)", name: "position" }]} />
            </div>
            <div className="card" style={{ flex: 1, minWidth: 300 }}>
              <h2>Recent fills</h2>
              {frame?.fills && frame.fills.length > 0 ? (
                <table>
                  <thead><tr><th>side</th><th>price</th><th>size</th><th>pos</th><th>realized</th></tr></thead>
                  <tbody>
                    {[...frame.fills].reverse().map((f, i) => (
                      <tr key={i}>
                        <td className={f.side === "BUY" ? "pos" : "neg"}>{f.side}</td>
                        <td>{f.price.toFixed(3)}</td><td>{f.size}</td>
                        <td>{f.position.toFixed(0)}</td><td>{f.realized_pnl.toFixed(3)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : <p className="muted small">No fills yet — a quiet market may produce none.</p>}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function Kpi({ label, value, num, cls }: { label: ReactNode; value?: string; num?: number; cls?: string }) {
  return (
    <div className="card" style={{ padding: "var(--s3) var(--s4)" }}>
      <div className="small muted">{label}</div>
      <div className={cls} style={{ fontSize: 20, fontWeight: 700 }}>
        {num !== undefined ? <AnimatedNumber value={num} dp={4} prefix={num >= 0 ? "+" : ""} /> : value}
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return <div><label>{label}</label>{children}</div>;
}

function NumField({ label, term, value, step, disabled, onChange }:
  { label: string; term?: string; value: number; step: number; disabled?: boolean; onChange: (v: number) => void }) {
  return (
    <div>
      <label>{label}{term && <InfoTip term={term} />}</label>
      <input type="number" value={value} step={step} disabled={disabled} style={{ width: 96 }} onChange={(e) => onChange(+e.target.value)} />
    </div>
  );
}
