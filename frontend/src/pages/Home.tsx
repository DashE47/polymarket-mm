// Cockpit dashboard: at-a-glance KPIs, a live watchlist, and recent runs.

import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useWatchlist, tokenOf, type WatchItem } from "../state/WatchlistContext";
import { useSelection } from "../state/SelectionContext";
import AnimatedNumber from "../components/AnimatedNumber";
import Sparkline from "../components/Sparkline";
import StarButton from "../components/StarButton";
import styles from "./Home.module.css";

export default function Home() {
  const { items } = useWatchlist();
  const config = useQuery({ queryKey: ["config"], queryFn: api.config });
  const runs = useQuery({ queryKey: ["runs"], queryFn: () => api.runs(8) });

  const cfg = config.data as { mode?: string; max_daily_loss_usd?: number } | undefined;
  const lastPnl = runs.data?.[0]?.total_pnl;

  return (
    <div className="col">
      <h1>Dashboard</h1>
      <p className="muted">Your cockpit — watchlist, recent runs, and setup at a glance. Press <kbd>⌘K</kbd> to jump anywhere.</p>

      <div className={styles.kpis}>
        <Kpi label="Markets watched" value={String(items.length)} />
        <Kpi label="Last run P&L"
             value={lastPnl !== undefined ? `${lastPnl >= 0 ? "+" : ""}${lastPnl.toFixed(2)}` : "—"}
             cls={lastPnl !== undefined ? (lastPnl >= 0 ? "pos" : "neg") : ""} />
        <Kpi label="Mode" value={cfg?.mode ?? "…"} />
        <Kpi label="Max daily loss" value={cfg ? `$${cfg.max_daily_loss_usd}` : "…"} />
      </div>

      <div className="col">
        <h2>★ Watchlist</h2>
        {items.length === 0 ? (
          <div className="card muted">
            No markets yet — star markets in the <Link to="/explorer">Explorer</Link> to track them here live.
          </div>
        ) : (
          <div className={styles.grid}>
            {items.map((it) => <WatchTile key={tokenOf(it)} item={it} />)}
          </div>
        )}
      </div>

      <div className="col">
        <h2>Recent runs</h2>
        {!runs.data || runs.data.length === 0 ? (
          <div className="card muted">No runs yet — try a <Link to="/analytics">backtest</Link> or a <Link to="/lab">live sim</Link>.</div>
        ) : (
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
        )}
      </div>
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
