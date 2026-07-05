// Global "currently selected market" — set on the Explorer page, read everywhere
// (Order Book, Strategy Lab, Recorder) so you pick a market once.

import { createContext, useContext, useState, type ReactNode } from "react";
import type { Market } from "../api/types";

interface Selection {
  market: Market | null;
  outcome: string | null;
  tokenId: string | null;
  select: (market: Market, outcome: string) => void;
}

const Ctx = createContext<Selection | null>(null);

export function SelectionProvider({ children }: { children: ReactNode }) {
  const [market, setMarket] = useState<Market | null>(null);
  const [outcome, setOutcome] = useState<string | null>(null);

  const select = (m: Market, o: string) => {
    setMarket(m);
    setOutcome(o);
  };

  const tokenId = market && outcome ? market.tokens[outcome] : null;
  return <Ctx.Provider value={{ market, outcome, tokenId, select }}>{children}</Ctx.Provider>;
}

export function useSelection(): Selection {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useSelection must be used within SelectionProvider");
  return ctx;
}
