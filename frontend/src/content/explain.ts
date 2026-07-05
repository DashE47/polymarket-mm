// Turn a backtest's numbers into a plain-English paragraph — the "explain this
// result" feature. Pure rules over the summary + price series; no LLM needed.

import type { Series, SummaryRow } from "../api/types";

export function explainResult(s: SummaryRow, series: Series): string {
  if (s.fills === 0) {
    return "No fills — your quotes never got hit. The market's touch didn't move far enough to reach them. Try a tighter spread, a more active/volatile market, or quoting closer to the touch.";
  }

  const mids = series.mid.filter((x) => typeof x === "number");
  const move = mids.length > 1 ? mids[mids.length - 1] - mids[0] : 0;
  const trend = Math.abs(move) < 0.005 ? "stayed roughly flat" : move > 0 ? "trended up" : "trended down";
  const pos = s.final_position;
  const side = pos > 0 ? "long" : pos < 0 ? "short" : "flat";
  const parts: string[] = [];

  if (s.total_pnl >= 0) {
    parts.push(`Net positive (+${s.total_pnl.toFixed(2)} pUSD). You captured the spread on ${Math.round(s.win_rate * 100)}% of round-trips while the price ${trend}, and kept inventory manageable.`);
  } else {
    parts.push(`Net loss (${s.total_pnl.toFixed(2)} pUSD).`);
    if (Math.abs(pos) >= 100 && Math.abs(move) >= 0.005) {
      const which = pos > 0 ? "bids kept filling as the price fell" : "asks kept filling as the price rose";
      parts.push(`You ended ${side} ${Math.abs(pos).toFixed(0)} shares while the price ${trend} — classic adverse selection: your ${which}, so unrealized losses (${s.unrealized_pnl.toFixed(2)}) dominated.`);
    } else if (s.win_rate < 0.5) {
      parts.push(`Most round-trips lost — often a sign that skew is dragging your quotes back through your own entry, or the spread is too tight to cover the moves you're getting filled on.`);
    } else {
      parts.push(`Round-trips were mostly okay, but a few large adverse fills outweighed the small wins.`);
    }
  }

  if (s.max_drawdown > Math.abs(s.total_pnl) * 2 && s.max_drawdown > 1) {
    parts.push(`It was a bumpy ride — peak-to-trough drawdown reached ${s.max_drawdown.toFixed(2)}.`);
  }
  return parts.join(" ");
}
