// A small "?" you can place next to any term. Hover or focus (keyboard/tap)
// reveals a friendly one-liner from the glossary. Deeper detail lives on /learn.

import { byKey } from "../content/glossary";
import styles from "./InfoTip.module.css";

export default function InfoTip({ term }: { term: string }) {
  const t = byKey[term];
  if (!t) return null;
  return (
    <span className={styles.tip} tabIndex={0} aria-label={`What is ${t.term}?`}>
      <span className={styles.icon} aria-hidden>?</span>
      <span className={styles.pop} role="tooltip">
        <strong className={styles.term}>{t.term}</strong>
        <span className={styles.short}>{t.short}</span>
        {t.example && <span className={styles.ex}>e.g. {t.example}</span>}
      </span>
    </span>
  );
}
