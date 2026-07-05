// TypeScript shapes mirroring the FastAPI JSON responses (see api/main.py).

export interface Market {
  question: string;
  slug: string;
  condition_id: string;
  tokens: Record<string, string>; // outcome -> token_id
  tradeable: boolean;
  active: boolean;
  closed: boolean;
  volume: number;
  liquidity: number;
  one_day_price_change: number;
  one_hour_price_change: number;
  end_date: string;
  outcome_prices: Record<string, number>; // outcome -> current implied price
}

export type Level = [number, number]; // [price, size]

export interface Book {
  token_id: string;
  best_bid: number | null;
  best_ask: number | null;
  mid: number | null;
  spread: number | null;
  tick_size: number | null;
  bids: Level[];
  asks: Level[];
}

export interface Stats {
  token_id: string;
  condition_id: string | null;
  best_bid: number | null;
  best_ask: number | null;
  mid: number | null;
  spread: number | null;
  tick_size: number | null;
  last_trade_price: number | null;
  question?: string;
  volume?: number;
  liquidity?: number;
  one_day_price_change?: number;
  one_hour_price_change?: number;
  end_date?: string;
  tradeable?: boolean;
}

export interface SummaryRow {
  total_pnl: number;
  realized_pnl: number;
  unrealized_pnl: number;
  fills: number;
  win_rate: number;
  avg_spread_captured: number;
  max_abs_inventory: number;
  max_drawdown: number;
  sharpe: number;
  fills_per_min: number;
  final_position: number;
  halted: boolean;
}

export interface Series {
  t: number[];
  total: number[];
  realized: number[];
  unrealized: number[];
  position: number[];
  mid: number[];
}

export interface BacktestResult {
  token_id: string;
  source: string;
  summary: SummaryRow;
  series: Series;
}

export type SweepRow = SummaryRow & { spread: number; size: number; skew: number };

export interface StrategyParams {
  spread: number;
  size: number;
  skew: number;
  widen: number;
  requote: number;
}

export interface RecordingStatus {
  running: boolean;
  count: number;
  path: string | null;
}

export interface RunSummary {
  file: string;
  mtime: number;
  total_pnl: number;
  fills: number;
  win_rate: number;
  source: string;
}

// --- Up/Down study (live threshold lab) ----------------------------------
export interface UpDownFile {
  name: string;
  size_kb: number;
  mtime: number;
}

export interface UpDownCell {
  edge: number | null; // hit% − paid%, in percentage points
  bets: number;
  pnl_per_bet: number | null;
}

export interface UpDownGrid {
  file: string;
  updated: number;
  window_len: number;
  buckets: number;
  by_asset: Record<string, number>;
  base_up_rate: number | null;
  thresholds: number[];
  windows: number[];
  grid: UpDownCell[][]; // rows = thresholds, cols = windows
  min_sample: number;
}

// --- HD research (record → resolve → exact-fill replay) -------------------
export interface HDJob {
  running: boolean;
  error: string | null;
  [k: string]: unknown;
}

export interface HDSummary {
  buckets: number;
  by_window: Record<string, number>;
  by_asset: Record<string, number>;
  resolved: number;
  unresolved: number;
  size_mb: number;
  disk_free_gb: number;
  newest_end_ts: number | null;
  recent_writes: number;
  recorder: { running: boolean; pid: number | null; uptime_s: number | null; args: { assets: string[]; windows: number[] } | null };
  resolver: HDJob & { checked: number; settled: number; pending: number };
  replay: HDJob & { done: number; total: number; fresh: number };
}

export interface HDCell {
  thr: number;
  win: number;
  bets: number;
  entered: number;
  hit: number | null;
  paid: number | null;
  edge: number | null;
  pnl_per_bet: number | null;
  fill: number | null;
  slip_c: number | null;
}

export interface HDGrid {
  mode: string;
  window_len: number;
  thresholds: number[];
  windows: number[];
  cells: HDCell[];
  cached: number;
  total: number;
  complete: boolean;
  buckets_settled: number;
  min_sample: number;
}

export interface HDEquityRow {
  end_ts: number;
  asset: string;
  side: string;
  avg: number;
  won: boolean;
  pnl: number;
}

export interface HDEquity {
  thr: number;
  win: number;
  mode: string;
  n: number;
  wins: number;
  hit: number | null;
  final: number;
  per_bet: number | null;
  max_drawdown: number;
  cum: number[];
  rows: HDEquityRow[];
}

export interface UpDownEquity {
  thr: number;
  win: number;
  n: number;
  wins: number;
  hit: number | null;
  final: number;
  per_bet: number | null;
  max_drawdown: number;
  first: string | null;
  last: string | null;
  cum: number[];
}

// WebSocket frames
export interface BookFrame {
  best_bid: number | null;
  best_ask: number | null;
  mid: number | null;
  spread: number | null;
  tick: number | null;
  bids: Level[];
  asks: Level[];
  mid_times: number[];
  mid_vals: number[];
  updates: number;
}

export interface Fill {
  side: string;
  price: number;
  size: number;
  position: number;
  realized_pnl: number;
}

// The live-sim summary (from SimEngine.summary()) differs from the backtest
// scorecard (SummaryRow): it reports current position + a halt reason.
export interface SimSummary {
  cycles: number;
  fills: number;
  buys: number;
  sells: number;
  position: number;
  avg_price: number;
  realized_pnl: number;
  unrealized_pnl: number;
  total_pnl: number;
  halted: boolean;
  halt_reason: string;
}

export interface SimFrame {
  waiting: boolean;
  running: boolean;
  summary?: SimSummary;
  fills?: Fill[];
  series?: Series;
}
