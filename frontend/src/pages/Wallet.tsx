// Paper Wallet — the demo-money bot. Start/stop the paper-trading daemon (it
// trades the validated momentum rules live with simulated fills), and watch the
// wallet: balance, open positions, realized P&L, equity curve, trade history.
// This page is step 4 of the roadmap: if paper P&L tracks the replay's
// expectations over days, the pipeline is proven end-to-end. SIMULATION ONLY.

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useToast } from "../components/Toast";
import SeriesChart from "../components/SeriesChart";
import styles from "./HDLab.module.css";

const WINDOWS = [15, 60];

export default function Wallet() {
  const toast = useToast();
  const qc = useQueryClient();
  const [windows, setWindows] = useState<number[]>([60]); // validated rule; 15-min is ~breakeven
  const [stake, setStake] = useState(10);
  const [showLog, setShowLog] = useState(true);

  const status = useQuery({ queryKey: ["paperStatus"], queryFn: api.paperStatus, refetchInterval: 6000 });
  const s = status.data;
  const running = !!s?.daemon.running;

  const log = useQuery({
    queryKey: ["paperLog"],
    queryFn: () => api.paperLog(16),
    refetchInterval: running && showLog ? 5000 : false,
    enabled: running && showLog,
  });

  const act = async (fn: () => Promise<unknown>, okMsg: string) => {
    try {
      await fn();
      toast(okMsg, "success");
      qc.invalidateQueries({ queryKey: ["paperStatus"] });
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  const balance = s?.wallet?.balance;
  const start = s?.wallet?.start_balance;
  const atRisk = (s?.open_positions ?? []).reduce((a, p) => a + (p.spent ?? 0), 0);
  const totalPnl = balance !== undefined && start !== undefined ? balance + atRisk - start : undefined;
  const eqData = (s?.equity ?? []).map((p, i) => ({ t: i + 1, balance: p.balance }));

  return (
    <div className="col">
      <div className="row spread center wrap">
        <h1 style={{ margin: 0 }}>Paper Wallet</h1>
        {running && (
          <span className="small muted">
            <span className={styles.dot} /> trading {Math.floor((s?.daemon.uptime_s ?? 0) / 60)}m
            {s?.daemon.args && ` — ${s.daemon.args.windows.join("/")}m markets, $${s.daemon.args.stake}/trade`}
          </span>
        )}
      </div>
      <p className="muted small">
        Demo money, real markets, real fills model: buys the strong side when the validated momentum
        rule triggers (60m: ≥0.65 in first 48m · 15m: ≥0.85 in first 12m), holds to the real settled
        outcome. If a week of this tracks the replay's numbers, the pipeline is proven. Simulation only.
      </p>

      {/* --- wallet KPIs --- */}
      <div className={styles.chips}>
        <Chip label="balance" value={balance !== undefined ? `$${balance.toFixed(2)}` : "—"} />
        <Chip label="total P&L" value={totalPnl !== undefined ? `${totalPnl >= 0 ? "+" : ""}$${totalPnl.toFixed(2)}` : "—"}
              cls={totalPnl !== undefined ? (totalPnl >= 0 ? "pos" : "neg") : undefined} />
        <Chip label="open positions" value={String(s?.open_positions.length ?? 0)} sub={atRisk ? `$${atRisk.toFixed(2)} at risk` : undefined} />
        <Chip label="settled trades" value={String(s?.trades ?? 0)}
              sub={s?.hit !== null && s?.hit !== undefined ? `hit rate ${s.hit}%` : undefined} />
      </div>

      {/* --- controls --- */}
      <div className="card col">
        {!running ? (
          <div className="row center wrap">
            <div className={styles.checks}>
              <span className="small muted">markets:</span>
              {WINDOWS.map((w) => (
                <label key={w}>
                  <input type="checkbox" checked={windows.includes(w)}
                    onChange={() => setWindows((cur) => cur.includes(w) ? cur.filter((x) => x !== w) : [...cur, w])} />
                  {w}m
                </label>
              ))}
            </div>
            <div><label>stake $</label><input type="number" value={stake} min={1} step={1} style={{ width: 80 }} onChange={(e) => setStake(+e.target.value)} /></div>
            <button className="btn btn-primary" disabled={!windows.length}
              onClick={() => act(() => api.paperStart([...windows].sort((a, b) => a - b), stake), "Paper trader started")}>
              ▶ Start paper trading
            </button>
          </div>
        ) : (
          <div className="row center wrap">
            <button className="btn" onClick={() => act(api.paperStop, "Paper trader stopped")}>■ Stop</button>
            <button className="btn" onClick={() => setShowLog((v) => !v)}>{showLog ? "hide log" : "show log"}</button>
            <span className="small muted">open positions persist and settle on the next start</span>
          </div>
        )}
        {running && showLog && <pre className={styles.log}>{(log.data?.lines ?? ["…"]).join("\n")}</pre>}
      </div>

      {/* --- equity curve --- */}
      {eqData.length > 1 && (
        <div className="card col">
          <h2 style={{ margin: 0 }}>Balance over settled trades</h2>
          <SeriesChart data={eqData}
            lines={[{ key: "balance", color: (totalPnl ?? 0) >= 0 ? "var(--accent)" : "var(--red)", name: "balance" }]}
            height={220} />
        </div>
      )}

      {/* --- open positions --- */}
      {(s?.open_positions.length ?? 0) > 0 && (
        <div className="card col">
          <h2 style={{ margin: 0 }}>Open positions</h2>
          <table>
            <thead><tr><th>market</th><th>side</th><th>shares</th><th>paid</th><th>resolves</th></tr></thead>
            <tbody>
              {s!.open_positions.map((p, i) => (
                <tr key={i}>
                  <td className="small">{p.asset} {p.window_min}m</td>
                  <td>{p.side}</td>
                  <td>{p.shares?.toFixed(2)}</td>
                  <td>${p.spent?.toFixed(2)} @ {p.avg?.toFixed(3)}</td>
                  <td className="small muted">{p.end_ts ? new Date(p.end_ts * 1000).toLocaleTimeString() : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* --- trade history --- */}
      {(s?.history.length ?? 0) > 0 && (
        <div className="card col">
          <h2 style={{ margin: 0 }}>Trade history</h2>
          <table>
            <thead><tr><th>settled</th><th>market</th><th>side</th><th>paid</th><th>result</th><th>P&L</th><th>balance</th></tr></thead>
            <tbody>
              {s!.history.map((t, i) => (
                <tr key={i}>
                  <td className="small muted">{new Date(t.ts).toLocaleTimeString()}</td>
                  <td className="small">{t.asset} {t.window_min}m</td>
                  <td>{t.side}</td>
                  <td>{t.avg?.toFixed(3)}</td>
                  <td className={t.won ? "pos" : "neg"}>{t.won ? "won" : "lost"} ({t.winner})</td>
                  <td className={t.pnl >= 0 ? "pos" : "neg"}>{t.pnl >= 0 ? "+" : ""}{t.pnl.toFixed(2)}</td>
                  <td className="small">${t.balance_after.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {!s?.wallet && (
        <div className="card muted">No wallet yet — hit "Start paper trading" and the demo wallet is created with $1,000.</div>
      )}
    </div>
  );
}

function Chip({ label, value, sub, cls }: { label: string; value: string; sub?: string; cls?: string }) {
  return (
    <div className={styles.chip}>
      <div className={styles.lbl}>{label}</div>
      <div className={`${styles.val} ${cls ?? ""}`}>{value}</div>
      {sub && <div className={styles.sub}>{sub}</div>}
    </div>
  );
}
