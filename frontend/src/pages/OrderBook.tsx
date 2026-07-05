// Live Order Book: market bar + streaming top-of-book metrics + depth ladder +
// live mid sparkline, fed by the /ws/book WebSocket.

import { useSelection } from "../state/SelectionContext";
import { useBookStream } from "../hooks/useBookStream";
import MarketBar from "../components/MarketBar";
import DepthLadder from "../components/DepthLadder";
import DepthCurve from "../components/DepthCurve";
import Sparkline from "../components/Sparkline";
import InfoTip from "../components/InfoTip";
import AnimatedNumber from "../components/AnimatedNumber";
import styles from "./OrderBook.module.css";

export default function OrderBook() {
  const { tokenId, market, outcome } = useSelection();
  const { frame, connected } = useBookStream(tokenId);

  if (!tokenId) {
    return (
      <div>
        <h1>Live Order Book</h1>
        <div className="card muted">Select a market in the Market Explorer first.</div>
      </div>
    );
  }

  return (
    <div className="col">
      <h1>Live Order Book</h1>
      <div className="muted small">{market?.question} [{outcome}]</div>
      <MarketBar tokenId={tokenId} />

      <div className={styles.metrics}>
        <Stat label="Best bid" term="bid" value={frame?.best_bid} cls="pos" />
        <Stat label="Best ask" term="ask" value={frame?.best_ask} cls="neg" />
        <Stat label="Mid" term="mid" value={frame?.mid} />
        <Stat label="Spread" term="spread" value={frame?.spread} />
      </div>

      <div className="card">
        <h2>Cumulative depth</h2>
        {frame ? <DepthCurve bids={frame.bids} asks={frame.asks} /> : <p className="muted">Waiting for data…</p>}
      </div>

      <div className="row" style={{ alignItems: "flex-start" }}>
        <div className="card" style={{ flex: 1 }}>
          <h2>Depth ladder</h2>
          {frame ? <DepthLadder bids={frame.bids} asks={frame.asks} depth={10} /> : <p className="muted">Waiting for data…</p>}
        </div>
        <div className="card" style={{ flex: 1 }}>
          <h2>Mid price (live)</h2>
          <Sparkline points={frame?.mid_vals ?? []} width={420} height={120}
                     color={(frame?.mid_vals?.length ?? 0) > 1 && frame!.mid_vals[frame!.mid_vals.length - 1] >= frame!.mid_vals[0] ? "var(--green)" : "var(--red)"} />
          <div className="small muted">
            {connected ? "🟢 live" : "⚪ connecting…"} · {frame?.updates ?? 0} updates
          </div>
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value, cls, term }: { label: string; value: number | null | undefined; cls?: string; term?: string }) {
  return (
    <div className="card" style={{ padding: "var(--s3) var(--s4)" }}>
      <div className="small muted">{label}{term && <InfoTip term={term} />}</div>
      <div className={`mono ${cls ?? ""}`} style={{ fontSize: 22, fontWeight: 700 }}>
        <AnimatedNumber value={value} dp={3} />
      </div>
    </div>
  );
}
