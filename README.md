# Polymarket Market-Making & Backtesting Environment

A learning-oriented, safety-first toolkit for quoting and backtesting on
**Polymarket CLOB V2** (live since 2026-04-28; collateral is **pUSD**).

> Built in phases. **Phase 1 = project setup + an authenticated connection.**
> No order placement exists yet — Phase 1 only reads data.

## What Phase 1 gives you

- A clean project layout with secrets isolated in `.env`.
- A configuration layer with a global **MODE** (`readonly` / `simulation` /
  `live`) defaulting to `simulation`, plus risk-limit settings and a file-based
  **kill switch** — wired in now so safety is never bolted on later.
- A connection module that builds the **V2** `ClobClient`, performs
  **L1 → L2** authentication, and verifies connectivity.
- Two scripts:
  - `scripts/check_connection.py` — prove auth + connectivity work.
  - `scripts/show_account.py` — print your **pUSD balance** and **open positions**.

## Setup (Windows / PowerShell)

```powershell
cd "D:\Claude Code Projects\polymarket-mm"

# 1. Create and activate a virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. Install dependencies
pip install -r requirements.txt

# 3. Create your .env from the template and fill it in
Copy-Item .env.example .env
notepad .env   # add PRIVATE_KEY and FUNDER_ADDRESS

# 4. Verify the connection (no orders, no money moved)
python scripts/check_connection.py

# 5. See your balance and positions
python scripts/show_account.py
```

> macOS/Linux: use `source .venv/bin/activate` and `cp .env.example .env`.

## The two APIs (and why we use both)

| API   | Host                              | Auth        | Used for                         |
|-------|-----------------------------------|-------------|----------------------------------|
| CLOB  | `https://clob.polymarket.com`     | L1 → L2     | balance, and (later) trading     |
| Gamma | `https://gamma-api.polymarket.com`| none        | market discovery (later phases)  |
| Data  | `https://data-api.polymarket.com` | none        | open positions                   |

## Authentication, briefly

1. **L1** — sign a message with your `PRIVATE_KEY` to prove wallet ownership.
2. The SDK uses that to **create or derive API credentials**
   (`api_key` / `secret` / `passphrase`).
3. **L2** — those credentials HMAC-sign every authenticated request.

Polymarket holds your funds in a **proxy wallet** (a Gnosis Safe), not your raw
key address. That proxy is your **`FUNDER_ADDRESS`**, and `SIGNATURE_TYPE` tells
the SDK how your account is set up (see `.env.example`).

## Safety model

- **MODE** gates behaviour. `live` additionally requires `CONFIRM_LIVE=YES`.
- **Kill switch**: create a file named `KILL` in this folder to halt quoting
  (`New-Item KILL` / `touch KILL`); delete it to resume.
- **Risk limits**: `MAX_POSITION_USD` and `MAX_DAILY_LOSS_USD` (enforced by the
  market maker in later phases; defined now in `config/settings.py`).

## Phase 2 — market discovery + live data

All public and read-only (no key needed).

```powershell
# 1. Search markets by keyword -> get conditionId + Yes/No token ids
.\.venv\Scripts\python.exe scripts\search_markets.py "bitcoin"
.\.venv\Scripts\python.exe scripts\search_markets.py "world cup" --all --limit 30

# 2. Watch one token's order book live (best bid/ask, mid, spread, depth ladder)
.\.venv\Scripts\python.exe scripts\live_view.py <token_id>
.\.venv\Scripts\python.exe scripts\live_view.py 0x<conditionId> --outcome No --depth 8
```

- **Discovery** uses Gamma `/public-search` (the website's search box; `/markets`
  has no text search). `clobTokenIds`/`outcomes` arrive as JSON *strings* and are
  decoded for you; `tokens["Yes"]` / `tokens["No"]` give the token ids.
