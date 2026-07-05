r"""
FastAPI backend for the Polymarket MM project.

This is a THIN layer over the existing src/ modules — it does no trading logic of
its own, it just exposes the functions the CLI and Streamlit app already use as
HTTP/WebSocket endpoints. That makes it the foundation for a future custom
frontend (e.g. React) without touching the engine.

Run it:
    .\.venv\Scripts\python.exe -m uvicorn api.main:app --reload
    #  or:  .\.venv\Scripts\python.exe scripts\run_api.py
Interactive docs (try every endpoint in the browser): http://localhost:8000/docs

Read-only & simulation-only: nothing here places an order or exposes the key.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Make the project root importable whether run via uvicorn or the launcher.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import RedirectResponse  # noqa: E402

from api.models import BacktestRequest, RecordRequest, SweepRequest  # noqa: E402
from app.live import LiveSession, RecorderSession  # noqa: E402  (reused; src + threading only)
from config.settings import SETTINGS, Mode  # noqa: E402
from src import gamma, history, market_data, runner  # noqa: E402
from src.analytics import compute_metrics, load_events  # noqa: E402
from src.connection import build_public_client  # noqa: E402
from src.gamma import Market  # noqa: E402
from src.orderbook import LocalOrderBook  # noqa: E402
from src.strategy import StrategyConfig  # noqa: E402

from api.hd import router as hd_router  # noqa: E402  (HD record/resolve/replay endpoints)
from api.paper import router as paper_router  # noqa: E402  (demo-wallet paper trading)

app = FastAPI(title="Polymarket MM API", version="1.0")
app.include_router(hd_router)
app.include_router(paper_router)

# Allow a local frontend dev server (React/Vite/Next on localhost) to call us.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://localhost:\d+",
    allow_methods=["*"],
    allow_headers=["*"],
)

# A single shared public (unauthenticated) CLOB client for market-data reads.
_client = None


def client():
    global _client
    if _client is None:
        _client = build_public_client()
    return _client


# --- serialisers ----------------------------------------------------------

def market_to_dict(m: Market) -> dict:
    return {
        "question": m.question,
        "slug": m.slug,
        "condition_id": m.condition_id,
        "tokens": m.tokens,
        "tradeable": m.tradeable,
        "active": m.active,
        "closed": m.closed,
        "volume": m.volume,
        "liquidity": m.liquidity,
        "one_day_price_change": m.one_day_price_change,
        "one_hour_price_change": m.one_hour_price_change,
        "end_date": m.end_date,
        "outcome_prices": m.outcome_prices,
    }


def book_to_dict(b: LocalOrderBook) -> dict:
    return {
        "token_id": b.token_id,
        "best_bid": b.best_bid,
        "best_ask": b.best_ask,
        "mid": b.midpoint,
        "spread": b.spread,
        "tick_size": b.tick_size,
        "bids": b.bid_levels(20),
        "asks": b.ask_levels(20),
    }


# --- meta -----------------------------------------------------------------

@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    # Visiting the base URL is friendlier than a 404 — send people to the docs.
    return RedirectResponse(url="/docs")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "mode": SETTINGS.mode.value}


@app.get("/config")
def config() -> dict:
    return SETTINGS.redacted()


# --- market discovery -----------------------------------------------------

@app.get("/markets/search")
def markets_search(q: str, limit: int = 20, tradeable_only: bool = True) -> list[dict]:
    return [market_to_dict(m) for m in gamma.search_markets(q, limit=limit, tradeable_only=tradeable_only)]


@app.get("/markets/top")
def markets_top(limit: int = 24, tradeable_only: bool = True) -> list[dict]:
    return [market_to_dict(m) for m in gamma.top_markets(limit, tradeable_only)]


@app.get("/markets/crypto-updown")
def markets_crypto_updown(limit: int = 24) -> list[dict]:
    return [market_to_dict(m) for m in gamma.crypto_updown(limit)]


@app.get("/markets/{condition_id}")
def market_detail(condition_id: str) -> dict:
    m = gamma.get_market(condition_id)
    if m is None:
        raise HTTPException(status_code=404, detail="market not found")
    return market_to_dict(m)


# --- market data ----------------------------------------------------------

@app.get("/book/{token_id}")
def book(token_id: str) -> dict:
    return book_to_dict(market_data.fetch_order_book(client(), token_id))


@app.get("/stats/{token_id}")
def stats(token_id: str) -> dict:
    """Book-derived stats + Gamma market context — powers a market-overview bar."""
    raw = client().get_order_book(token_id)
    b = LocalOrderBook(token_id)
    b.apply_snapshot(raw if isinstance(raw, dict) else market_data._book_to_dict(raw))
    condition_id = raw.get("market") if isinstance(raw, dict) else None

    out: dict = {
        "token_id": token_id,
        "condition_id": condition_id,
        "best_bid": b.best_bid,
        "best_ask": b.best_ask,
        "mid": b.midpoint,
        "spread": b.spread,
        "tick_size": b.tick_size,
        "last_trade_price": b.last_trade_price,
    }
    if condition_id:
        m = gamma.get_market(condition_id)
        if m is not None:
            out.update({
                "question": m.question,
                "volume": m.volume,
                "liquidity": m.liquidity,
                "one_day_price_change": m.one_day_price_change,
                "one_hour_price_change": m.one_hour_price_change,
                "end_date": m.end_date,
                "tradeable": m.tradeable,
            })
    return out


@app.get("/history/{token_id}")
def price_history(token_id: str, interval: str = "1d", fidelity: int = 5) -> list[dict]:
    series = history.fetch_price_history(client(), token_id, interval, fidelity)
    return [{"t": t, "p": p} for t, p in series]


@app.get("/runs")
def runs(limit: int = 15) -> list[dict]:
    """Recent simulation/backtest runs (from logs/mm_*.jsonl), newest first, with
    a computed P&L summary — powers the Home dashboard's 'recent activity'."""
    d = PROJECT_ROOT / "logs"
    if not d.exists():
        return []
    files = sorted(d.glob("mm_*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    out = []
    for p in files:
        try:
            events = load_events(p)
            m = compute_metrics(events)
            start = next((e for e in events if e.get("type") == "run_start"), {})
            params = start.get("params", {}) or {}
            out.append({
                "file": p.name,
                "mtime": int(p.stat().st_mtime),
                "total_pnl": m.total_pnl,
                "fills": m.fills,
                "win_rate": m.win_rate,
                "source": params.get("source") or params.get("via") or "",
            })
        except Exception:  # noqa: BLE001 - skip unreadable/partial logs
            continue
    return out


@app.get("/recordings")
def recordings() -> list[dict]:
    d = PROJECT_ROOT / "data" / "recordings"
    if not d.exists():
        return []
    return [
        {"name": p.name, "size_kb": round(p.stat().st_size / 1024, 1)}
        for p in sorted(d.glob("*.jsonl"), reverse=True)
    ]


# --- backtest / sweep (run in a worker thread — these are sync `def`) ------

def _cfg(p) -> StrategyConfig:
    return StrategyConfig(spread=p.spread, size=p.size, inventory_skew=p.skew,
                          inventory_widen=p.widen, requote_threshold=p.requote)


@app.post("/backtest")
def backtest(req: BacktestRequest) -> dict:
    cfg = _cfg(req.params)
    try:
        if req.source == "history":
            if not req.token_id:
                raise ValueError("token_id is required for history backtests")
            res = runner.backtest_history(req.token_id, req.interval, req.fidelity, cfg)
        else:
            if not req.recording:
                raise ValueError("recording path is required for recording backtests")
            res = runner.backtest_recording(req.recording, cfg)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc))

    m = res.metrics
    return {
        "token_id": res.token_id,
        "source": res.source,
        "summary": m.summary_row(),
        "series": {
            "t": m.t, "total": m.total_series, "realized": m.realized_series,
            "unrealized": m.unrealized_series, "position": m.position_series, "mid": m.mid,
        },
    }


