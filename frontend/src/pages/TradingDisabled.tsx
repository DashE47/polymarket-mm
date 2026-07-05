export default function TradingDisabled() {
  return (
    <div>
      <h1>Live Trading</h1>
      <div className="card" style={{ borderColor: "var(--red)" }}>
        <span className="badge badge-red">disabled</span>
        <p>Live trading is not implemented. This app is simulation-only.</p>
        <p className="muted small">
          Any future live trading must pass two gates in .env: MODE=live AND
          CONFIRM_LIVE=YES. Until then there are no working controls here.
        </p>
        <button className="btn" disabled>Place order</button>
      </div>
    </div>
  );
}