- **Order book** comes from the CLOB REST API (`get_order_book`) for snapshots and
  the **V2 WebSocket** (`wss://ws-subscriptions-clob.polymarket.com/ws/market`) for
  live `book` + `price_change` updates. Both feed one `LocalOrderBook`, so the
  midpoint/spread math is identical whether pulled or streamed (verified to match
  the CLOB's own `get_midpoint`/`get_spread`).
- The live view seeds from a REST snapshot for an instant first paint, then
  streams deltas and re-renders in place (~15 fps). Ctrl-C to quit.

## Phase 3 — market-making strategy (simulation)

Quotes a two-sided market around the book midpoint, skews by inventory,
re-quotes as the book moves, enforces the risk limits, and **simulates fills
against the live order book**. It never sends a real order.

```powershell
# pick a token from search_markets.py, then:
.\.venv\Scripts\python.exe scripts\run_market_maker.py <token_id> `
    --spread 0.01 --size 100 --skew 0.02 --widen 0.01 --requote 0.002 --duration 120
```

- **Fair value** = order-book midpoint. **Quotes** = reservation ± half-spread,
  where `reservation = mid - skew * inventory_ratio` (long → quotes shift down to
  offload) and the spread widens with inventory.
- **Re-quote** only when a side moves ≥ `--requote` (avoids order churn).
- **Risk**: halts on the `KILL` file, on the daily-loss cap (`MAX_DAILY_LOSS_USD`),
  and stops quoting the side that would breach `MAX_POSITION_USD`.
- **Fill model** (read `src/sim_engine.py`): a resting bid fills when the best
  ask trades down to it (and vice-versa). Optimistic v1 — assumes full size, no
  queue, no latency. Phase 4 reuses the *same* model so backtest and live-sim
  agree.
- Every quote/fill/halt is printed and appended to `logs/mm_*.jsonl`.

Tip: to actually *see* fills, use a liquid, moving market and a spread near or
inside the market's own spread; very wide quotes rarely get hit.

## Phase 4 — backtest + replay engine

Feed historical data through the **same `SimEngine`** used live, so a backtest is
a faithful re-run of the strategy — only faster and deterministic. Two sources:

```powershell
# A) Record a live feed, then replay it (faithful full-book fill model)
.\.venv\Scripts\python.exe scripts\record_market.py <token_id> --duration 300
.\.venv\Scripts\python.exe scripts\backtest.py --recording data\recordings\rec_....jsonl --spread 0.004 --size 100

# B) Backtest on CLOB price history right now (no recording needed; coarser)
.\.venv\Scripts\python.exe scripts\backtest.py 0x<conditionId> --outcome Yes --history `
    --interval 1d --fidelity 5 --spread 0.01 --size 100 --status-every 60
```

- **Strategy flags are identical to `run_market_maker.py`**, so a setting moves
  straight from live-sim to backtest. Risk limits still come from `.env`.
- **Recording replay** reconstructs the real order book tick-by-tick (book
  snapshots + `price_change` deltas) → realistic fill model (bid fills when best
  ask trades down to it).
- **History replay** uses `get_prices_history` (a price series). It synthesises a
  1-level book per point, so the fill model degrades to **mid-crossing** (bid
  fills when the price falls to it) and spread is unknown. Coarser, but needs no
  pre-recorded data. See the top of `src/history.py` for the trade-offs.
- Each run writes a `logs/mm_*.jsonl` (Phase 5 analytics reads these).

> Note: a market maker typically *loses* in a trending market (you keep getting
> filled on the losing side). That's a real result, not a bug — it's what the
> backtester is for. Tune spread/size/skew and compare.

## Phase 5 — analytics + parameter sweep

Turn run logs into a scorecard and charts, and sweep parameters to find good
settings instead of guessing one live run at a time.

```powershell
# Scorecard + chart (PnL / inventory / price) for a run; defaults to latest log
.\.venv\Scripts\python.exe scripts\analyze_run.py
.\.venv\Scripts\python.exe scripts\analyze_run.py logs\mm_....jsonl

# Sweep spread x size x skew over the SAME data; ranked table + CSV + chart
.\.venv\Scripts\python.exe scripts\sweep.py --recording data\recordings\rec_....jsonl `
    --spreads 0.004,0.01,0.02,0.04 --sizes 50,100 --skews 0,0.005,0.02
.\.venv\Scripts\python.exe scripts\sweep.py 0x<conditionId> --outcome Up --history `
    --interval 6h --fidelity 1 --spreads 0.01,0.02,0.04 --skews 0,0.005
```

- **Metrics**: total / realized / unrealized PnL, fills & fills-per-minute,
  win rate, avg spread captured per closing trade, max |inventory|, max drawdown,
  Sharpe (per-step, not annualised), all on **market time** (so a backtest that
  replays in 1s still reports the real market duration).
- Charts and the sweep CSV are written to `reports/` (git-ignored).
- **Reading results**: on a *trending* market the best any market maker can do is
  *lose less* (wider spread / more skew → fewer fills, smaller position). To find
  *profitable* settings, sweep over *ranging* (choppy, mean-reverting) data — that's
  where capturing the spread beats adverse selection.

## Phase 6 — Web UI (no more command line)

A local **Streamlit** app wraps everything above so you can search markets, watch
order books, run sims/backtests, and sweep parameters from the browser.

```powershell
.\.venv\Scripts\python.exe -m streamlit run app/main.py
#  or:  .\.venv\Scripts\python.exe scripts\run_app.py
```
Opens http://localhost:8501. Pages:

- **Home & Safety** — redacted config, risk limits, a kill-switch toggle, and an
  on-demand read-only pUSD balance + positions panel.
- **Market Explorer** — keyword search → pick a market + outcome (shared with
  every other page; no more pasting token ids).
- **Live Order Book** — streaming best bid/ask/mid/spread, depth ladder, mid chart.
- **Strategy Lab** — run the strategy in simulation against the live book
  (fixed-duration or continuous), live P&L / inventory / fills.
- **Backtest & Analytics** — run history/recordings or load a saved log; full
  scorecard + interactive charts.
- **Parameter Sweep** — grid over spread/size/skew; ranked table + chart + CSV.
- **Recorder** — capture a live feed to `data/recordings/` for backtests.
- **Live Trading** — intentionally **disabled** placeholder (simulation-only app).

The UI reuses the same `src/` modules and `src/runner.py` as the CLI, so results
match. It is **simulation-only** and never displays the private key.

## Phase 7 — API backend (foundation for a custom UI)

A **FastAPI** layer exposes the `src/` modules as a REST + WebSocket API — the
foundation for a future fully-custom frontend (e.g. React) while keeping all the
Python engine intact. The Streamlit app still works unchanged.

```powershell
.\.venv\Scripts\python.exe scripts\run_api.py
```
This auto-picks a bindable port (default 8040) and prints the URL. It prefers the
launcher because plain `uvicorn api.main:app` defaults to port **8000**, which on
Windows is often **reserved** (Hyper-V/WSL/Docker) and fails with
`WinError 10013`. If you run uvicorn directly, pass a port:
`.\.venv\Scripts\python.exe -m uvicorn api.main:app --port 8040`.

Open the printed URL — **interactive docs at `/docs`** let you try every endpoint
in the browser. Endpoints:

| Method | Path | Purpose |
|---|---|---|
| GET | `/health`, `/config` | status + redacted settings |
| GET | `/markets/search?q=` | keyword search |
| GET | `/markets/{condition_id}` | market detail |
| GET | `/book/{token_id}` | order-book snapshot (depth, bid/ask/mid/spread) |
| GET | `/stats/{token_id}` | book + Gamma context (volume, liquidity, change, end) |
| GET | `/history/{token_id}` | price history series |
| GET | `/recordings` | list recordings |
| POST | `/backtest` | run a backtest → summary + series |
| POST | `/sweep` | run a parameter sweep → ranked rows |
| WS | `/ws/book/{token_id}` | live 1 Hz order-book snapshots |

It's a thin wrapper — every endpoint calls the same `src/` functions the CLI and
Streamlit app use (`runner`, `gamma`, `market_data`, `history`). Read-only,
simulation-only, never exposes the key. CORS is open to `localhost:*` for a local
frontend dev server.

## Phase 8 — Custom web app (React frontend)

A polished single-page app in `frontend/` (Vite + React + TypeScript, **hand-written
CSS** design system — no UI framework) that talks to the FastAPI backend. Runs
locally; the Streamlit app and CLI still work unchanged.

**Run it (two terminals, from the project root):**
```powershell
# 1) backend  (API on http://localhost:8040)
.\.venv\Scripts\python.exe scripts\run_api.py

# 2) frontend (UI on http://localhost:5173)
cd frontend
npm install     # first time only
npm run dev
```
Then open **http://localhost:5173**. Vite proxies `/api` and `/ws` to the backend,
so the browser uses one origin (no CORS fuss).

> Gotchas (Windows / Node 18): the backend must be on **8040** (the Vite proxy
> targets `127.0.0.1:8040` — `127.0.0.1`, not `localhost`, to avoid a Node-18 IPv6
> miss). `run_api.py` picks 8040 by default. Requires **Node 18+**; we pin Vite 5.

**Pages:** Home (cockpit: watchlist + KPIs + recent runs) · Market Explorer
(categories, trending, live **↕ Up/Down** crypto buckets, ★ watchlist) · Live Order
Book (animated, depth ladder) · Strategy Lab (live sim, streaming equity curve) ·
Backtest & Analytics (charts + "what happened?" explainer) · Parameter Sweep (P&L
heatmap) · Recorder · Learn (interactive quote simulator + glossary + hover tips) ·
disabled Live Trading. Plus a light/dark theme, toasts, skeletons, and a ⌘K palette.

**Build / type-check:** `cd frontend && npm run build` (runs `tsc` + Vite).

## Layout

```
polymarket-mm/
├─ config/settings.py   # loads .env, validates, exposes SETTINGS
├─ src/
│  ├─ connection.py     # build V2 client (auth + public), L1->L2, connectivity
│  ├─ account.py        # pUSD balance (CLOB) + positions (Data API)
│  ├─ gamma.py          # Gamma market discovery / keyword search (Phase 2)
│  ├─ market_data.py    # REST order book, midpoint, spread (Phase 2)
│  ├─ orderbook.py      # LocalOrderBook + best bid/ask/mid/spread math (Phase 2)
│  ├─ ws_client.py      # live WebSocket book subscriber (Phase 2)
│  ├─ strategy.py       # pure quoting logic: spread + inventory skew (Phase 3)
│  ├─ inventory.py      # position + avg-cost realized/unrealized P&L (Phase 3)
│  ├─ sim_engine.py     # quoting loop: fills, risk, re-quote (Phase 3)
│  ├─ sim_logger.py     # console + JSONL run logging (Phase 3)
│  ├─ recorder.py       # record live WS events to disk (Phase 4)
│  ├─ history.py        # CLOB price-history fetch + synthetic book (Phase 4)
│  ├─ replay.py         # drive SimEngine from recordings / history (Phase 4)
│  ├─ analytics.py      # metrics + time series from a run log (Phase 5)
│  ├─ charts.py         # save PnL / inventory / sweep charts (Phase 5)
│  ├─ runner.py         # shared backtest/sweep orchestration (CLI + UI) (Phase 6)
│  ├─ http_utils.py     # GET with exponential-backoff retry for public APIs
│  └─ safety.py         # kill switch + risk-limit checks
├─ app/                 # Streamlit web UI (Phase 6)
│  ├─ main.py           # navigation + sidebar entry point
│  ├─ state.py          # session-state helpers + sidebar
│  ├─ live.py           # background RecorderSession / LiveSession (threads)
│  ├─ charts.py         # Plotly figure builders (interactive)
│  └─ views/            # one module per page (home, explorer, order_book, …)
├─ api/                 # FastAPI backend (Phase 7)
│  ├─ main.py           # REST + WebSocket endpoints over src/
│  └─ models.py         # Pydantic request schemas
├─ frontend/            # React + TS web app (Phase 8); npm run dev
│  └─ src/              # styles/ (design tokens), api/, state/, hooks/,
│                       #   components/, pages/ — hand-written CSS, no UI framework
├─ scripts/
│  ├─ check_connection.py
│  ├─ show_account.py
│  ├─ diagnose_signature_type.py   # find the right SIGNATURE_TYPE for your wallet
│  ├─ search_markets.py            # keyword search -> token ids (Phase 2)
│  ├─ live_view.py                 # live order-book view (Phase 2)
│  ├─ run_market_maker.py          # simulated market maker (Phase 3)
│  ├─ record_market.py             # record live data for backtests (Phase 4)
│  ├─ backtest.py                  # replay recordings / history (Phase 4)
│  ├─ analyze_run.py               # scorecard + charts for a run (Phase 5)
│  ├─ sweep.py                     # parameter sweep + comparison (Phase 5)
│  ├─ run_app.py                   # launch the Streamlit UI (Phase 6)
│  └─ run_api.py                   # launch the FastAPI backend (Phase 7)
├─ data/  logs/         # git-ignored caches/logs
├─ .env.example         # template; copy to .env (git-ignored)
└─ requirements.txt
```

## Security notes

- `.env`, `logs/`, `data/`, and `KILL` are git-ignored. **Never commit `.env`.**
- The config printer redacts the funder address and never prints the key.
- A clean, dedicated wallet holding only the funds you intend to trade is
  strongly advised.