@app.post("/sweep")
def sweep(req: SweepRequest) -> list[dict]:
    src = ({"recording": req.recording} if req.source == "recording"
           else {"token_id": req.token_id, "interval": req.interval, "fidelity": req.fidelity})
    try:
        df = runner.run_sweep(spreads=req.spreads, sizes=req.sizes, skews=req.skews,
                              widen=req.widen, requote=req.requote, **src)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc))
    return df.to_dict(orient="records")


# --- account (read-only, authenticated) ----------------------------------

@app.get("/account")
def account() -> dict:
    """pUSD balance + open positions. Authenticated read; never moves funds."""
    if not SETTINGS.private_key:
        raise HTTPException(status_code=503, detail="PRIVATE_KEY not set in .env")
    if SETTINGS.mode == Mode.READONLY:
        raise HTTPException(status_code=503, detail="MODE=readonly disables balance reads")
    from src.account import get_positions, get_pusd_balance
    from src.connection import build_clob_client
    try:
        client_l2 = build_clob_client()
        bal = get_pusd_balance(client_l2)
        positions = get_positions(SETTINGS.funder_address) if SETTINGS.funder_address else []
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"account read failed: {exc}")
    cols = ["outcome", "size", "avgPrice", "curPrice", "currentValue", "title"]
    return {
        "balance_pusd": bal["balance_pusd"],
        "allowance_pusd": bal["allowance_pusd"],
        "positions": [{c: p.get(c) for c in cols} for p in positions],
    }


