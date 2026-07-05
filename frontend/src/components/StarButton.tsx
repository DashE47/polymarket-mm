// Toggle a market+outcome in the watchlist. Used on market cards and the bar.

import type { Market } from "../api/types";
import { useWatchlist } from "../state/WatchlistContext";
import styles from "./StarButton.module.css";

export default function StarButton({ market, outcome }: { market: Market; outcome: string }) {
  const { has, toggle } = useWatchlist();
  const on = has(market.tokens[outcome]);
  return (
    <button
      className={`${styles.star} ${on ? styles.on : ""}`}
      title={on ? "Remove from watchlist" : "Add to watchlist"}
      aria-pressed={on}
      onClick={(e) => { e.stopPropagation(); toggle({ market, outcome }); }}
    >
      {on ? "★" : "☆"}
    </button>
  );
}
