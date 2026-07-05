// Interactive explainer: set your spread + skew, then drag the market price.
// When it dips to your bid you BUY; when it rises to your ask you SELL. Watch
// inventory build and feel adverse selection — no real data, just intuition.

import { useRef, useState } from "react";
import styles from "./QuoteSimulator.module.css";

const PMIN = 0.4, PMAX = 0.6, MID = 0.5, MAX_INV = 5;
const clampP = (p: number) => Math.max(PMIN + 0.01, Math.min(PMAX - 0.01, p));
// Map a price to a y pixel in the 0..260 plot (top = PMAX).
const y = (p: number) => 20 + (1 - (p - PMIN) / (PMAX - PMIN)) * 230;

export default function QuoteSimulator() {
  const [spread, setSpread] = useState(0.04);
  const [skew, setSkew] = useState(0);
  const [market, setMarket] = useState(MID);
  const [inventory, setInventory] = useState(0);
  const [cash, setCash] = useState(0);
  const [flash, setFlash] = useState<"up" | "down" | "">("");
  const [log, setLog] = useState<string[]>([]);
  const prev = useRef(MID);

  const quotesFor = (inv: number) => {
    const reservation = MID - skew * (inv / MAX_INV);
    return { bid: clampP(reservation - spread / 2), ask: clampP(reservation + spread / 2) };
  };
  const { bid, ask } = quotesFor(inventory);
  const pnl = cash + inventory * market;

  const onMarket = (v: number) => {
    const p = prev.current;
    let inv = inventory, c = cash, ev = "";
    if (v <= bid && p > bid && inv < MAX_INV) {
      inv++; c -= bid; ev = `▲ Bought @ ${bid.toFixed(3)} — the market dipped to your bid`;
      setFlash("up"); setTimeout(() => setFlash(""), 600);
    } else if (v >= ask && p < ask && inv > -MAX_INV) {
      inv--; c += ask; ev = `▼ Sold @ ${ask.toFixed(3)} — the market rose to your ask`;
      setFlash("down"); setTimeout(() => setFlash(""), 600);
    }
    prev.current = v;
    setMarket(v);
    if (inv !== inventory) { setInventory(inv); setCash(c); setLog((l) => [ev, ...l].slice(0, 4)); }
  };

  const reset = () => { setInventory(0); setCash(0); setMarket(MID); setLog([]); prev.current = MID; };

  return (
    <div className={`card ${styles.wrap}`}>
      <h2>🎮 Try it: be the market maker</h2>
      <p className="muted small" style={{ marginTop: 0 }}>
        Set your spread and skew, then <strong>drag the market price</strong>. You buy at your bid, sell at your ask.
      </p>

      <div className={styles.layout}>
        <svg viewBox="0 0 300 270" className={styles.svg} role="img" aria-label="quote simulator">
          {/* spread band */}
          <rect x="60" y={y(ask)} width="200" height={Math.max(0, y(bid) - y(ask))} fill="var(--accent-weak)" />
          {/* mid */}
          <line x1="60" y1={y(MID)} x2="260" y2={y(MID)} stroke="var(--text-muted)" strokeDasharray="4 4" />
          <text x="262" y={y(MID) + 4} fontSize="10" fill="var(--text-muted)">fair 0.50</text>
          {/* ask */}
          <line x1="60" y1={y(ask)} x2="260" y2={y(ask)} stroke="var(--red)" strokeWidth="2" />
          <text x="6" y={y(ask) + 4} fontSize="11" fill="var(--red)">ask {ask.toFixed(3)}</text>
          {/* bid */}
          <line x1="60" y1={y(bid)} x2="260" y2={y(bid)} stroke="var(--green)" strokeWidth="2" />
          <text x="6" y={y(bid) + 4} fontSize="11" fill="var(--green)">bid {bid.toFixed(3)}</text>
          {/* market marker */}
          <line x1="60" y1={y(market)} x2="260" y2={y(market)} stroke="var(--accent)" strokeWidth="2" />
          <polygon points={`260,${y(market)} 270,${y(market) - 5} 270,${y(market) + 5}`} fill="var(--accent)" />
          <text x="100" y={y(market) - 6} fontSize="11" fontWeight="700" fill="var(--accent)">market {market.toFixed(3)}</text>
        </svg>

        <div className={styles.controls}>
          <label>Market price — drag me <input type="range" min={PMIN} max={PMAX} step={0.005} value={market} onChange={(e) => onMarket(+e.target.value)} /></label>
          <label>Spread <input type="range" min={0.01} max={0.1} step={0.005} value={spread} onChange={(e) => setSpread(+e.target.value)} /> <span className="mono small">{spread.toFixed(3)}</span></label>
          <label>Inventory skew <input type="range" min={0} max={0.05} step={0.005} value={skew} onChange={(e) => setSkew(+e.target.value)} /> <span className="mono small">{skew.toFixed(3)}</span></label>

          <div className={styles.stats}>
            <div><span className="small muted">Inventory</span><div className={styles.statV}>{inventory > 0 ? "+" : ""}{inventory}</div></div>
            <div><span className="small muted">P&L (mark-to-mkt)</span><div className={`${styles.statV} ${pnl >= 0 ? "pos" : "neg"} ${flash === "up" ? styles.fu : flash === "down" ? styles.fd : ""}`}>{pnl >= 0 ? "+" : ""}{pnl.toFixed(3)}</div></div>
            <button className="btn" onClick={reset}>Reset</button>
          </div>
        </div>
      </div>

      <div className={styles.log}>
        {log.length === 0
          ? <span className="muted small">Drag the market price down past your bid, or up past your ask, to trade.</span>
          : log.map((l, i) => <div key={i} className="small">{l}</div>)}
      </div>
      {Math.abs(inventory) >= 3 && (
        <p className={`small ${styles.lesson}`}>
          👀 Notice: dragging one direction keeps filling you on that side, piling up inventory at worse and worse prices.
          That's <strong>adverse selection</strong> — and why a market maker uses <strong>skew</strong> (try raising it) to lean against inventory.
        </p>
      )}
    </div>
  );
}
