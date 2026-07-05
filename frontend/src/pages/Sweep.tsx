// Parameter Sweep: run a grid of settings on one data source, then compare via a
// P&L heatmap (spread × skew) + a ranked table with CSV export.

import { useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { SweepRow } from "../api/types";
import { useSelection } from "../state/SelectionContext";
import { useToast } from "../components/Toast";
import Heatmap from "../components/Heatmap";
import InfoTip from "../components/InfoTip";

const floats = (s: string) => s.split(",").map((x) => parseFloat(x.trim())).filter((x) => !isNaN(x));

export default function Sweep() {
  const { tokenId } = useSelection();
  const toast = useToast();
  const [src, setSrc] = useState("history");
  const [interval, setIntervalV] = useState("1d");
  const [fidelity, setFidelity] = useState(30);
  const [recording, setRecording] = useState("");
  const [spreads, setSpreads] = useState("0.01,0.02,0.04");
  const [sizes, setSizes] = useState("50");
  const [skews, setSkews] = useState("0,0.005,0.01");
  const [widen, setWiden] = useState(0.005);
  const [requote, setRequote] = useState(0.002);
  const [rows, setRows] = useState<SweepRow[] | null>(null);
  const [size, setSize] = useState<number | null>(null);
  const [running, setRunning] = useState(false);
  const [err, setErr] = useState("");

  const recordings = useQuery({ queryKey: ["recordings"], queryFn: api.recordings });

  const run = async () => {
    setErr(""); setRunning(true);
    try {
      const body: Record<string, unknown> = {
        source: src, spreads: floats(spreads), sizes: floats(sizes), skews: floats(skews), widen, requote,
      };
      if (src === "history") { body.token_id = tokenId; body.interval = interval; body.fidelity = fidelity; }
      else body.recording = recording;
      const res = await api.sweep(body);
      setRows(res);
      setSize(res.length ? res[0].size : null);
      toast(`Swept ${res.length} settings`, "success");
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  };

  const sizesAvail = rows ? [...new Set(rows.map((r) => r.size))].sort((a, b) => a - b) : [];
  const heatRows = rows ? rows.filter((r) => size === null || r.size === size) : [];
  const canRun = !running && (src === "history" ? !!tokenId : !!recording);

  const downloadCsv = () => {
    if (!rows || rows.length === 0) return;
    const cols = Object.keys(rows[0]);
    const csv = [cols.join(","), ...rows.map((r) => cols.map((c) => (r as unknown as Record<string, unknown>)[c]).join(","))].join("\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    const a = document.createElement("a");
    a.href = url; a.download = "sweep.csv"; a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="col">
      <h1>Parameter Sweep</h1>
      <p className="muted small">Compare settings on identical data — the right way to tune <InfoTip term="sweep" /></p>

      <div className="card col">
        <div className="row center wrap">
          <Seg value={src} onChange={setSrc} options={[["history", "History"], ["recording", "Recording"]]} />
          {src === "history" ? (
            <>
              <span className="small muted">token: {tokenId ? `${tokenId.slice(0, 14)}…` : "select in Explorer"}</span>
              <Field label="interval">
                <select value={interval} onChange={(e) => setIntervalV(e.target.value)}>
                  {["1h", "6h", "1d", "1w", "max"].map((o) => <option key={o}>{o}</option>)}
                </select>
              </Field>
              <Field label="fidelity"><input type="number" value={fidelity} min={1} max={60} style={{ width: 80 }} onChange={(e) => setFidelity(+e.target.value)} /></Field>
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
          <Field label="spreads"><input value={spreads} onChange={(e) => setSpreads(e.target.value)} style={{ width: 150 }} /></Field>
          <Field label="sizes"><input value={sizes} onChange={(e) => setSizes(e.target.value)} style={{ width: 100 }} /></Field>
          <Field label="skews"><input value={skews} onChange={(e) => setSkews(e.target.value)} style={{ width: 150 }} /></Field>
          <Field label="widen"><input type="number" value={widen} step={0.001} style={{ width: 90 }} onChange={(e) => setWiden(+e.target.value)} /></Field>
          <Field label="requote"><input type="number" value={requote} step={0.001} style={{ width: 90 }} onChange={(e) => setRequote(+e.target.value)} /></Field>
        </div>

        <div className="row center">
          <button className="btn btn-primary" disabled={!canRun} onClick={run}>{running ? "Sweeping…" : "Run sweep"}</button>
          {err && <span className="neg small">{err}</span>}
        </div>
      </div>

      {rows && rows.length > 0 && (
        <>
          <div className="card col">
            <div className="row spread center wrap">
              <h2 style={{ margin: 0 }}>P&L heatmap</h2>
              {sizesAvail.length > 1 && (
                <Field label="size">
                  <select value={size ?? ""} onChange={(e) => setSize(+e.target.value)}>
                    {sizesAvail.map((s) => <option key={s} value={s}>{s}</option>)}
                  </select>
                </Field>
              )}
            </div>
            <Heatmap rows={heatRows} />
            <div className="small muted">Best: spread {rows[0].spread} · size {rows[0].size} · skew {rows[0].skew} → <span className={rows[0].total_pnl >= 0 ? "pos" : "neg"}>{rows[0].total_pnl.toFixed(2)} pUSD</span></div>
          </div>

          <div className="card">
            <div className="row spread center"><h2 style={{ margin: 0 }}>All results</h2><button className="btn" onClick={downloadCsv}>⬇ CSV</button></div>
            <table>
              <thead><tr><th>spread</th><th>size</th><th>skew</th><th>P&L</th><th>fills</th><th>win</th><th>maxDD</th><th>sharpe</th></tr></thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={i}>
                    <td>{r.spread}</td><td>{r.size}</td><td>{r.skew}</td>
                    <td className={r.total_pnl >= 0 ? "pos" : "neg"}>{r.total_pnl.toFixed(2)}</td>
                    <td>{r.fills}</td><td>{Math.round(r.win_rate * 100)}%</td>
                    <td>{r.max_drawdown.toFixed(2)}</td><td>{r.sharpe.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
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
