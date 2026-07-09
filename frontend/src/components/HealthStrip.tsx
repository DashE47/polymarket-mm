import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import styles from "./HealthStrip.module.css";

/**
 * System-health strip: is every daemon alive, and is data actually flowing?
 * Exists because our worst incidents were SILENT process death (recorder died
 * in a reboot and cost us two days of forensics; a paper trader ran unnoticed).
 * Optional desktop notifications fire on any healthy -> down transition.
 */

type Pill = { key: string; label: string; ok: boolean | null; detail: string };

export default function HealthStrip() {
  const hd = useQuery({ queryKey: ["hdSummary"], queryFn: api.hdSummary, refetchInterval: 10000, retry: 1 });
  const paper = useQuery({ queryKey: ["paperStatus"], queryFn: api.paperStatus, refetchInterval: 10000, retry: 1 });

  const apiOk = !(hd.isError && paper.isError);
  const s = hd.data;
  const recOk = s ? s.recorder.running || s.recent_writes > 0 : null;
  const botOk = paper.data ? paper.data.daemon.running : null;

  const pills: Pill[] = [
    {
      key: "api", label: "API", ok: apiOk,
      detail: apiOk ? ":8040" : "unreachable — run: mm start",
    },
    {
      key: "rec", label: "Recorder", ok: recOk,
      detail: s ? (recOk ? `${s.recent_writes} live bucket${s.recent_writes === 1 ? "" : "s"}` : "not recording") : "…",
    },
    {
      key: "bot", label: "Paper bot", ok: botOk,
      detail: paper.data
        ? botOk
          ? `up ${((paper.data.daemon.uptime_s ?? 0) / 3600).toFixed(1)}h · $${paper.data.wallet?.balance?.toFixed(0) ?? "?"}`
          : "stopped"
        : "…",
    },
  ];

  // --- desktop notifications on healthy -> down transitions ---
  const [alerts, setAlerts] = useState(() => localStorage.getItem("healthAlerts") === "on");
  const prev = useRef<Record<string, boolean | null>>({});
  useEffect(() => {
    for (const p of pills) {
      const was = prev.current[p.key];
      if (alerts && was === true && p.ok === false && Notification.permission === "granted") {
        new Notification(`${p.label} is DOWN`, { body: p.detail });
      }
      prev.current[p.key] = p.ok;
    }
  });

  const toggleAlerts = async () => {
    if (!alerts && Notification.permission !== "granted") {
      const perm = await Notification.requestPermission();
      if (perm !== "granted") return;
    }
    const next = !alerts;
    setAlerts(next);
    localStorage.setItem("healthAlerts", next ? "on" : "off");
  };

  return (
    <div className={styles.strip}>
      {pills.map((p) => (
        <span key={p.key} className={styles.pill} title={p.detail}>
          <span className={`${styles.dot} ${p.ok === null ? styles.unknown : p.ok ? styles.up : styles.down}`} />
          <span className={styles.label}>{p.label}</span>
          <span className={styles.detail}>{p.detail}</span>
        </span>
      ))}
      <button
        className={`${styles.bell} ${alerts ? styles.bellOn : ""}`}
        onClick={toggleAlerts}
        title={alerts ? "Desktop alerts ON — click to disable" : "Notify me when something dies"}
      >
        {alerts ? "alerts on" : "alerts off"}
      </button>
    </div>
  );
}
