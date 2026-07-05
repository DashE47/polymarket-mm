// Depth-of-market ladder: asks (red) on top descending to the touch, bids (green)
// below. Bar width = size relative to the largest level shown.

import type { Level } from "../api/types";
import styles from "./DepthLadder.module.css";

export default function DepthLadder({ bids, asks, depth = 10 }: { bids: Level[]; asks: Level[]; depth?: number }) {
  const topBids = bids.slice(0, depth);
  const topAsks = asks.slice(0, depth);
  const maxSize = Math.max(1, ...topBids.map((l) => l[1]), ...topAsks.map((l) => l[1]));

  const Row = ({ price, size, side }: { price: number; size: number; side: "bid" | "ask" }) => (
    <div className={styles.row}>
      <span className={`mono ${side === "bid" ? "pos" : "neg"}`}>{price.toFixed(3)}</span>
      <div className={styles.barTrack}>
        <div
          className={side === "bid" ? styles.bidBar : styles.askBar}
          style={{ width: `${(size / maxSize) * 100}%` }}
        />
      </div>
      <span className="mono small muted">{size.toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>
    </div>
  );

  return (
    <div className={styles.ladder}>
      {/* asks: show worst price on top, best ask just above the divider */}
      {[...topAsks].reverse().map(([p, s], i) => <Row key={`a${i}`} price={p} size={s} side="ask" />)}
      <div className={styles.divider} />
      {topBids.map(([p, s], i) => <Row key={`b${i}`} price={p} size={s} side="bid" />)}
    </div>
  );
}
