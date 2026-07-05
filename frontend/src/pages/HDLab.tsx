// HD Lab — the full research cockpit over the high-precision recordings:
//   1. DATASET   live inventory of data/updown_hd (buckets, resolution, disk)
//   2. RECORDER  start/stop the tick recorder from the browser + live log tail
//   3. RESOLVER  one click backfills real settled winners from Gamma
//   4. REPLAY    exact-fill backtest grid (fade / momentum) from the incremental
//                cache — every recording is replayed once, then results are instant.
//   5. EQUITY    click a cell → that rule's cumulative P&L + recent fills.
// SIMULATION ONLY — analyses recorded data; places no orders.

import { useMemo, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type HDReplayParams } from "../api/client";
import { useToast } from "../components/Toast";
import SeriesChart from "../components/SeriesChart";
import styles from "./HDLab.module.css";

const ASSETS = ["Bitcoin", "Ethereum", "Solana", "XRP"];
const WINDOWS = [5, 15, 60];

export default function HDLab() {
  const toast = useToast();
  const qc = useQueryClient();

  // recorder form
  const [assets, setAssets] = useState<string[]>([...ASSETS]);
  const [recWindows, setRecWindows] = useState<number[]>([...WINDOWS]);
  const [showLog, setShowLog] = useState(true);

  // replay params
  const [mode, setMode] = useState<"momentum" | "fade">("momentum");
  const [windowLen, setWindowLen] = useState(5);
  const [stake, setStake] = useState(1);
  const [maxSpread, setMaxSpread] = useState(0.05);
  const [latency, setLatency] = useState(0);
  const [minFill, setMinFill] = useState(0);
  const [sel, setSel] = useState<{ thr: number; win: number } | null>(null);

  const params: HDReplayParams = { stake, max_spread: maxSpread, latency_ms: latency, min_fill_frac: minFill };

  const summary = useQuery({ queryKey: ["hdSummary"], queryFn: api.hdSummary, refetchInterval: 5000 });
  const s = summary.data;
  const busy = !!(s?.replay.running || s?.resolver.running);

  const log = useQuery({
    queryKey: ["hdLog"],
    queryFn: () => api.hdRecorderLog(16),
    refetchInterval: s?.recorder.running && showLog ? 4000 : false,
    enabled: !!s?.recorder.running && showLog,
  });

  const grid = useQuery({
    queryKey: ["hdGrid", mode, windowLen, params],
    queryFn: () => api.hdGrid(mode, windowLen, params),
    refetchInterval: busy ? 6000 : false,
  });
  const g = grid.data;

  const eq = useQuery({
    queryKey: ["hdEquity", mode, windowLen, params, sel],
    queryFn: () => api.hdEquity(mode, windowLen, sel!.thr, sel!.win, params),
    enabled: !!sel,
  });

  const act = async (fn: () => Promise<unknown>, okMsg: string) => {
    try {
      await fn();
      toast(okMsg, "success");
      qc.invalidateQueries({ queryKey: ["hdSummary"] });
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  const maxAbs = useMemo(() => {
    const vals = (g?.cells ?? []).map((c) => c.edge).filter((e): e is number => e !== null).map(Math.abs);
    return Math.max(1e-9, ...vals, 1);
  }, [g]);
  const color = (edge: number | null) => {
    if (edge === null) return "var(--surface-2)";
    const a = 0.12 + 0.8 * Math.min(1, Math.abs(edge) / maxAbs);
    return edge >= 0 ? `rgba(31,160,90,${a})` : `rgba(214,69,63,${a})`;
  };
  const bestKey = useMemo(() => {
    if (!g) return "";
    let k = "", bv = -Infinity;
    for (const c of g.cells) if (c.edge !== null && c.bets >= g.min_sample && c.edge > bv) { bv = c.edge; k = `${c.thr}|${c.win}`; }
    return k;
  }, [g]);

  const toggle = <T,>(arr: T[], v: T, set: (x: T[]) => void) =>
    set(arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v]);

  const replayPct = s?.replay.total ? Math.round((s.replay.done / s.replay.total) * 100) : 0;
  const eqData = eq.data ? eq.data.cum.map((v, i) => ({ t: i + 1, pnl: v, zero: 0 })) : [];

  return (
    <div className="col">
      <h1>HD Lab</h1>
      <p className="muted small">
        Record tick-level data (both books), backfill real settled outcomes, and backtest with
        execution-exact fills. Results here are what live trading would have gotten. Simulation only.
      </p>

      {/* ---- 1. dataset ---- */}
      {s && (
        <div className="card col">
          <div className="row spread center wrap">
            <h2 style={{ margin: 0 }}>Dataset</h2>
            <span className="small muted">
              {s.recent_writes > 0 ? <><span className={styles.dot} /> recording activity in the last 2 min</>
                : <><span className={styles.dotIdle} /> no recent writes</>}
            </span>
          </div>
          <div className={styles.chips}>
            <Chip label="buckets" value={String(s.buckets)}
              sub={Object.entries(s.by_window).map(([w, n]) => `${w}m: ${n}`).join(" · ")} />
            <Chip label="settled outcomes" value={`${s.resolved}`} sub={`${s.unresolved} pending`}
              cls={s.unresolved > 20 ? "neg" : undefined} />
            <Chip label="on disk" value={`${(s.size_mb / 1000).toFixed(2)} GB`} sub={`${s.disk_free_gb} GB free`} />
            <Chip label="by asset" value={String(Object.keys(s.by_asset).length)}
              sub={Object.entries(s.by_asset).map(([a, n]) => `${a.slice(0, 3)} ${n}`).join(" · ")} />
          </div>
          <div className="row center wrap">
            <button className="btn" disabled={s.resolver.running}
              onClick={() => act(api.hdResolveStart, "Resolver started")}>
              {s.resolver.running ? `Resolving… ${s.resolver.checked} checked, ${s.resolver.settled} settled` : "Backfill settled outcomes"}
            </button>
            <span className="small muted">run this after collecting — fetches each bucket's real winner from Gamma</span>
          </div>
        </div>
      )}

      {/* ---- 2. recorder ---- */}
      <div className="card col">
        <div className="row spread center wrap">
          <h2 style={{ margin: 0 }}>Recorder</h2>
          {s?.recorder.running && (
            <span className="small muted">
              <span className={styles.dot} /> running {Math.floor((s.recorder.uptime_s ?? 0) / 60)}m
              {s.recorder.args && ` — ${s.recorder.args.assets.length} assets, windows ${s.recorder.args.windows.join("/")}m`}
            </span>
          )}
        </div>
        {!s?.recorder.running ? (
          <>
            <div className={styles.checks}>
              <span className="small muted">assets:</span>
              {ASSETS.map((a) => (
                <label key={a}><input type="checkbox" checked={assets.includes(a)} onChange={() => toggle(assets, a, setAssets)} />{a}</label>
              ))}
              <span className="small muted" style={{ marginLeft: 12 }}>windows:</span>
              {WINDOWS.map((w) => (
                <label key={w}><input type="checkbox" checked={recWindows.includes(w)} onChange={() => toggle(recWindows, w, setRecWindows)} />{w}m</label>
              ))}
            </div>
            <div className="row center wrap">
              <button className="btn btn-primary" disabled={!assets.length || !recWindows.length}
                onClick={() => act(() => api.hdRecorderStart(assets, [...recWindows].sort((a, b) => a - b)), "Recorder started")}>
                ▶ Start recording
              </button>
              {(s?.recent_writes ?? 0) > 0 && (
                <span className="neg small">files are being written right now — another recorder (terminal?) may already be running; duplicates are deduped in analysis, but avoid doubling up</span>
              )}
            </div>
          </>
        ) : (
          <div className="row center wrap">
            <button className="btn" onClick={() => act(api.hdRecorderStop, "Recorder stopped")}>■ Stop</button>
            <button className="btn" onClick={() => setShowLog((v) => !v)}>{showLog ? "hide log" : "show log"}</button>
            <span className="small muted">stop is immediate; in-flight buckets keep their ticks and get winners from the resolver</span>
          </div>
        )}
        {s?.recorder.running && showLog && (
          <pre className={styles.log}>{(log.data?.lines ?? ["…"]).join("\n")}</pre>
        )}
      </div>

      {/* ---- 3. replay ---- */}
      <div className="card col">
        <div className="row spread center wrap">
          <h2 style={{ margin: 0 }}>Exact-fill replay</h2>
          {g && <span className="small muted">{g.cached}/{g.total} recordings cached · {g.buckets_settled} settled</span>}
        </div>
        <div className="row center wrap">
          <Field label="strategy">
            <div className="row" style={{ gap: 6 }}>
              <button className={`btn ${mode === "momentum" ? "btn-primary" : ""}`} onClick={() => { setMode("momentum"); setSel(null); }}>Momentum ≥</button>
              <button className={`btn ${mode === "fade" ? "btn-primary" : ""}`} onClick={() => { setMode("fade"); setSel(null); }}>Fade ≤</button>
            </div>
          </Field>
          <Field label="market length">
            <div className="row" style={{ gap: 6 }}>
              {WINDOWS.map((w) => (
                <button key={w} className={`btn ${windowLen === w ? "btn-primary" : ""}`} onClick={() => { setWindowLen(w); setSel(null); }}>{w}m</button>
              ))}
            </div>
          </Field>
          <Field label="stake $"><input type="number" value={stake} min={0.5} step={0.5} style={{ width: 80 }} onChange={(e) => setStake(+e.target.value)} /></Field>
          <Field label="max spread"><input type="number" value={maxSpread} step={0.01} min={0} style={{ width: 85 }} onChange={(e) => setMaxSpread(+e.target.value)} /></Field>
          <Field label="latency ms"><input type="number" value={latency} step={100} min={0} style={{ width: 85 }} onChange={(e) => setLatency(+e.target.value)} /></Field>
          <Field label="min fill"><input type="number" value={minFill} step={0.1} min={0} max={1} style={{ width: 75 }} onChange={(e) => setMinFill(+e.target.value)} /></Field>
        </div>

        {g && !g.complete && (
          <div className="row center wrap">
            <button className="btn btn-primary" disabled={!!s?.replay.running}
              onClick={() => act(() => api.hdReplayStart(params), "Replay job started")}>
              {s?.replay.running ? "Replaying…" : `Replay ${g.total - g.cached} uncached recordings`}
            </button>
            {s?.replay.running && (
              <>
                <div className={styles.progress}><div className={styles.progressFill} style={{ width: `${replayPct}%` }} /></div>
                <span className="small muted">{s.replay.done}/{s.replay.total}</span>
              </>
            )}
            <span className="small muted">one-time per recording — afterwards every view is instant</span>
          </div>
        )}

        {g && g.cached > 0 && (
          <>
            <div className={styles.legend}>
              <span>edge (pp):</span>
              <span className={styles.swatch} style={{ background: color(-maxAbs) }} />
              <span>loss</span>
              <span className={styles.swatch} style={{ background: "var(--surface-2)" }} />
              <span className={styles.swatch} style={{ background: color(maxAbs) }} />
              <span>profit · ★ best (n≥{g.min_sample}) · click a cell for its equity</span>
            </div>
            <div className="small muted">entered within (minutes into the bucket) →</div>
            <div className={styles.grid} style={{ gridTemplateColumns: `72px repeat(${g.windows.length}, 1fr)` }}>
              <div className={styles.corner}>{mode === "momentum" ? "rise ≥" : "dip ≤"}</div>
              {g.windows.map((w) => <div key={`h${w}`} className={styles.colh}>≤{w}m</div>)}
              {g.thresholds.map((thr) => [
                <div key={`r${thr}`} className={styles.rowh}>{thr.toFixed(2)}</div>,
                ...g.windows.map((w) => {
                  const c = g.cells.find((x) => x.thr === thr && x.win === w);
                  const empty = !c || c.edge === null;
                  const isSel = sel?.thr === thr && sel?.win === w;
                  return (
                    <div key={`${thr}-${w}`}
                      className={`${styles.cell} ${empty ? styles.empty : ""} ${isSel ? styles.sel : ""}`}
                      style={{ background: color(c?.edge ?? null) }}
                      onClick={() => !empty && setSel({ thr, win: w })}
                      title={empty ? "no settled bets" : `hit ${c!.hit}% vs paid ${c!.paid}% · fill ${c!.fill}% · slip ${c!.slip_c}¢ · ${c!.bets} bets`}>
                      {`${thr}|${w}` === bestKey && <span className={styles.star}>★</span>}
                      <span>{empty ? "—" : `${c!.edge! >= 0 ? "+" : ""}${c!.edge!.toFixed(1)}`}</span>
                      {!empty && <span className={styles.n}>n={c!.bets}</span>}
                    </div>
                  );
                }),
              ])}
            </div>
            <div className="small muted">
              ↑ {mode === "momentum" ? "buy the STRONG side once it reaches this price (ride the move)" : "buy the CHEAP side once it dips to this price (bet on reversal)"} ·
              fills walk the real ask ladder · winners from real settlement
            </div>
          </>
        )}
        {g && g.cached === 0 && !s?.replay.running && (
          <p className="muted small">No cached replays for these execution settings yet — hit the replay button above.</p>
        )}
      </div>

      {/* ---- 4. equity ---- */}
      {sel && eq.data && eq.data.n > 0 && (
        <div className="card col">
          <div className="row spread center wrap">
            <h2 style={{ margin: 0 }}>
              Equity — {mode === "momentum" ? "rise ≥" : "dip ≤"} {sel.thr}, entered ≤ {sel.win}m
            </h2>
            <span className="small muted">{mode} · {windowLen}m markets · ${stake} stakes</span>
          </div>
          <div className={styles.chips}>
            <Chip label="bets" value={String(eq.data.n)} />
            <Chip label="hit rate" value={eq.data.hit !== null ? `${eq.data.hit}%` : "—"} />
            <Chip label="final P&L" value={`${eq.data.final >= 0 ? "+" : ""}${eq.data.final.toFixed(2)}`} cls={eq.data.final >= 0 ? "pos" : "neg"} />
            <Chip label="worst drawdown" value={`-${eq.data.max_drawdown.toFixed(2)}`} cls="neg" />
          </div>
          <SeriesChart data={eqData}
            lines={[
              { key: "zero", color: "var(--border-strong)", name: "0" },
              { key: "pnl", color: eq.data.final >= 0 ? "var(--accent)" : "var(--red)", name: "cumulative P&L" },
            ]} height={240} />
          <details>
            <summary className="small muted" style={{ cursor: "pointer" }}>last {eq.data.rows.length} fills</summary>
            <table>
              <thead><tr><th>time</th><th>asset</th><th>side</th><th>paid</th><th>result</th><th>P&L</th></tr></thead>
              <tbody>
                {[...eq.data.rows].reverse().map((r, i) => (
                  <tr key={i}>
                    <td>{r.end_ts ? new Date(r.end_ts * 1000).toLocaleTimeString() : "—"}</td>
                    <td>{r.asset}</td><td>{r.side}</td><td>{r.avg.toFixed(3)}</td>
                    <td className={r.won ? "pos" : "neg"}>{r.won ? "won" : "lost"}</td>
                    <td className={r.pnl >= 0 ? "pos" : "neg"}>{r.pnl >= 0 ? "+" : ""}{r.pnl.toFixed(3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        </div>
      )}
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return <div><label>{label}</label>{children}</div>;
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
