// A calm, browsable glossary. Search or skim by category — every concept the
// app uses, explained in plain English with an example.

import { useState } from "react";
import { GLOSSARY, type Term } from "../content/glossary";
import QuoteSimulator from "../components/QuoteSimulator";
import styles from "./Learn.module.css";

const CATEGORIES: Term["category"][] = ["Order book", "Strategy", "P&L", "General"];

export default function Learn() {
  const [q, setQ] = useState("");
  const needle = q.trim().toLowerCase();
  const match = (t: Term) =>
    !needle || `${t.term} ${t.short} ${t.long}`.toLowerCase().includes(needle);

  return (
    <div className="col">
      <h1>Learn</h1>
      <p className="muted">Every term in the app, in plain English. Hover the “?” icons anywhere to get a quick reminder, or browse here.</p>

      <QuoteSimulator />

      <h2 style={{ marginTop: "var(--s2)" }}>Glossary</h2>
      <input className={styles.search} placeholder="Search concepts — spread, skew, drawdown…"
             value={q} onChange={(e) => setQ(e.target.value)} />

      {CATEGORIES.map((cat) => {
        const terms = GLOSSARY.filter((t) => t.category === cat && match(t));
        if (terms.length === 0) return null;
        return (
          <section key={cat} className="col" style={{ gap: "var(--s3)" }}>
            <h2 className={styles.cat}>{cat}</h2>
            <div className={styles.grid}>
              {terms.map((t) => (
                <div key={t.key} className={`card ${styles.item}`}>
                  <div className={styles.termRow}>
                    <strong>{t.term}</strong>
                  </div>
                  <div className={styles.short}>{t.short}</div>
                  <div className="muted">{t.long}</div>
                  {t.example && <div className={styles.ex}>e.g. {t.example}</div>}
                </div>
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}
