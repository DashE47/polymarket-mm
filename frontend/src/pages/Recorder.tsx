// Recorder: capture the selected market's live feed to data/recordings/ (via the
// server-side recorder), with a live event counter, then list saved recordings.

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { useSelection } from "../state/SelectionContext";
import { useToast } from "../components/Toast";

export default function Recorder() {
  const { tokenId, market, outcome } = useSelection();
  const toast = useToast();
  const [duration, setDuration] = useState(300);
  const [busy, setBusy] = useState(false);

  const status = useQuery({ queryKey: ["recstatus"], queryFn: api.recordingStatus, refetchInterval: 1500 });
  const recs = useQuery({ queryKey: ["recordings"], queryFn: api.recordings });
  const running = status.data?.running;

  const start = async () => {
    if (!tokenId) return;
    setBusy(true);
    try { await api.startRecording(tokenId, duration); toast("Recording started", "success"); status.refetch(); }
    catch (e) { toast(e instanceof Error ? e.message : String(e), "error"); }
    finally { setBusy(false); }
  };
  const stop = async () => {
    setBusy(true);
    try { await api.stopRecording(); toast("Recording stopped", "success"); status.refetch(); recs.refetch(); }
    catch (e) { toast(e instanceof Error ? e.message : String(e), "error"); }
    finally { setBusy(false); }
  };

  return (
    <div className="col">
      <h1>Recorder</h1>
      <p className="muted small">Capture a live feed to replay later in Backtest &amp; Analytics or the Sweep (faithful full-book fills).</p>

      <div className="card col">
        {tokenId
          ? <span className="small muted">{market?.question} [{outcome}]</span>
          : <span className="muted">Select a market in the Market Explorer to record it.</span>}
        <div className="row center wrap">
          <div><label>duration (s)</label><input type="number" value={duration} min={10} max={3600} step={10} style={{ width: 120 }} disabled={running} onChange={(e) => setDuration(+e.target.value)} /></div>
          <button className="btn btn-primary" disabled={!tokenId || running || busy} onClick={start}>⏺ Start recording</button>
          <button className="btn btn-danger" disabled={!running || busy} onClick={stop}>⏹ Stop</button>
        </div>
        {status.data && (
          <div className="small">
            {running
              ? <span className="pos">● recording — {status.data.count} events → {status.data.path}</span>
              : <span className="muted">idle{status.data.path ? ` — last: ${status.data.path} (${status.data.count} events)` : ""}</span>}
          </div>
        )}
      </div>

      <div className="card">
        <h2>Recordings</h2>
        {recs.data && recs.data.length > 0 ? (
          <table>
            <thead><tr><th>file</th><th>size</th></tr></thead>
            <tbody>{recs.data.map((r) => <tr key={r.name}><td className="mono small">{r.name}</td><td>{r.size_kb} KB</td></tr>)}</tbody>
          </table>
        ) : <p className="muted">No recordings yet.</p>}
      </div>
    </div>
  );
}
