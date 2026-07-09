// Mission Control: what we're building, what's proven dead vs. alive, the live
// dataset status, and where we are on the road to a profitable bot. The verdicts
// below are maintained by hand as research concludes — they ARE the project memory.

import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useWatchlist, tokenOf, type WatchItem } from "../state/WatchlistContext";
import { useSelection } from "../state/SelectionContext";
import AnimatedNumber from "../components/AnimatedNumber";
import Sparkline from "../components/Sparkline";
import StarButton from "../components/StarButton";
import styles from "./Home.module.css";

// Findings from the 16GB / 3,344-bucket exact-fill study (July 2026).
const VERDICTS: { tag: "lead" | "maybe" | "dead" | "parked"; name: string; why: string }[] = [
  { tag: "dead", name: "60-min momentum", why: "the +8–16¢/bet edge (July 1–5, 48 windows, passed all tests) COLLAPSED to ≈0 when the sample doubled to 104 windows (July 9 re-run: best cell +0.9¢, P(≤0)=0.40, every other cell ≤0). Same regime-dependent illusion as the 5-min collapse — the tests were right to warn 'one broad regime era'. Live paper P&L agreed: −4pp vs breakeven." },
  { tag: "dead", name: "15-min momentum", why: "≈breakeven after spread on the pooled sample (sim +2.6pp, live −4.2pp, combined ~+0.7pp on ~970 bets) — the spread eats the signal" },
  { tag: "dead", name: "5-min (any strategy)", why: "market proven efficient on 2,360 buckets — momentum & fade both ≈0 or negative. Stopped recording it." },
  { tag: "dead", name: "Fade the dip (all horizons)", why: "dips continue rather than revert — uniformly −1.5 to −13pp with exact fills. Entry is −EV; no exit rule can rescue a bad entry." },
  { tag: "dead", name: "Exit rules on 60-min momentum (stops & velocity)", why: "every exit tested leaks edge: stop-loss 0.45 keeps only +3.4¢ of hold's +9.3¢/bet; velocity exits (sell on 5–15¢ fast drops) keep ≈0¢ — 54–86% of winners dip hard mid-flight and recover. Mid-flight prices are calibrated; ALL edge realizes at settlement. Hold to resolution." },
  { tag: "parked", name: "Market making (spread capture)", why: "the original platform below — engine works, edge never validated. Revisit after the momentum bot." },
  { tag: "parked", name: "News-overshoot reversion (event markets)", why: "real effect — a news jump overshoots then partly reverts. Untradeable on longshots (wide spread + reversed leverage eat the 0.5¢ move), but plausible on mid-priced, liquid markets (elections, big sports). Needs a different system: event markets + jump detector. Test only after the momentum bot validates." },
];

const STEPS: { label: string; state: "done" | "now" | "todo" }[] = [
  { label: "Build honest instruments (tick recorder, exact-fill replay, real settlement)", state: "done" },
  { label: "Find a candidate edge and stress-test it (latency, luck, time-split)", state: "done" },
  { label: "Re-test on doubled data: momentum edge did NOT survive — Up/Down family concluded efficient", state: "done" },
  { label: "Next candidate: pick from the parked ideas (news-overshoot, rewards MM, options-implied gap) with the same instruments", state: "now" },
  { label: "Tiny real stakes with kill-switches, only after an edge survives everything above", state: "todo" },
];

