// ⌘K / Ctrl+K command palette: jump to any page, or search markets and open one.
// Keyboard: ⌘K toggles, ↑/↓ move, Enter selects, Esc closes.

import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { useSelection } from "../state/SelectionContext";
import { useToast } from "./Toast";
import styles from "./CommandPalette.module.css";

const PAGES: [string, string][] = [
  ["/", "Mission Control"], ["/hdlab", "HD Lab (Up/Down bot)"],
  ["/explorer", "Market Explorer"], ["/book", "Live Order Book"],
  ["/lab", "Strategy Lab"], ["/analytics", "Backtest & Analytics"], ["/sweep", "Parameter Sweep"],
  ["/recorder", "Book Recorder"], ["/learn", "Learn / Glossary"], ["/trading", "Live Trading"],
];

type Item =
  | { type: "page"; to: string; label: string }
  | { type: "market"; label: string; market: import("../api/types").Market };

export default function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [dq, setDq] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();
  const { select } = useSelection();
  const toast = useToast();

  // Global hotkey.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      } else if (e.key === "Escape") {
        setOpen(false);
      }
    };
    const onOpen = () => setOpen(true); // fired by the sidebar search button
    window.addEventListener("keydown", onKey);
    window.addEventListener("open-cmdk", onOpen);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("open-cmdk", onOpen);
    };
  }, []);

  useEffect(() => {
    if (open) {
      setQ(""); setDq(""); setActive(0);
      setTimeout(() => inputRef.current?.focus(), 30);
    }
  }, [open]);

  // Debounce the market search.
  useEffect(() => {
    const t = setTimeout(() => setDq(q.trim()), 200);
    return () => clearTimeout(t);
  }, [q]);

  const search = useQuery({
    queryKey: ["cmd", dq],
    queryFn: () => api.searchMarkets(dq, true, 8),
    enabled: open && dq.length >= 2,
  });

  const pages: Item[] = PAGES.filter(([, l]) => l.toLowerCase().includes(q.toLowerCase()))
    .map(([to, label]) => ({ type: "page", to, label }));
  const markets: Item[] = (search.data ?? []).map((m) => ({ type: "market", label: m.question, market: m }));
  const items = [...pages, ...markets];

  const run = (item: Item) => {
    if (item.type === "page") {
      navigate(item.to);
    } else {
      const outcome = Object.keys(item.market.tokens).find((k) => k.toLowerCase() === "yes")
        ?? Object.keys(item.market.tokens)[0];
      select(item.market, outcome);
      toast(`Selected ${item.market.question}`, "success");
      navigate("/book");
    }
    setOpen(false);
  };

  if (!open) return null;

  return (
    <div className={styles.backdrop} onClick={() => setOpen(false)}>
      <div className={styles.panel} onClick={(e) => e.stopPropagation()}>
        <input
          ref={inputRef}
          className={styles.input}
          placeholder="Jump to a page, or search markets…"
          value={q}
          onChange={(e) => { setQ(e.target.value); setActive(0); }}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, items.length - 1)); }
            else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
            else if (e.key === "Enter" && items[active]) { e.preventDefault(); run(items[active]); }
          }}
        />
        <div className={styles.list}>
          {pages.length > 0 && <div className={styles.section}>Pages</div>}
          {items.map((item, i) => {
            if (item.type === "page" && i === 0) { /* fallthrough */ }
            const isMarketStart = item.type === "market" && (i === 0 || items[i - 1].type === "page");
            return (
              <div key={i}>
                {isMarketStart && <div className={styles.section}>Markets {search.isFetching && "…"}</div>}
                <button
                  className={`${styles.row} ${i === active ? styles.active : ""}`}
                  onMouseEnter={() => setActive(i)}
                  onClick={() => run(item)}
                >
                  <span className={styles.rowLabel}>{item.label}</span>
                  <span className={styles.rowKind}>{item.type === "page" ? "Page" : "↵ open"}</span>
                </button>
              </div>
            );
          })}
          {dq.length >= 2 && markets.length === 0 && !search.isFetching && (
            <div className={styles.empty}>No markets match “{dq}”.</div>
          )}
        </div>
        <div className={styles.footer}><kbd>↑</kbd><kbd>↓</kbd> move · <kbd>↵</kbd> select · <kbd>esc</kbd> close</div>
      </div>
    </div>
  );
}
