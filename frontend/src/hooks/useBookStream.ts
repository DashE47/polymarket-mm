// Subscribe to the live order-book WebSocket (/ws/book/{token}) and expose the
// latest frame. Reconnects on token change; closes on unmount.

import { useEffect, useRef, useState } from "react";
import { bookWsUrl } from "../api/client";
import type { BookFrame } from "../api/types";

export function useBookStream(tokenId: string | null) {
  const [frame, setFrame] = useState<BookFrame | null>(null);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!tokenId) return;
    setFrame(null);
    const ws = new WebSocket(bookWsUrl(tokenId));
    wsRef.current = ws;
    ws.onopen = () => setConnected(true);
    ws.onmessage = (e) => {
      try {
        setFrame(JSON.parse(e.data) as BookFrame);
      } catch {
        /* ignore malformed frame */
      }
    };
    ws.onclose = () => setConnected(false);
    ws.onerror = () => setConnected(false);
    return () => ws.close();
  }, [tokenId]);

  return { frame, connected };
}
