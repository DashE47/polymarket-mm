// Shimmering placeholders shown while data loads — calmer than "Loading…".

import styles from "./Skeleton.module.css";

export function Skeleton({ h = 16, w = "100%", r = 6 }: { h?: number | string; w?: number | string; r?: number }) {
  return <div className={styles.sk} style={{ height: h, width: w, borderRadius: r }} />;
}

/** A placeholder shaped like a MarketCard, for the Explorer grid. */
export function SkeletonCard() {
  return (
    <div className="card" style={{ padding: "var(--s4)", display: "flex", flexDirection: "column", gap: "var(--s3)" }}>
      <Skeleton h={14} w="85%" />
      <Skeleton h={14} w="60%" />
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end" }}>
        <Skeleton h={30} w={70} />
        <Skeleton h={34} w={120} />
      </div>
      <div style={{ display: "flex", gap: "var(--s2)" }}>
        <Skeleton h={32} w="50%" />
        <Skeleton h={32} w="50%" />
      </div>
    </div>
  );
}
