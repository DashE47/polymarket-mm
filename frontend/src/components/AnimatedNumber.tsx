// A number that smoothly tweens to its new value and briefly flashes green (up)
// or red (down) when it changes — the core "alive" feel for live prices/P&L.

import { useEffect, useRef, useState } from "react";
import styles from "./AnimatedNumber.module.css";

interface Props {
  value: number | null | undefined;
  dp?: number;
  prefix?: string;
  suffix?: string;
}

export default function AnimatedNumber({ value, dp = 3, prefix = "", suffix = "" }: Props) {
  const [display, setDisplay] = useState(value ?? 0);
  const [dir, setDir] = useState<"up" | "down" | "">("");
  const prev = useRef(value ?? 0);
  const raf = useRef<number>();

  useEffect(() => {
    if (value === null || value === undefined) return;
    const from = prev.current;
    const to = value;
    if (from === to) return;
    setDir(to > from ? "up" : "down");

    const start = performance.now();
    const dur = 300;
    const step = (now: number) => {
      const t = Math.min(1, (now - start) / dur);
      const eased = 1 - Math.pow(1 - t, 3); // ease-out cubic
      setDisplay(from + (to - from) * eased);
      if (t < 1) {
        raf.current = requestAnimationFrame(step);
      } else {
        setDisplay(to);
        prev.current = to;
        window.setTimeout(() => setDir(""), 400);
      }
    };
    if (raf.current) cancelAnimationFrame(raf.current);
    raf.current = requestAnimationFrame(step);
    return () => {
      if (raf.current) cancelAnimationFrame(raf.current);
    };
  }, [value]);

  if (value === null || value === undefined) return <span>—</span>;
  return (
    <span className={`${styles.num} ${dir === "up" ? styles.up : dir === "down" ? styles.down : ""}`}>
      {prefix}{display.toFixed(dp)}{suffix}
    </span>
  );
}
