// Polymarket-style view of the live short-term crypto "Up or Down" markets:
// grouped by asset, each showing its upcoming time buckets in sequence (times in
// the user's local zone). Pick Up (green) or Down (magenta) on any bucket.

import type { Market } from "../api/types";
import { localTime } from "../lib/time";
import styles from "./CryptoUpDown.module.css";

const ASSET_ORDER = ["Bitcoin", "Ethereum", "Solana", "XRP", "BNB", "Dogecoin", "Hyperliquid"];
const assetOf = (m: Market) => m.question.split(/\s+up or down/i)[0].trim();

export default function CryptoUpDown({
  markets, selectedToken, onSelect,
}: {
  markets: Market[];
  selectedToken: string | null;
  onSelect: (m: Market, outcome: string) => void;
}) {
  // Group by asset, each sorted soonest-first.
  const groups = new Map<string, Market[]>();
  for (const m of markets) {
    const a = assetOf(m);
    (groups.get(a) ?? groups.set(a, []).get(a)!).push(m);
  }
  for (const list of groups.values()) list.sort((x, y) => x.end_date.localeCompare(y.end_date));

  const assets = [...groups.keys()].sort((a, b) => {
    const ia = ASSET_ORDER.indexOf(a), ib = ASSET_ORDER.indexOf(b);
    return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib) || a.localeCompare(b);
  });

  if (assets.length === 0) {
    return <div className="card muted">No short-term crypto Up/Down markets are live right now — they roll over every few minutes, so check back shortly.</div>;
  }

  return (
    <div className="col">
      {assets.map((asset) => (
        <div key={asset} className={`card ${styles.panel}`}>
          <div className={styles.head}>
            <span className={styles.asset}>{asset}</span>
            <span className="small muted">Up or Down · next buckets · your time</span>
          </div>
          <div className={styles.row}>
            {(groups.get(asset) ?? []).map((m, i) => {
              const up = m.outcome_prices["Up"] ?? 0;
              const down = m.outcome_prices["Down"] ?? 0;
              const sel = m.tokens["Up"] === selectedToken || m.tokens["Down"] === selectedToken;
              return (
                <div key={m.condition_id} className={`${styles.tile} ${sel ? styles.sel : ""}`}>
                  <div className={styles.time}>{localTime(m.end_date) || "—"}{i === 0 && <span className={styles.next}>next</span>}</div>
                  <div className={styles.split}>
                    <span style={{ width: `${up * 100}%`, background: "var(--green)" }} />
                    <span style={{ width: `${down * 100}%`, background: "var(--red)" }} />
                  </div>
                  <div className={styles.btns}>
                    <button className={styles.up} onClick={() => onSelect(m, "Up")}>Up {Math.round(up * 100)}%</button>
                    <button className={styles.down} onClick={() => onSelect(m, "Down")}>Down {Math.round(down * 100)}%</button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}
