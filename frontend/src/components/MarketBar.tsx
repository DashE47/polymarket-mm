// The market-overview bar (from the mockup): shows the selected token's price,
// 24h change, best bid/ask, spread, volume, liquidity, time-to-resolution, and a
// price sparkline. Reused at the top of the Order Book and Strategy Lab pages.

import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import Sparkline from "./Sparkline";
import AnimatedNumber from "./AnimatedNumber";
import styles from "./MarketBar.module.css";

function fmt(x: number | null | undefined, dp = 4): string {
  return x === null || x === undefined ? "—" : x.toFixed(dp);
}

function money(x: number | null | undefined): string {
  if (x === null || x === undefined) return "—";
  if (x >= 1e6) return `$${(x / 1e6).toFixed(1)}M`;
  if (x >= 1e3) return `$${(x / 1e3).toFixed(0)}k`;
  return `$${x.toFixed(0)}`;
}

function endsIn(iso?: string): string {
  if (!iso) return "—";
  const ms = new Date(iso).getTime() - Date.now();
  if (isNaN(ms)) return "—";
  if (ms <= 0) return "ended";
  const h = Math.floor(ms / 3.6e6);
  const d = Math.floor(h / 24);
  return d >= 1 ? `${d}d ${h % 24}h` : `${h}h ${Math.floor((ms % 3.6e6) / 6e4)}m`;
}

export default function MarketBar({ tokenId }: { tokenId: string }) {
  // Stats refresh every 5s so the bar stays live; history is a one-off sparkline.
  const stats = useQuery({
    queryKey: ["stats", tokenId],
    queryFn: () => api.stats(tokenId),
    refetchInterval: 5000,
  });
  const history = useQuery({
    queryKey: ["history", tokenId],
    queryFn: () => api.history(tokenId, "1d", 60),
  });

  if (stats.isLoading) return <div className={`card ${styles.bar}`}>Loading market…</div>;
  if (stats.isError) return <div className={`card ${styles.bar}`}>Could not load market stats.</div>;

  const s = stats.data!;
  const change = s.one_day_price_change ?? 0;
  const up = change >= 0;
  const prices = (history.data ?? []).map((p) => p.p);

  return (
    <div className={`card ${styles.bar}`}>
      <div className={styles.top}>
        <div>
          <div className={styles.question}>{s.question ?? "Selected market"}</div>
          <div className="small muted">
            tick {fmt(s.tick_size, 3)} ·{" "}
            <span className={s.tradeable ? "pos" : "neg"}>● {s.tradeable ? "tradeable" : "not tradeable"}</span>
          </div>
        </div>
        <div className={styles.priceWrap}>
          <div className={styles.price}><AnimatedNumber value={s.mid} dp={3} /></div>
          <div className={`small ${up ? "pos" : "neg"}`}>{up ? "▲" : "▼"} {change >= 0 ? "+" : ""}{change.toFixed(3)} today</div>
        </div>
      </div>

      <div className={styles.tiles}>
        <Tile label="Best bid / ask" value={`${fmt(s.best_bid, 3)} / ${fmt(s.best_ask, 3)}`} mono />
        <Tile label="Spread" value={fmt(s.spread, 3)} mono />
        <Tile label="24h volume" value={money(s.volume)} />
        <Tile label="Liquidity" value={money(s.liquidity)} />
        <Tile label="Ends in" value={endsIn(s.end_date)} />
      </div>

      <div className={styles.spark}>
        <div className="small muted">Price · last 24h</div>
        <Sparkline points={prices} color={prices.length && prices[prices.length - 1] >= prices[0] ? "var(--green)" : "var(--red)"} />
      </div>
    </div>
  );
}

function Tile({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className={styles.tile}>
      <div className="small muted">{label}</div>
      <div className={mono ? "mono" : undefined} style={{ fontWeight: 600, fontSize: 15 }}>{value}</div>
    </div>
  );
}
