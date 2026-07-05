// A market tile for the Explorer grid: question, the headline outcome's chance,
// 24h move, volume, a mini price chart, and clickable outcome chips to select.

import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Market } from "../api/types";
import Sparkline from "./Sparkline";
import StarButton from "./StarButton";
import { localTime } from "../lib/time";
import styles from "./MarketCard.module.css";

// Yes/up = green, No/down = magenta, anything else = accent.
function outcomeColor(o: string): string {
  const k = o.toLowerCase();
  if (k === "yes" || k === "up") return "var(--green)";
  if (k === "no" || k === "down") return "var(--red)";
  return "var(--accent)";
}

function primaryOutcome(m: Market): string {
  const keys = Object.keys(m.tokens);
  return keys.find((k) => k.toLowerCase() === "yes") ?? keys[0] ?? "";
}

function endsIn(iso?: string): string | null {
  if (!iso) return null;
  const ms = new Date(iso).getTime() - Date.now();
  if (isNaN(ms) || ms <= 0) return null;
  const m = Math.floor(ms / 60000);
  if (m < 60) return `ends in ${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `ends in ${h}h ${m % 60}m`;
  return `ends in ${Math.floor(h / 24)}d`;
}

export default function MarketCard({
  market, selectedToken, onSelect,
}: {
  market: Market;
  selectedToken: string | null;
  onSelect: (m: Market, outcome: string) => void;
}) {
  const primary = primaryOutcome(market);
  const token = market.tokens[primary];
  const chance = market.outcome_prices[primary];

  // Lazy, cached mini-chart for the headline outcome (coarse fidelity = small).
  const hist = useQuery({
    queryKey: ["cardhist", token],
    queryFn: () => api.history(token, "1d", 180),
    enabled: !!token,
    staleTime: 5 * 60_000,
  });
  const prices = (hist.data ?? []).map((p) => p.p);
  const up = market.one_day_price_change >= 0;

  return (
    <div className={`card ${styles.card}`}>
      <div className={styles.head}>
        <div className={styles.q}>{market.question}</div>
        <StarButton market={market} outcome={primary} />
      </div>

      <div className={styles.row}>
        <div>
          <div className={styles.chance} style={{ color: outcomeColor(primary) }}>
            {chance !== undefined ? `${Math.round(chance * 100)}%` : "—"}
          </div>
          <div className="small muted">{primary}</div>
        </div>
        <div className={styles.rightCol}>
          <span className={`small ${up ? "pos" : "neg"}`}>{up ? "▲" : "▼"} {(market.one_day_price_change * 100).toFixed(1)}%</span>
          <Sparkline points={prices} width={120} height={34} color={up ? "var(--green)" : "var(--red)"} />
        </div>
      </div>

      {/* chance-by-color bar: each outcome's width = its probability */}
      <div className={styles.bar}>
        {Object.entries(market.outcome_prices).map(([o, p]) => (
          <span key={o} style={{ width: `${p * 100}%`, background: outcomeColor(o) }} title={`${o} ${Math.round(p * 100)}%`} />
        ))}
      </div>

      <div className={styles.meta}>
        <span className="small muted">${Math.round(market.volume).toLocaleString()} vol</span>
        {endsIn(market.end_date) && (
          <span className="small" style={{ color: "var(--amber)" }}>
            {endsIn(market.end_date)}{localTime(market.end_date) && ` · ${localTime(market.end_date)}`}
          </span>
        )}
        {market.tradeable ? <span className="badge badge-green">tradeable</span> : <span className="badge">closed</span>}
      </div>

      <div className={styles.outcomes}>
        {Object.keys(market.tokens).map((o) => {
          const isSel = market.tokens[o] === selectedToken;
          return (
            <button key={o}
              className={`${styles.outcomeBtn} ${isSel ? styles.sel : ""}`}
              style={{ borderLeft: `3px solid ${outcomeColor(o)}` }}
              onClick={() => onSelect(market, o)}>
              {o}
              {market.outcome_prices[o] !== undefined && (
                <span className={styles.oPrice} style={{ color: outcomeColor(o) }}>{Math.round(market.outcome_prices[o] * 100)}%</span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
