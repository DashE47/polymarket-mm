import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The FastAPI backend (scripts/run_api.py) defaults to port 8040. We proxy
// /api and /ws through Vite's dev server so the browser talks to one origin —
// no CORS/websocket-origin friction in development. Change here if you run the
// API on a different port.
// NOTE: use 127.0.0.1, NOT localhost — on Node 18 / Windows "localhost" can
// resolve to IPv6 (::1) while uvicorn binds IPv4, causing ECONNREFUSED ::1.
const API = "http://127.0.0.1:8040";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // REST: strip the /api prefix before forwarding (/api/health -> /health).
      "/api": { target: API, changeOrigin: true, rewrite: (p) => p.replace(/^\/api/, "") },
      // WebSockets: forward as-is with ws upgrade enabled.
      "/ws": { target: API, ws: true, changeOrigin: true },
    },
  },
});
