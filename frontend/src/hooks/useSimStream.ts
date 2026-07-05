// Stream the live market-making simulation over /ws/sim. Opens when `running`
// becomes true (with the params captured at that moment) and closes on stop /
// unmount / server-side auto-stop (calls onEnd so the page can reset).

import { useEffect, useRef, useState } from "react";
import { simWsUrl } from "../api/client";
import type { SimFrame, StrategyParams } from "../api/types";

export function useSimStream(
  tokenId: string | null,
  params: StrategyParams,
  duration: number,
  running: boolean,
  onEnd?: () => void,
) {
  const [frame, setFrame] = useState<SimFrame | null>(null);
  const [connected, setConnected] = useState(false);
  const paramsRef = useRef(params); paramsRef.current = params;
  const durRef = useRef(duration); durRef.current = duration;
  const endRef = useRef(onEnd); endRef.current = onEnd;

  useEffect(() => {
    if (!running || !tokenId) return;
    setFrame(null);
    const ws = new WebSocket(simWsUrl(tokenId, paramsRef.current, durRef.current));
    ws.onopen = () => setConnected(true);
    ws.onmessage = (e) => { try { setFrame(JSON.parse(e.data) as SimFrame); } catch { /* ignore */ } };
    ws.onclose = () => { setConnected(false); endRef.current?.(); };
    ws.onerror = () => setConnected(false);
    return () => ws.close();
  }, [running, tokenId]);

  return { frame, connected };
}
