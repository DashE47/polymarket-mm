// Star/watch markets. Persisted in the browser (localStorage). Each entry keeps
// the full Market + chosen outcome so tiles can re-select and re-fetch live data.

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import type { Market } from "../api/types";

export interface WatchItem { market: Market; outcome: string; }
const KEY = "pmm-watchlist";

export const tokenOf = (i: WatchItem) => i.market.tokens[i.outcome];

interface Ctx {
  items: WatchItem[];
  has: (tokenId: string) => boolean;
  toggle: (item: WatchItem) => void;
  remove: (tokenId: string) => void;
}

const C = createContext<Ctx | null>(null);

export function WatchlistProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<WatchItem[]>(() => {
    try { return JSON.parse(localStorage.getItem(KEY) || "[]"); } catch { return []; }
  });
  useEffect(() => { localStorage.setItem(KEY, JSON.stringify(items)); }, [items]);

  const has = (tid: string) => items.some((i) => tokenOf(i) === tid);
  const remove = (tid: string) => setItems((xs) => xs.filter((i) => tokenOf(i) !== tid));
  const toggle = (it: WatchItem) =>
    setItems((xs) => (xs.some((i) => tokenOf(i) === tokenOf(it))
      ? xs.filter((i) => tokenOf(i) !== tokenOf(it))
      : [...xs, it]));

  return <C.Provider value={{ items, has, toggle, remove }}>{children}</C.Provider>;
}

export function useWatchlist() {
  const c = useContext(C);
  if (!c) throw new Error("useWatchlist must be used within WatchlistProvider");
  return c;
}