# --- recording control (one active recorder, server-side) -----------------

_recorder: RecorderSession | None = None


@app.post("/recordings/start")
def recording_start(req: RecordRequest) -> dict:
    global _recorder
    if _recorder is not None and _recorder.running:
        raise HTTPException(status_code=409, detail="a recording is already running")
    _recorder = RecorderSession(req.token_id, req.duration)
    _recorder.start()
    return {"running": True, "path": _recorder.path.name}


@app.post("/recordings/stop")
def recording_stop() -> dict:
    if _recorder is None:
        raise HTTPException(status_code=409, detail="no recording to stop")
    _recorder.stop()
    return {"running": False, "count": _recorder.count, "path": _recorder.path.name}


@app.get("/recordings/status")
def recording_status() -> dict:
    if _recorder is None:
        return {"running": False, "count": 0, "path": None}
    return {"running": _recorder.running, "count": _recorder.count, "path": _recorder.path.name}


# --- live book over WebSocket --------------------------------------------

@app.websocket("/ws/book/{token_id}")
async def ws_book(websocket: WebSocket, token_id: str) -> None:
    """Stream a 1 Hz order-book snapshot to the client until it disconnects.

    A LiveSession runs the WS subscription on a background thread; we just poll
    its thread-safe snapshot once a second and push it down to the browser.
    """
    await websocket.accept()
    session = LiveSession(token_id, depth=12)
    session.start()
    try:
        while True:
            await websocket.send_json(session.snapshot())
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001 - client gone / send failed
        pass
    finally:
        session.stop()


def _sim_payload(session: LiveSession) -> dict:
    """Compact frame for the sim stream: summary + recent fills + P&L series."""
    es = session.engine_snapshot()
    if not es or es["summary"] is None:
        return {"waiting": True, "running": session.running}
    m = compute_metrics(es["events"])
    fills = [e for e in es["events"] if e.get("type") == "fill"][-20:]
    return {
        "waiting": False,
        "running": session.running,
        "summary": es["summary"],
        "fills": fills,
        "series": {
            "t": m.t, "total": m.total_series, "position": m.position_series,
            "realized": m.realized_series, "unrealized": m.unrealized_series, "mid": m.mid,
        },
    }


@app.websocket("/ws/sim/{token_id}")
async def ws_sim(
    websocket: WebSocket,
    token_id: str,
    spread: float = 0.02,
    size: float = 100.0,
    skew: float = 0.005,
    widen: float = 0.005,
    requote: float = 0.002,
    duration: float = 0.0,
) -> None:
    """Run the market-making simulation against the live book and stream results.

    Uses the same LiveSession + SimEngine the Streamlit Strategy Lab uses, so the
    numbers match. `duration` 0 = run until the client disconnects.
    """
    await websocket.accept()
    cfg = StrategyConfig(spread=spread, size=size, inventory_skew=skew,
                         inventory_widen=widen, requote_threshold=requote)
    session = LiveSession(token_id, cfg=cfg, to_file=True)
    session.start(duration=duration or None)
    try:
        while True:
            await websocket.send_json(_sim_payload(session))
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        pass
    finally:
        session.stop()