export default function Home() {
  const { items } = useWatchlist();
  const hd = useQuery({ queryKey: ["hdSummary"], queryFn: api.hdSummary, refetchInterval: 10000 });
  const runs = useQuery({ queryKey: ["runs"], queryFn: () => api.runs(5) });
  const s = hd.data;

  return (
    <div className="col">
      <h1>Mission Control</h1>
      <p className="muted">
        Goal: a bot with a <em>proven</em> edge on Polymarket. Everything here is simulation-only until
        the ladder below says otherwise. Press <kbd>⌘K</kbd> to jump anywhere.
      </p>

      {/* --- live dataset / research status --- */}
      <div className={styles.kpis}>
        <Kpi label="Recordings (15m / 60m / 5m)" value={s ? `${s.by_window["15"] ?? 0} / ${s.by_window["60"] ?? 0} / ${s.by_window["5"] ?? 0}` : "…"} />
        <Kpi label="Settled outcomes" value={s ? `${s.resolved}` : "…"} />
        <Kpi label="Data on disk" value={s ? `${(s.size_mb / 1000).toFixed(1)} GB` : "…"} />
        <Kpi label="Recorder" value={s ? (s.recorder.running || s.recent_writes > 0 ? "live" : "off") : "…"}
             cls={s && (s.recorder.running || s.recent_writes > 0) ? "pos" : "muted"} />
      </div>

      {/* --- strategy verdicts --- */}
      <div className="card col">
        <div className="row spread center">
          <h2 style={{ margin: 0 }}>Strategy verdicts</h2>
          <Link to="/hdlab" className="small">open HD Lab →</Link>
        </div>
        <div className={styles.verdicts}>
          {VERDICTS.map((v) => (
            <div key={v.name} className={styles.verdict}>
              <span className={`${styles.vTag} ${{ lead: styles.vLead, maybe: styles.vMaybe, dead: styles.vDead, parked: styles.vParked }[v.tag]}`}>
                {{ lead: "LEAD", maybe: "PROMISING", dead: "DEAD", parked: "PARKED" }[v.tag]}
              </span>
              <span className={styles.vName}>{v.name}</span>
              <span className={styles.vWhy}>{v.why}</span>
            </div>
          ))}
        </div>
      </div>

      {/* --- roadmap --- */}
      <div className="card col">
        <h2 style={{ margin: 0 }}>Road to a live bot</h2>
        <div className={styles.steps}>
          {STEPS.map((st, i) => (
            <div key={i} className={styles.step}>
              <span className={`${styles.stepN} ${st.state === "done" ? styles.stepDone : st.state === "now" ? styles.stepNow : ""}`}>
                {st.state === "done" ? "✓" : i + 1}
              </span>
              <span className={st.state === "now" ? "" : "muted"} style={{ fontSize: 14 }}>
                {st.label} {st.state === "now" && <span className={styles.dot} />}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* --- secondary: watchlist + recent runs (market-making platform) --- */}
      {items.length > 0 && (
        <div className="col">
          <h2>★ Watchlist</h2>
          <div className={styles.grid}>
            {items.map((it) => <WatchTile key={tokenOf(it)} item={it} />)}
          </div>
        </div>
      )}

      {runs.data && runs.data.length > 0 && (
        <div className="col">
          <h2>Recent MM sim runs</h2>
          <div className="card">
            <table>
              <thead><tr><th>Run</th><th>Source</th><th>Fills</th><th>P&L</th></tr></thead>
              <tbody>
                {runs.data.map((r) => (
                  <tr key={r.file}>
                    <td className="mono small">{r.file.replace("mm_", "").replace(".jsonl", "")}</td>
                    <td className="small muted">{r.source || "—"}</td>
                    <td>{r.fills}</td>
                    <td className={r.total_pnl >= 0 ? "pos" : "neg"}>{r.total_pnl >= 0 ? "+" : ""}{r.total_pnl.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function Kpi({ label, value, cls }: { label: string; value: string; cls?: string }) {
  return (
    <div className="card">
      <div className="small muted">{label}</div>
      <div className={`${styles.kpiVal} ${cls ?? ""}`}>{value}</div>
    </div>
  );
}

function WatchTile({ item }: { item: WatchItem }) {
  const navigate = useNavigate();
  const { select } = useSelection();
  const tid = item.market.tokens[item.outcome];
  const stats = useQuery({ queryKey: ["stats", tid], queryFn: () => api.stats(tid), refetchInterval: 8000 });
  const hist = useQuery({ queryKey: ["history", tid], queryFn: () => api.history(tid, "1d", 180), staleTime: 300_000 });

  const prices = (hist.data ?? []).map((p) => p.p);
  const mid = stats.data?.mid ?? item.market.outcome_prices[item.outcome];
  const up = (stats.data?.one_day_price_change ?? item.market.one_day_price_change) >= 0;

  return (
    <div className={`card ${styles.tile}`} onClick={() => { select(item.market, item.outcome); navigate("/book"); }}>
      <div className={styles.tileHead}>
        <span className={styles.tileQ}>{item.market.question}</span>
        <StarButton market={item.market} outcome={item.outcome} />
      </div>
      <div className={styles.tileRow}>
        <div>
          <span className={styles.tilePrice}><AnimatedNumber value={mid} dp={3} /></span>{" "}
          <span className="small muted">{item.outcome}</span>
        </div>
        <Sparkline points={prices} width={110} height={32} color={up ? "var(--green)" : "var(--red)"} />
      </div>
    </div>
  );
}
