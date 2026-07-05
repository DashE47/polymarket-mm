// Market Explorer: browse trending markets or a category, or search by name.
// Results show as cards with each outcome's live chance + a mini price chart.
// Picking an outcome stores it globally for the other pages.

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { useSelection } from "../state/SelectionContext";
import { useToast } from "../components/Toast";
import MarketCard from "../components/MarketCard";
import CryptoUpDown from "../components/CryptoUpDown";
import MarketBar from "../components/MarketBar";
import { SkeletonCard } from "../components/Skeleton";
import type { Market } from "../api/types";
import styles from "./Explorer.module.css";

const CATEGORIES = ["Trending", "↕ Up/Down", "Crypto", "Politics", "Sports", "Economy", "Tech", "World"];
const UPDOWN = "↕ Up/Down";

export default function Explorer() {
  const { select, tokenId, market, outcome } = useSelection();
  const toast = useToast();
  const onSelect = (m: Market, o: string) => {
    select(m, o);
    toast(`Selected ${m.question} [${o}]`, "success");
  };
  const [cat, setCat] = useState("Trending");
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [minPct, setMinPct] = useState(0);
  const [maxPct, setMaxPct] = useState(100);

  // The headline (Yes/first) outcome's chance, as a 0–100 percentage.
  const chancePct = (m: Market) => {
    const k = Object.keys(m.tokens).find((x) => x.toLowerCase() === "yes") ?? Object.keys(m.tokens)[0];
    return Math.round((m.outcome_prices[k] ?? 0) * 100);
  };

  // What to load: a typed search term wins; otherwise the active category
  // ("Trending" → top markets by volume; anything else → search that word).
  const source = submitted
    ? { kind: "search" as const, q: submitted }
    : cat === UPDOWN
      ? { kind: "updown" as const }
      : cat === "Trending"
        ? { kind: "top" as const }
        : { kind: "search" as const, q: cat };

  const results = useQuery({
    queryKey: ["explore", source],
    queryFn: () =>
      source.kind === "top" ? api.topMarkets(24)
        : source.kind === "updown" ? api.cryptoUpDown(48)
          : api.searchMarkets(source.q, true, 24),
    // Up/Down buckets roll over every few minutes — keep them fresh.
    refetchInterval: source.kind === "updown" ? 20_000 : false,
  });

  const heading = submitted ? `Results for “${submitted}”`
    : cat === UPDOWN ? "Live crypto Up/Down — short-term, rolling"
      : cat === "Trending" ? "Trending markets" : `${cat} markets`;

  return (
    <div className="col">
      <h1>Market Explorer</h1>

      <form className={styles.searchRow} onSubmit={(e) => { e.preventDefault(); setSubmitted(query.trim()); }}>
        <input className={styles.search} placeholder="Search markets by name — bitcoin, election, world cup…"
               value={query} onChange={(e) => setQuery(e.target.value)} />
        {submitted && <button type="button" className="btn" onClick={() => { setSubmitted(""); setQuery(""); }}>Clear</button>}
        <button className="btn btn-primary" type="submit">Search</button>
      </form>

      <div className={styles.chips}>
        {CATEGORIES.map((c) => (
          <button key={c}
            className={`${styles.chip} ${!submitted && cat === c ? styles.chipActive : ""}`}
            onClick={() => { setCat(c); setSubmitted(""); setQuery(""); }}>
            {c}
          </button>
        ))}
      </div>

      {source.kind !== "updown" && (
        <div className={styles.filter}>
          <span className="small muted">Filter by chance</span>
          <input type="number" min={0} max={100} value={minPct} onChange={(e) => setMinPct(+e.target.value)} style={{ width: 64 }} />
          <span className="small muted">to</span>
          <input type="number" min={0} max={100} value={maxPct} onChange={(e) => setMaxPct(+e.target.value)} style={{ width: 64 }} />
          <span className="small muted">%</span>
          {(minPct > 0 || maxPct < 100) && <button className="btn" onClick={() => { setMinPct(0); setMaxPct(100); }}>clear</button>}
        </div>
      )}

      <h2 className="muted" style={{ marginBottom: 0 }}>{heading}</h2>
      {results.isError && <p className="neg">Couldn’t load markets — is the API running?</p>}
      {results.data && results.data.length === 0 && <p className="muted">Nothing here — try another search or category.</p>}

      {results.isLoading && (
        <div className={styles.grid}>
          {Array.from({ length: 8 }).map((_, i) => <SkeletonCard key={i} />)}
        </div>
      )}

      {results.data && results.data.length > 0 && source.kind === "updown" && (
        <CryptoUpDown markets={results.data} selectedToken={tokenId} onSelect={onSelect} />
      )}

      {results.data && results.data.length > 0 && source.kind !== "updown" && (() => {
        const shown = results.data.filter((m) => { const c = chancePct(m); return c >= minPct && c <= maxPct; });
        return shown.length > 0 ? (
          <div className={styles.grid}>
            {shown.map((m) => <MarketCard key={m.condition_id} market={m} selectedToken={tokenId} onSelect={onSelect} />)}
          </div>
        ) : <p className="muted">No markets between {minPct}% and {maxPct}% chance — widen the range.</p>;
      })()}

      {tokenId && (
        <div className="col">
          <h2>Selected — {market?.question} [{outcome}]</h2>
          <MarketBar tokenId={tokenId} />
        </div>
      )}
    </div>
  );
}
