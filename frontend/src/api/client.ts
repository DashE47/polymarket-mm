// Typed client for the FastAPI backend. All REST calls go through the Vite dev
// proxy at /api (-> the API server); WebSockets go through /ws (same origin).

import type {
  BacktestResult, Book, HDEquity, HDGrid, HDJob, HDSummary, Market, RecordingStatus,
  RunSummary, Stats, StrategyParams, SweepRow, UpDownEquity, UpDownFile, UpDownGrid,
} from "./types";

export interface HDReplayParams {
  stake: number;
  max_spread: number;
  latency_ms: number;
  min_fill_frac: number;
}

const hdQuery = (p: HDReplayParams) =>
  `stake=${p.stake}&max_spread=${p.max_spread}&latency_ms=${p.latency_ms}&min_fill_frac=${p.min_fill_frac}`;

export interface UpDownParams {
  window_len: number;
  max_spread: number;
  fill_lag: number;
  min_size: number;
  file?: string;
}

const updownQuery = (p: UpDownParams) =>
  `window_len=${p.window_len}&max_spread=${p.max_spread}&fill_lag=${p.fill_lag}` +
  `&min_size=${p.min_size}${p.file ? `&file=${encodeURIComponent(p.file)}` : ""}`;

const BASE = "/api";

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error((await res.text()) || `GET ${path} failed (${res.status})`);
  return res.json() as Promise<T>;
}

async function postJSON<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error((await res.text()) || `POST ${path} failed (${res.status})`);
  return res.json() as Promise<T>;
}

// --- REST endpoints -------------------------------------------------------
export const api = {
  config: () => getJSON<Record<string, unknown>>("/config"),
  searchMarkets: (q: string, tradeableOnly = true, limit = 20) =>
    getJSON<Market[]>(`/markets/search?q=${encodeURIComponent(q)}&limit=${limit}&tradeable_only=${tradeableOnly}`),
  topMarkets: (limit = 24, tradeableOnly = true) =>
    getJSON<Market[]>(`/markets/top?limit=${limit}&tradeable_only=${tradeableOnly}`),
  cryptoUpDown: (limit = 24) => getJSON<Market[]>(`/markets/crypto-updown?limit=${limit}`),
  book: (tokenId: string) => getJSON<Book>(`/book/${tokenId}`),
  stats: (tokenId: string) => getJSON<Stats>(`/stats/${tokenId}`),
  history: (tokenId: string, interval = "1d", fidelity = 30) =>
    getJSON<{ t: number; p: number }[]>(`/history/${tokenId}?interval=${interval}&fidelity=${fidelity}`),
  recordings: () => getJSON<{ name: string; size_kb: number }[]>("/recordings"),
  runs: (limit = 15) => getJSON<RunSummary[]>(`/runs?limit=${limit}`),
  recordingStatus: () => getJSON<RecordingStatus>("/recordings/status"),
  startRecording: (tokenId: string, duration: number) =>
    postJSON<RecordingStatus>("/recordings/start", { token_id: tokenId, duration }),
  stopRecording: () => postJSON<RecordingStatus>("/recordings/stop", {}),
  account: () => getJSON<{ balance_pusd: number; allowance_pusd: number; positions: unknown[] }>("/account"),
  backtestHistory: (tokenId: string, interval: string, fidelity: number, params: StrategyParams) =>
    postJSON<BacktestResult>("/backtest", { source: "history", token_id: tokenId, interval, fidelity, params }),
  backtestRecording: (recording: string, params: StrategyParams) =>
    postJSON<BacktestResult>("/backtest", { source: "recording", recording, params }),
  sweep: (body: Record<string, unknown>) => postJSON<SweepRow[]>("/sweep", body),
  hdSummary: () => getJSON<HDSummary>("/hd/summary"),
  hdRecorderStart: (assets: string[], windows: number[]) =>
    postJSON<HDSummary["recorder"]>("/hd/recorder/start", { assets, windows }),
  hdRecorderStop: () => postJSON<HDSummary["recorder"]>("/hd/recorder/stop", {}),
  hdRecorderLog: (lines = 20) => getJSON<{ lines: string[] }>(`/hd/recorder/log?lines=${lines}`),
  hdResolveStart: () => postJSON<HDJob>("/hd/resolve/start", {}),
  hdReplayStart: (p: HDReplayParams) => postJSON<HDJob>("/hd/replay/start", p),
  hdGrid: (mode: string, windowLen: number, p: HDReplayParams) =>
    getJSON<HDGrid>(`/hd/replay/grid?mode=${mode}&window_len=${windowLen}&${hdQuery(p)}`),
  hdEquity: (mode: string, windowLen: number, thr: number, win: number, p: HDReplayParams) =>
    getJSON<HDEquity>(`/hd/replay/equity?mode=${mode}&window_len=${windowLen}&thr=${thr}&win=${win}&${hdQuery(p)}`),
  updownFiles: () => getJSON<UpDownFile[]>("/updown/files"),
  updownGrid: (p: UpDownParams) => getJSON<UpDownGrid>(`/updown/grid?${updownQuery(p)}`),
  updownEquity: (p: UpDownParams & { thr: number; win: number }) =>
    getJSON<UpDownEquity>(`/updown/equity?thr=${p.thr}&win=${p.win}&${updownQuery(p)}`),
};

// --- WebSocket URLs (same origin; Vite proxies /ws to the API) ------------
function wsBase(): string {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${location.host}`;
}

export const bookWsUrl = (tokenId: string) => `${wsBase()}/ws/book/${tokenId}`;

export const simWsUrl = (tokenId: string, p: StrategyParams, duration: number) =>
  `${wsBase()}/ws/sim/${tokenId}?spread=${p.spread}&size=${p.size}&skew=${p.skew}` +
  `&widen=${p.widen}&requote=${p.requote}&duration=${duration}`;
