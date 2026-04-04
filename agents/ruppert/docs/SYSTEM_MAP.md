# Ruppert System Map
_Last updated: 2026-04-03 | v2.1 | All P0 + P1 sprints applied; live env + autoresearch archived_

---

## Changelog

### v2.1 — 2026-04-03
- Removed live environment section (environments/live/ archived — will be rebuilt from scratch)
- Removed autoresearch section (archived — will be replaced with new backtest engine)

### v2.0 — 2026-04-03
- Applied 40+ corrections from P1 domain audits (DS, Trader, Strategist) verified by QA
- Marked all resolved P1 known issues as ✅ RESOLVED
- Updated: settlement formulas, optimizer paths, WS backoff, S5 Polymarket, daily module architecture, cap lock, exit record schema, dashboard status

### v1.4 — 2026-04-03
- QA corrections: ISSUE-E01 and ISSUE-I01 marked Resolved with commit references

### v1.3 — 2026-04-03
- Trader domain updated for Sprints 1-5

### v1.2 — 2026-04-03
- DS domain updated for Sprints 1-5

### v1.1 — 2026-04-02
- 10-audit pass: 12 factual errors fixed, 12 gaps filled

### v1.0 — 2026-04-02
- Initial assembly from 6 research agents

---

## 0. System Overview

### Description

Ruppert is an automated prediction-market trading bot targeting Kalshi contracts across crypto, weather, economics, and geopolitical markets. It operates in a **demo environment** (simulated orders, real market data) and is structured as a multi-module pipeline: three entry modules generate directional signals from OKX, Kraken, Binance, Coinbase, Kalshi, and Polymarket feeds; a strategy layer applies capital allocation gates (Kelly sizing, edge/confidence thresholds, exposure caps); a real-time WebSocket feed monitors and executes exits via stop-loss and gain thresholds; a batch settlement checker catches any positions the WS path misses; and an analytics pipeline joins outcomes to scored predictions for calibration and optimizer review. A FastAPI dashboard on port 8765 and a CEO daily brief (Telegram + markdown) provide David with live P&L visibility. All persistent state lives in `environments/demo/logs/`; Windows Task Scheduler drives the scheduled scan cycles.

---

### High-Level Architecture

```
External Data Sources
─────────────────────────────────────────────────────────────────────
 OKX (trades, books, candles, OI, funding) │ Kalshi WebSocket + REST
 Kraken (spot prices)                       │ Polymarket (consensus)
 Binance Futures (funding)                  │ Coinbase (spot cross-check)
 OpenMeteo/NWS (weather)                   │ TheNewsAPI (geo signals)
─────────────────────────────────────────────────────────────────────
                              │
          ┌───────────────────┼──────────────────────┐
          ▼                   ▼                      ▼
  crypto_15m.py        crypto_band_daily.py  crypto_threshold_daily.py
  (15m direction)      (daily band/range)    (daily above/below)
  OKX microstructure   log-normal model      5-signal composite
  4 z-scored signals   scipy band_prob()     S1-S5 (momentum,
  Half-Kelly sizing    strategy.py gate      funding, ATR, OI,
                       strategy sizes        Polymarket)
          │                   │                      │  bypasses strategy.py
          └───────────────────▼──────────────────────┘
                        strategy.py
                  (edge gate, confidence gate,
                   exposure caps, Kelly sizing)
                              │
                        Trader.execute_opportunity()
                              │
              ┌───────────────┼──────────────────┐
              ▼               ▼                  ▼
         KalshiClient    position_tracker    log_trade()
         place_order()   add_position()     trades_YYYY-MM-DD.jsonl
                              │
         ┌────────────────────┼──────────────────────┐
         ▼                    ▼                      ▼
    ws_feed.py         settlement_checker.py   post_trade_monitor.py
  (WS exit engine)     (batch settlement)      (position monitor)
  stop-loss tiers      catches WS misses       every 30 min
  gain thresholds      3× daily (11PM, 8AM, 6AM)
  check_expired_pos()
         │                    │
         ▼                    ▼
  position_tracker       prediction_scorer.score_new_settlements()
  execute_exit()                    │
  settle records                    ▼
                          logs/scored_predictions.jsonl
                                    │
         ┌──────────────────────────┼───────────────────────┐
         ▼                          ▼                       ▼
   data_agent.py            optimizer.py           synthesizer.py
   (post-scan audit         (6-dim analysis,       (truth files:
    auto-fixes, alerts)      proposals)             pnl_cache.json
                                                    pending_alerts.json
                                                    state.json)
                                    │
                             capital.py (single truth for $)
                                    │
                      ┌─────────────┴──────────────┐
                      ▼                            ▼
               dashboard/api.py           brief_generator.py
               FastAPI port 8765          Daily Telegram brief
               (read-only)                20:00 PDT via scheduler
```

---

### Module Inventory Table

| Module Name | Type | Status | Description |
|---|---|---|---|
| `crypto_15m.py` | Entry | Active | 15-min Kalshi binary direction (BTC/ETH/XRP/DOGE/SOL). OKX microstructure, 4 z-scored signals (TFI/OBI/MACD/OI), Half-Kelly sizing. Data-collection thresholds in Phase 2. |
| `crypto_threshold_daily.py` | Entry | Active (Phase 1/2) | Daily above/below (BTC/ETH, SOL gated). 5-signal composite (momentum, funding, ATR, OI regime, Polymarket). Bypasses `should_enter()`. |
| `crypto_band_daily.py` | Entry | Active | Daily band/range (BTC/ETH/XRP/SOL/DOGE). Log-normal probability model. Uses `should_enter()` for sizing. Trade execution isolated in `_execute_band_trades()` with portalocker cap lock (ISSUE-053). |
| `crypto_long_horizon.py` | Entry | Active | Monthly/annual Kalshi markets (KXBTCMAXM, KXBTCMAXY, etc.). Fear & Greed regime + log-normal touch probability. $50 hard cap, 1/6 Kelly. Called in `full` mode from `ruppert_cycle.py`. |
| `strategy.py` | Strategy Gate | Active | Capital allocation brain. Edge/confidence/exposure/module-cap/reentry gates. Kelly sizing with tiered confidence fractions. Shim at `environments/demo/bot/strategy.py`. |
| `KalshiClient` | Execution | Active | All Kalshi API calls. Demo mode blocks orders silently. Live RSA/PSS auth. Enriches orderbooks. |
| `Trader` | Execution | Active | Converts strategy decisions into orders. Calls `KalshiClient.place_order()`, logs all outcomes (success + failure). |
| `logger.py` | Execution | Active | All trade logging (`build_trade_entry`, `log_trade`, `log_activity`). P&L aggregation. Module classification. Session-level dedup. |
| `ruppert_cycle.py` | Orchestration | Active | Cycle dispatcher. Modes: `full`, `check`, `crypto_only`, `crypto_1d`, `weather_only`, `econ_prescan`, `report`. Loads state, reconciles positions, dispatches scans. |
| `main.py` | Orchestration | Active | Per-module scan runners for weather, crypto band, crypto 1D, fed, geo. Interfaces `should_enter()` → `Trader`. |
| `ws_feed.py` | Exit | Active | Persistent WS process. Real-time price cache updates, stop-loss/gain exit evaluation, fallback poll loop for missed 15m windows. |
| `position_tracker.py` | Exit | Active | Core exit engine. Tracks open positions in memory + disk. Stop-loss tiers (15m and daily). Threshold exits. Settlement detection. |
| `settlement_checker.py` | Exit | Scheduled | Batch settlement resolver. 3× daily (11PM, 8AM, 6AM PDT). Catches positions missed by WS path. FIFO exit accounting. |
| `market_cache.py` | Shared | Active | In-memory price store. WS feed writes; all modules read. Staleness detection. Thread-safe. Persists to `price_cache.json`. |
| `circuit_breaker.py` | Risk | Active | Per-module consecutive loss tracking + global daily loss circuit breaker. State file `circuit_breaker_state.json`. Auto-resets on PDT day boundary. |
| `prediction_scorer.py` | Analytics | Active | Post-hoc join of buy records + settle records → `scored_predictions.jsonl`. Triggered by `settlement_checker`. |
| `brier_tracker.py` | Analytics | Active (legacy) | Push-model prediction calibration. Logs at entry, scores at resolution. Writes to same `scored_predictions.jsonl` as scorer with **incompatible schema**. |
| `optimizer.py` | Analytics | Active | 6-dimension trade analysis (win rate, confidence tiers, calibration, exit timing, cap utilization, sizing). **Fixed P1-3 (ISSUE-005):** reads from `logs/trades/` (corrected glob path). **Fixed P1-3 (ISSUE-046):** exit timing dimension now works (buy/exit join via `buy_index`; was using nonexistent `exit_timestamp` field). **Fixed P1-3 (ISSUE-041):** daily cap utilization no longer double-counts — filters to `action in ('buy','open')` before summing. |
| `data_agent.py` | Analytics | Active | Post-scan audit. Duplicate detection, missing fields, module mismatch, tracker drift. Auto-fixes. Runs after every scan cycle + once daily historical. |
| `synthesizer.py` | Analytics | Active | Writes truth files from event logs. `pnl_cache.json`, `pending_alerts.json`, `state.json`, `pending_optimizer_review.json`. |
| `capital.py` | Finance | Active | Single source of truth for capital, buying power, exposure, P&L. Reads deposits + `compute_closed_pnl_from_logs()`. |
| `env_config.py` | Infrastructure | Active | Environment isolation. Path dictionary for `demo`/`live`. Live gate requires two conditions. |
| `config.py` | Infrastructure | Active | All constants. 100+ entries covering sizing, risk, thresholds, circuit breakers, stop-losses, scheduling. |
| `mode.json` | Infrastructure | Active | Single-field runtime mode switch: `{"mode": "demo"}`. Requires restart to take effect. |
| `ws_feed_watchdog.py` | Infrastructure | Active (double-spawn issue) | Monitors ws_feed heartbeat. Restarts if stale >180s. Two copies exist (workspace root = active; demo/scripts = stale). |
| `dashboard/api.py` | Dashboard | Active | FastAPI on port 8765. Read-only DEMO mode. 30s in-process cache. 19 endpoints. |
| `brief_generator.py` | Reporting | Active | CEO daily brief. Telegram + markdown report. Two conflicting P&L methods in same output. |
| `daily_progress_report.py` | Reporting | Deprecated | Shim that delegates to `brief_generator.py`. |

> **Note (2026-04-03):** `environments/live/` has been archived and will be rebuilt from scratch before going live. `autoresearch.py` has been archived and will be replaced with a new backtest engine.

---

## 1. Entry Pipeline

_Source: `memory/agents/sysmap-section1-entry-pipeline.md`_

### 1.1 Architecture Overview

All three crypto entry modules follow the same general flow:

```
Data Sources (OKX API, Kraken, Binance, Coinbase, Kalshi, Polymarket)
    ↓
Signal Computation (module-specific: z-scores, log-normal, momentum)
    ↓
Local Risk Filters (module-internal: spread, staleness, drawdown, etc.)
    ↓
should_enter() in strategy.py (edge gate, confidence gate, sizing)
    ↓
Kalshi order placement (via KalshiClient or Trader)
    ↓
Trade logging (log_trade / log_activity) + Decision log (JSONL)
```

`environments/demo/bot/strategy.py` is a **shim file** — it re-exports everything from `agents/ruppert/strategist/strategy.py`. All real logic is in the latter file. Any import of `bot/strategy.py` is functionally identical to importing the real module.

---

### 1.2 Module: crypto_15m.py — 15-Minute Binary Direction

**Source file:** `agents/ruppert/trader/crypto_15m.py`

**Purpose:** Evaluates Kalshi 15-minute binary direction markets (KXBTC15M, KXETH15M, KXXRP15M, KXDOGE15M, KXSOL15M). These markets settle YES if the asset's price is higher at close than at open (Coinbase reference). ~~⚠️ **KXSOL15M is actively misrouted**~~ — **FIXED Sprint 4 (ISSUE-001):** `'KXSOL15M'` added to `CRYPTO_15M_SERIES` in `ws_feed.py`. Called on every WebSocket tick. Builds a weighted composite of four microstructure signals from OKX perpetual swap data, applies 10 risk filters, runs the strategy gate, sizes via Half-Kelly, and places a Kalshi order.

#### Inputs

| Data | Source | API Endpoint | Cache TTL |
|------|--------|-------------|-----------|
| Recent trades (200) | OKX | `GET /api/v5/market/trades?instId=<symbol>&limit=200` | None (live) |
| Orderbook depth (10 levels) | OKX | `GET /api/v5/market/books?instId=<symbol>&sz=10` | None (live) |
| 5-minute OHLCV candles (30) | OKX | `GET /api/v5/market/candles?instId=<symbol>&bar=5m&limit=30` | None (live) |
| Open interest (swap) | OKX | `GET /api/v5/public/open-interest?instType=SWAP&instId=<symbol>` | 600s (prev OI snapshot) |
| Spot price | Coinbase | `GET /v2/prices/<ASSET>-USD/spot` | 30s |
| Spot price (cross-check) | OKX | `GET /api/v5/market/ticker?instId=<symbol>` | 30s |
| Funding rate z-score | internal | `crypto_client._compute_funding_z_scores()` | (internal) |
| Polymarket consensus price | internal | `polymarket_client.get_crypto_consensus(asset)` | (shadow only) |
| Capital | internal | `capital.get_capital()` | None |
| Daily exposure | internal | `logger.get_daily_exposure(module=<module_name>)` | None |
| Buying power | internal | `capital.get_buying_power()` | None |
| Consecutive losses | internal | `circuit_breaker.get_consecutive_losses(module)` | File-backed |
| Today's trade log | internal | `logs/trades_YYYY-MM-DD.jsonl` | None |

**Asset symbol mapping** (`ASSET_SYMBOLS`):
- `BTC` → `BTC-USDT-SWAP`, `ETH` → `ETH-USDT-SWAP`, `XRP` → `XRP-USDT-SWAP`, `DOGE` → `DOGE-USDT-SWAP`, `SOL` → `SOL-USDT-SWAP`

#### Signal Computation

All four signals are z-scored against their own 4-hour rolling window (48 × 5-min buckets, `ROLLING_WINDOW = 48`). The `_z_score()` helper clips to `[-3.0, 3.0]` by default (OI uses `[-2.0, 2.0]`). Z-score is 0.0 if fewer than 5 values in the window.

**Signal 1: Taker Flow Imbalance (TFI) — weight `W_TFI` (config: 0.50)**

1. Fetch last 200 trades from OKX `/market/trades`.
2. Group into 5-minute buckets by `ts` field.
3. For each bucket: `tfi_bucket = (buy_volume - sell_volume) / total_volume` (ranges −1 to +1).
4. Time-weighted composite of last 3 buckets: weights `[0.20, 0.30, 0.50]`.
5. Z-score appended to rolling deque (`_rolling_tfi[symbol]`, maxlen=48).
- `stale = True` if the most recent trade timestamp is older than 90 seconds.

**Signal 2: Orderbook Imbalance (OBI) — weight `W_OBI` (config: 0.25)**

1. Fetch top 10 bid/ask levels from OKX `/market/books`.
2. Instant OBI: `(sum(bid_qty[:10]) - sum(ask_qty[:10])) / total_qty`.
3. EWM over `_obi_snapshots[symbol]` (deque, maxlen=120): alpha ≈ 0.0328 (= 2/61, span=60).
4. Z-score appended to `_rolling_obi[symbol]`.
- `stale = True` if OKX snapshot timestamp is older than 30 seconds.
- ⚠️ **See Known Issue 1.7:** EWM iterates backwards over deque — older values influence output more than expected.

**Signal 3: MACD Histogram — weight `W_MACD` (config: 0.15)**

1. Fetch last 30 5-minute candles (reversed to chronological).
2. Compute EMA-12, EMA-26 over closes. MACD line = EMA-12 − EMA-26.
3. Compute EMA-9 of MACD line. `macd_hist = macd_line[-1] - signal_line[-1]`.
4. Returns early with `stale=True` if fewer than 26 candles available.
- `stale = True` if last candle timestamp is older than 600 seconds (10 min).

**Signal 4: Open Interest Delta Conviction — weight `W_OI` (config: 0.10)**

1. Fetch current OI from OKX. Compare to 600s-cached previous OI.
1a. **Near-zero guard (Fixed P1-1 / ISSUE-129):** If `prev_oi < 1e-6`, skip computation — returns 0.0 to prevent z-score explosion on near-zero denominator.
2. `oi_conviction_raw = oi_delta_pct * sign_price` (directional OI conviction).
3. Z-score clipped to **`[-2.0, 2.0]`** (tighter than other signals — see Known Issue 1.5).

**Composite Score and Probability:**

```
raw_score = 0.50*tfi_z + 0.25*obi_z + 0.15*macd_z + 0.10*oi_z
P_directional = 1 / (1 + exp(-scale * raw_score))   [scale=1.0]
```

**Weight validation (Fixed P1-1 / ISSUE-114, ISSUE-069):** Weights are asserted (via `raise ValueError`) to sum to 1.0 ± 1e-6 at load time. If config weight keys are missing, a WARNING names the missing keys — silent Phase 1 hardcoded fallback no longer occurs.

**Bias Filters:**
- Funding rate z: if `|fr_z| > 2.0` → multiply P by 0.85 (bearish) or 1.15 (bullish).
- Polymarket nudge: **always forced to 0.0** (shadow/logging only). See Known Issue 1.4.

```
P_final = max(0.05, min(0.95, P_biased + poly_nudge))  [poly_nudge always 0.0]
```

**Timing Gates:**
- `elapsed < 90s` → EARLY_WINDOW skip
- `90s ≤ elapsed ≤ 480s` → primary window, base `min_edge = 0.02`
- `480s < elapsed ≤ 800s` → secondary window, `min_edge = 0.02 * 1.25 = 0.025`
- `elapsed > 800s` → LATE_WINDOW skip

#### Ten Risk Filters (`check_risk_filters`)

| Filter | Name | Condition | Block Reason |
|--------|------|-----------|--------------|
| R1 | Extreme realized vol | `vol_5m > 3.0 * avg_price_vol_30d` | `EXTREME_VOL` |
| R2 | Wide spread | `(yes_ask - yes_bid) > 25¢` | `WIDE_SPREAD` |
| R3 | Thin Kalshi book | `book_depth_usd < max(dollar_oi * 0.0005, 20.0)` | `LOW_KALSHI_LIQUIDITY` |
| R4 | Thin underlying volume | `okx_volume_pct < 0.01` | `THIN_MARKET` |
| R5a | Stale TFI | `tfi['stale'] == True` | `TFI_STALE` |
| R5b | Stale OBI | `obi['stale'] == True` | `OBI_STALE` |
| R6 | Extreme funding | `abs(fr_z) > 3.0` | `EXTREME_FUNDING` |
| R7 | Low conviction | `abs(raw_score) < 0.05` | `LOW_CONVICTION` |
| R8 | Session drawdown | `session_pnl < -0.05 * capital` | `DRAWDOWN_PAUSE` |
| R9 | Macro event | `has_macro_event_within(minutes=30)` | `MACRO_EVENT_RISK` |
| R10 | Basis risk | `abs(coinbase_price - okx_price) / okx_price > 0.0015` | `BASIS_RISK` |

Note: R2, R3, R4 thresholds are relaxed for Phase 2 data-collection mode (see Known Issue 1.11).

#### crypto_15m Own Sizing (overrides strategy size)

After `should_enter()` approves, the module computes its own Half-Kelly:

```python
kelly_half = ((P_win - c) / (c * (1-c))) / 2
position_usd = min(kelly_half * capital, capital * 0.01, $100 hard cap)
position_usd = max(position_usd, $5 floor)
```

Then three-tier cap check: circuit breaker (3 consecutive losses = hard stop), daily backstop (disabled), window cap (4% of capital per 15-min window; **Fixed P1-1 (ISSUE-105):** actual spend computed as `contracts × price/100` inside lock — no longer overcharged on partial/trimmed fills). The `decision['size']` from `should_enter()` is **discarded** (see Known Issue 1.2).

#### Output Signal Dict and Decision Log

- Signal dict to `should_enter()`: `{ticker, side, edge, win_prob, confidence, module, yes_ask, yes_bid, hours_to_settlement, open_position_value}`
- ⚠️ `confidence` = `abs(raw_score)` — a z-score magnitude, **NOT a probability** (see Known Issue 1.1)
- Decision log per evaluation (ENTER or SKIP): `logs/decisions_15m.jsonl`

---

### 1.3 Module: crypto_threshold_daily.py — Daily Above/Below

**Source file:** `agents/ruppert/trader/crypto_threshold_daily.py`

**Purpose:** Trades Kalshi daily above/below markets (KXBTCD, KXETHD, KXSOLD). Uses 5 daily-scale signals. Entry windows time-gated (primary 09:30–11:30 ET, secondary 13:30–14:30 ET). Settlement 17:00 ET daily.

#### Inputs

| Data | Source |
|------|--------|
| Daily OHLCV candles (30) | OKX `/api/v5/market/candles?bar=1D` |
| Funding rate + cumulative | Binance Futures via `crypto_client._compute_funding_z_scores()` |
| Current OI | OKX `/api/v5/public/open-interest` |
| OI 24h baseline | `logs/oi_1d_snapshot.json` |
| Polymarket consensus | `polymarket_client.get_crypto_daily_consensus(asset)` — **Fixed P1-6 (ISSUE-057):** switched from `get_crypto_consensus` (15m intraday scale) to `get_crypto_daily_consensus` (end-of-day scale, matches daily contract horizon). No longer labeled shadow — signal is actively used at 20% weight when available. |
| Kalshi markets | `KalshiClient.get_markets_metadata()` |
| Capital / exposure | `capital.get_capital()`, `logger.get_daily_exposure()`, `capital.get_buying_power()` |

#### Five Signals

**S1: 24h Momentum** — z-score of daily return vs 29-day history. Raw score = `clamp(z, -2, 2) / 2.0` → `[-1, 1]`.

**S2: Funding Rate Regime** — Binance cumulative 24h funding. Sign-inverted: high positive funding (longs paying) → mild bearish signal. `filter_skip = True` if `|funding_24h_z| > 3.5`.

**S3: ATR Band** — Rolling ATR-14 percentage. Sizing multiplier only (not directional). `raw_score = 0.0` always.

**S4: OI Regime** — 24h OI delta vs baseline from `oi_1d_snapshot.json`. If snapshot stale (>26h): weight = 0, redistributes to S1/S2/S3. If missing (bootstrap): neutral with full weight.

**S5: Polymarket Consensus** — calls `get_crypto_daily_consensus(asset)` (**Fixed P1-6, ISSUE-057:** was `get_crypto_consensus` which returned 15m intraday-scale prices, not end-of-day). `yes_price` → `raw_score = (yes_price - 0.5) * 2`. **Fixed P1-6 (ISSUE-089):** None guard added; bounds gate `[0.25, 0.75]` applied — if `yes_price` outside this range, S5 is skipped (far-from-money strikes suppressed, weight falls to 0%). Weight = 20% if available and in-bounds, 0% otherwise.

**Composite Score:**
```
P_above = sigmoid(raw_composite * 3.0)
direction: P_above > 0.54 → 'above'; P_above < 0.46 → 'below'; else 'no_trade'
```

#### Key Behaviors

- **Does NOT call `should_enter()`** — bypasses strategy gate entirely (see Known Issue 1.3).
- Calls `Trader.execute_opportunity()` directly, wrapped in portalocker cap lock (**Fixed P1-6 / ISSUE-053:** concurrent BTC+ETH evaluations are now serialized — both assets cannot simultaneously pass the cap check and place orders).
- Capital management via explicit per-asset cap (3%), daily cap (15%), secondary window global exposure gate (50%).
- Position sizing: Half-Kelly with ATR modifier, capped at $200 hard cap, $10 floor.
- OI snapshot written **after** successful trade (step 12), read during S4 computation (step 4). See Known Issue 1.10.

---

### 1.4 Module: crypto_band_daily.py — Daily Band (Range)

**Source file:** `agents/ruppert/trader/crypto_band_daily.py`

**Purpose:** Scans Kalshi daily band/range markets (KXBTC, KXETH, KXXRP, KXSOL, KXDOGE). Log-normal probability model. Top 3 opportunities by edge per scan cycle. **Fixed P1-6 (ISSUE-016):** previously filtered out same-day contracts via `ct.date() <= today`; now uses `ct <= datetime.now(UTC)` — same-day unexpired contracts are eligible. Trade execution isolated in `_execute_band_trades()` helper, wrapped in portalocker `LOCK_EX` cap lock to prevent concurrent cap race (**Fixed P1-6 / ISSUE-053**).

#### Inputs

| Data | Source |
|------|--------|
| Spot prices | Kraken `GET /0/public/Ticker?pair=<sym>` |
| All market metadata | Kalshi `KalshiClient.get_markets_metadata()` |
| Orderbook (per market) | Kalshi `KalshiClient.enrich_orderbook()` (parallel, 10 workers) |
| Composite confidence | `crypto_client.compute_composite_confidence()` |
| Capital / exposure | `capital.get_capital()`, `logger.get_daily_exposure()`, `capital.get_buying_power()` |

#### Signal: Log-Normal Band Probability

```python
sigma_m = daily_vol * sqrt(max(1.0, hours_left) / 24.0)
prob_model = norm.cdf((log(hi) - mu) / sigma_m) - norm.cdf((log(lo) - mu) / sigma_m)
edge = max(edge_yes, edge_no)
```

**Per-series parameters:**

| Series | half_w | daily_vol |
|--------|--------|-----------|
| KXBTC | $250 | 2.5% |
| KXETH | $10 | 3.0% |
| KXXRP | $0.01 | 4.5% |
| KXSOL | $5.00 | 4.5% |
| KXDOGE | $0.005 | 5.0% |

**Drift is always 0.0** — hardcoded at top of `run_crypto_scan()`. See Known Issue 1.6.

#### How it Calls strategy.py

Uses `should_enter()` and respects `decision['size']` (unlike crypto_15m which ignores it). Module daily cap (7%) enforced before the loop. ⚠️ **Module daily cap config key `CRYPTO_BAND_DAILY_BTC_DAILY_CAP_PCT` does not exist in config** — strategy gate fails open, relies on module's own 7% check (see Known Issue 1.12).

---

### 1.5 Strategy Layer: strategy.py

**Source file:** `agents/ruppert/strategist/strategy.py`  
**Shim:** `environments/demo/bot/strategy.py` (re-exports only)

**Purpose:** Single source of truth for capital allocation. Converts signals into binary enter/reject + dollar size. Seven gates in order; first failure short-circuits.

#### Gate Sequence

| Gate | Check | Rejection Reason |
|------|-------|-----------------|
| 1 | `hours_to_settlement < min_hours` (default 0.5h; crypto_15m: 0.04h) | `too_close_to_settlement` |
| 2 | `confidence < per_module_threshold` (0.40–0.55 by module) | `low_confidence` |
| 3 | `edge < module_min_edge` (0.08–0.15 by module) | `insufficient_edge` |
| 4 | `open_position_value >= capital * 0.70` | `global_exposure_cap_reached` |
| 5 | `module_deployed_pct >= module_cap_pct` (if cap exists in config) | `module_cap_exceeded` | **Fixed P1-1 (ISSUE-104):** `_module_cap_missing = False` initialized before the `if module is not None:` block. Previously, `module=None` caused `NameError` (variable used before assignment). Now safely defaults to `False` in all paths. |
| 6 | `ticker in traded_tickers` | `same_day_reentry` |
| 7 | `check_daily_cap(capital, deployed_today) <= 0` | `daily_cap_reached` |

#### Sizing

```python
kf = kelly_tier(confidence)  # 0.05 to 0.16 based on confidence band
f = edge / (1 - win_prob)    # raw Kelly fraction
kelly_size = kf * f * capital * (1/vol_ratio)
raw_size = min(kelly_size, capital * 0.01)  # 1% per-trade hard cap
impact_size = apply_market_impact_ceiling(raw_size, yes_ask, yes_bid, open_interest)
# spread ≤3c: full; 4-7c: *0.5; >7c: min(raw_size, $25)
# Phase 2 OI cap: if open_interest provided → additional cap at 5% of OI (MARKET_IMPACT_OI_CAP_PCT=0.05)
size = min(impact_size, daily_room)
if size < min_viable: reject 'below_min_viable'
```

**Confidence-tiered Kelly fractions:** `0.16 (≥80%), 0.14 (≥70%), 0.12 (≥60%), 0.10 (≥50%), 0.07 (≥40%), 0.05 (≥25%)`

#### Min Edge by Module (Strategy Gate)

| Module | Min Edge |
|--------|----------|
| `crypto_band_daily_*` | 0.12 |
| `crypto_dir_15m_*` | 0.12 (strategy gate; local gate is 0.02) |
| `crypto_threshold_daily_*` | 0.08 (bypassed — module doesn't call `should_enter`) |
| `weather_band`, `weather_threshold` | 0.12 |
| `geo` | 0.15 |
| `econ_*` | 0.12 |

---

### 1.6 Known Quirks — Entry Pipeline

1. **confidence = z-score in crypto_15m, NOT probability.** Strategy confidence gate (e.g. 0.50 threshold) is compared against `abs(raw_score)` which is a composite z-score magnitude, not a 0–1 probability.
2. **crypto_15m ignores strategy.py size.** `decision['size']` is discarded; module uses its own Half-Kelly.
3. **crypto_threshold_daily bypasses `should_enter()` entirely.** No strategy gate runs.
4. **Polymarket nudge always 0.** Code computes nudge, then forces `poly_nudge = 0.0` before applying.
5. **OI signal clips to ±2, not ±3.** Smaller max contribution than other signals.
6. **Band drift always 0.0.** `drift_sigma = 0.0` hardcoded in `run_crypto_scan()`.
7. **EWM direction reversal in OBI.** Loop iterates from newest backward; older values may influence EWM more than expected.
8. **Ticker timing encodes CLOSE time in EST.** `open_dt = close_dt - 15 minutes`.
9. **strategy.py is a shim.** Real logic in `agents/ruppert/strategist/strategy.py`.
10. **OI snapshot written AFTER trade, read BEFORE signals.** First-run bootstrap returns neutral S4.
11. **Data-collection mode thresholds.** `CRYPTO_15M_MAX_SPREAD=25¢`, `CRYPTO_15M_THIN_MARKET_RATIO=0.01`, `CRYPTO_15M_MIN_EDGE=0.02` — all looser than production.
12. **Module daily cap config for crypto_band_daily_* absent.** Strategy gate logs warning and fails open.
13. **Smart money wallet path (Fixed P1-5 / ISSUE-032):** `crypto_client._WALLETS_FILE` now resolves via `env_config.get_paths()['logs']`. Previously hardcoded to wrong path — silently used 3-wallet fallback. Now emits WARNING on empty/missing file.
14. **Fixed P1-6 (ISSUE-053):** Concurrent BTC+ETH daily scans (`crypto_band_daily.py` and `crypto_threshold_daily.py`) had a cap race condition — two async evaluations could both read the same module exposure and both pass the cap check before either wrote a trade. **Resolved:** both daily modules now wrap the cap-check + execute path with `portalocker` (file lock). BTC and ETH evaluations within the same module are serialized.

---

## 2. Execution Layer

_Source: `memory/agents/sysmap-section2-execution.md`_

### 2.1 Full Execution Flow

```
should_enter() returns True
        │
        ▼
  opp['strategy_size'] = decision['size']   ← set by caller
        │
        ▼
  Trader.execute_opportunity(opp)
        │
        ├─ [Guard] require_live_enabled() if env=live  → raises RuntimeError if not enabled
        ├─ [Guard] position_tracker.is_tracked(ticker, side)?  → return False if yes
        ├─ [Guard] strategy_size missing or <= 0?  → log + Telegram + return False
        ├─ price_cents = yes_price (YES) or 100-yes_price (NO)
        ├─ contracts = int(strategy_size / (price_cents/100)), min 1
        │
        ├─ [DRY RUN] log_trade(opp, size, contracts, {'dry_run': True, 'status': 'simulated'})
        │            position_tracker.add_position(...)
        │            return True
        │
        └─ [LIVE] result = KalshiClient.place_order(ticker, side, price_cents, contracts)
                  fill_contracts = result.get('filled_count') or result.get('count') or contracts
                  fill_price = result.get('yes_price') or result.get('price') or price_cents
                  [NO-side] fill_price = no_ask or (100 - yes_price)  ← Fixed P1-6 (ISSUE-017): explicit NO-side price; not derived from yes_price fallback. crypto_threshold_daily now includes no_ask in trade_opp dict (root cause fix). crypto_band_daily also updated for robustness.
                  log_trade(opp, size, fill_contracts, result)
                  position_tracker.add_position(...)
                  return True
                  [EXCEPTION] log_trade(opp, size, 0, {'error': str(e), 'status': 'failed'})
                  return False
```

**Key invariant:** `log_trade()` is called in ALL three paths (dry_run, live success, live failure). Failed orders are logged with `contracts=0` and `order_result={'error': ..., 'status': 'failed'}`.

---

### 2.2 KalshiClient — Key Methods

**Source file:** `agents/ruppert/data_analyst/kalshi_client.py`

| Method | Behavior |
|--------|----------|
| `__init__()` | Reads RSA key + API key ID from `kalshi_config.json`. Demo mode: prints "DEMO mode — all order methods are BLOCKED". |
| `get_balance()` | Returns dollars (Kalshi returns cents). Retries 3×. |
| `search_markets()` | Fetches weather series markets + enriches orderbooks. 0.1s sleep between markets. |
| `get_markets_metadata()` | Paginates all markets for a series (no orderbook enrichment — fast path). |
| `get_markets()` | Fetches markets list with optional filters. |
| `get_market()` | Fetches single market by ticker. |
| `enrich_orderbook()` | Enriches single market dict: `no_bid`, `yes_ask`, `yes_bid`, `no_ask`. |
| `place_order()` | **Demo:** returns `{"dry_run": True, "simulated": True, "environment": "demo"}`. **Live:** calls SDK `create_order()` with RSA auth. |
| `cancel_order()` | Cancels an open order by order ID. |
| `amend_order()` | Amends an existing order. |
| `sell_position()` | Same demo block pattern. Live: SDK `create_order()` with `action='sell'`. |
| `get_positions()` | SDK + raw REST fallback if Pydantic deserialization fails (StrictInt None). |
| `get_orders()` | Fetches open/closed orders. |
| `_build_rest_auth_headers()` | Builds RSA/PSS signed auth headers for direct REST calls. |
| `_get_positions_raw()` | Raw REST positions fetch (used as fallback when SDK deserialization fails). |
| `_get_with_retry()` | 3 retries. 429 → reads Retry-After header. 5xx → exponential backoff. |

**Demo note:** Both demo and live use `PROD_HOST = 'https://api.elections.kalshi.com/trade-api/v2'`. Demo is distinguished by account credentials, not URL.

---

### 2.3 Trader — Order Sizing

**Source file:** `agents/ruppert/trader/trader.py`

- `contracts_from_size(size_dollars, price_cents)` → `int(size_dollars / (price_cents / 100))`, min 1.
- `Trader.__init__(dry_run=True)` → fetches and stores `self.bankroll`.
- `Trader.execute_opportunity(opp)` → returns True (placed/logged) or False (skipped/failed).
- `Trader.execute_all(opportunities)` → returns count of True returns.

**Fields set on opportunity dict before `log_trade()`:**

| Field | Type | Value |
|---|---|---|
| `scan_contracts` | int | Contracts from strategy_size |
| `fill_contracts` | int | Actual fill or fallback |
| `scan_price` | int | Computed price_cents |
| `fill_price` | int | Actual fill price or fallback |

---

### 2.4 logger.py — Trade Logging

**Source file:** `agents/ruppert/data_scientist/logger.py`

**File locations:**
- Trade logs: `{env_paths['trades']}/trades_YYYY-MM-DD.jsonl` (one file per PDT calendar day)
- Activity logs: `{env_paths['logs']}/activity_YYYY-MM-DD.log`
- Log rotation: 90 days via `rotate_logs()`

**`build_trade_entry()` — complete field list:**

| Field | Type | Source |
|---|---|---|
| `trade_id` | str (uuid4) | Generated fresh |
| `timestamp` | str (ISO) | `opportunity.get('timestamp')` or now |
| `date` | str (YYYY-MM-DD) | `opportunity.get('date')` or `_today_pdt()` — **Sprint 5 (ISSUE-044):** uses PDT timezone via `_today_pdt()` helper; replaces `str(date.today())` which used system/local TZ |
| `ticker` | str | Required |
| `title` | str | Fallback to ticker |
| `side` | str | Required |
| `action` | str | Normalized: 'buy', 'exit', 'open', or lowercased |
| `action_detail` | str | Raw pre-normalization value |
| `source` | str | e.g. 'weather', 'crypto', 'ws_position_tracker' |
| `module` | str | From opportunity or `classify_module()` |
| `noaa_prob` | float\|None | Weather model probability |
| `market_prob` | float\|None | Market price at entry |
| `edge` | float\|None | |
| `confidence` | float\|None | `abs(edge)` fallback if None |
| `ensemble_temp_forecast_f` | float\|None | `ensemble_mean` |
| `model_source` | str\|None | |
| `ensemble_components` | dict\|None | From `models_used` |
| `entry_price` | float\|None | From `entry_price` or `fill_price` |
| `size_dollars` | float | `size` argument |
| `contracts` | int | `contracts` argument |
| `scan_contracts` | int\|None | |
| `fill_contracts` | int\|None | |
| `scan_price` | int\|None | |
| `fill_price` | int\|None | |
| `order_result` | dict | SDK response, dry_run stub, or error dict |
| `data_quality` | str\|None | crypto_15m only |
| `okx_volume_pct` | float\|None | crypto_15m only |
| `kalshi_book_depth_usd` | float\|None | crypto_15m only |
| `kalshi_spread_cents` | float\|None | crypto_15m only |
| `model_prob` | float\|None | crypto_15m only |

**Write path (Sprint 3 / ISSUE-077):** All JSONL writes go through `_append_jsonl()`, which acquires a `portalocker.LOCK_EX` file lock before appending. This provides cross-process write safety when multi-process scans and the WS feed write simultaneously. If portalocker is unavailable, falls back to unlocked append with a WARNING log.

**Dedup check (buy records):** Fingerprint = `(ticker, side, date, entry_price, contracts)`. Session-level in-memory set — **resets on process restart** (see Known Issue 2.4).

**Dedup check (exit/settle records — Sprint 3 / ISSUE-023):** `_logged_exit_fingerprints` set. `log_exit()` and `log_settle()` compute a fingerprint from `(ticker, side, action, date, contracts)` before writing. Duplicate exit/settle writes within the same process are silently dropped. Persists for the lifetime of the process.

**Key logger functions:**

| Function | Purpose |
|----------|---------|
| `log_trade()` | Write buy/open trade record (all paths) |
| `log_exit(pos, pnl, exit_price, rule, **extra)` | **Sprint 3:** Write exit record via unified schema + dedup fingerprint. All position_tracker exit writes route here. |
| `log_settle(pos, result, pnl, **extra)` | **Sprint 3:** Write settle record via unified schema + dedup fingerprint. All settlement writes route here. |
| `get_daily_exposure(module, asset)` | Total open exposure since START_DATE (`2026-03-26` hardcoded). Explicitly excludes `failed_order` records (Sprint 2). |
| `get_daily_wager(module)` | Total buy dollars for module today |
| `get_window_exposure(module, window_open_ts)` | Dollars for a specific 15m window |
| `compute_closed_pnl_from_logs()` | Sum `pnl` from exit/settle + `pnl_correction` from exit_correction. Canonical P&L source. |
| `acquire_exit_lock(ticker, side)` | File-based mutex; stale locks (>5 min) auto-removed |
| `classify_module(src, ticker)` | Maps (source, ticker) → canonical module name |

---

### 2.5 Scan Orchestration

**`ruppert_cycle.py`** (`environments/demo/ruppert_cycle.py`) — Cycle orchestrator.

**Supported modes:**

| Mode | Schedule | What runs |
|---|---|---|
| `full` | 7am, 3pm | All modules: weather + crypto + long-horizon + fed + geo |
| `check` | 10pm | Position check only |
| `econ_prescan` | 5am | Position check + econ scan |
| `weather_only` | 7pm | Position check + weather scan |
| `crypto_only` | 8am–8pm (every 2h) | Position check + crypto scan |
| `crypto_1d` | 9:30 ET, 1:30 ET | Daily crypto above/below scan |
| `report` | 7am | P&L summary + loss detection + optimizer review |
| `smart` | (placeholder) | **Runs as `check` mode — not implemented** (see Known Issue 2.7) |

**`run_cycle()` step sequence:**
1. Print banner, rotate logs
2. `KalshiClient()` init
3. `load_traded_tickers()` — today's log + `state.json` (stale if different day)
4. `get_capital()` → circuit breaker check; `sys.exit(0)` if tripped
5. `get_buying_power()` → `compute_open_exposure()`
6. Build `CycleState` dataclass
7. Historical audit (full/smart/econ_prescan modes)
8. `run_orphan_reconciliation()` — alert on orphaned positions
9. `run_exposure_reconciliation()` — alert if divergence > $50 and > 5%
10. `run_position_check()` — auto-exit weather positions (P&L > $4, margin < 2°F)
11. Dispatch to mode handler
12. `save_state()` → writes `logs/state.json`
13. `run_post_scan_audit()` (data agent)
14. `log_cycle(mode, 'done', summary)`

**`load_traded_tickers()` note:** Exits do NOT remove tickers from the set — once traded, blocked all day.

---

### 2.6 Trade Log Record Types

All records in `logs/trades/trades_YYYY-MM-DD.jsonl`.

**Buy record** (`action='buy'`) — new position opened.  
**Exit record** (`action='exit'`) — position closed early (auto or manual).  
⚠️ **`pnl` field NOT set by `build_trade_entry()`** — callers must set `opportunity['pnl']` before calling `log_trade()`. See Known Issue 2.2. **Partially fixed P1-2 (ISSUE-030):** `ruppert_cycle.py` and `post_trade_monitor.py` exit paths now set `pnl` on the opportunity dict before `log_trade()`. Remaining exit paths (if any) still require caller to set `opportunity['pnl']`.  
**Settle record** (`action='settle'`) — market settled at 100c (win) or 0c (loss). Same schema as exit. **Sprint 3:** All settle writes now route through `logger.log_settle()` wrapper (unified schema + dedup fingerprint).  
**Exit correction record** (`action='exit_correction'`) — corrects prior wrong P&L via `pnl_correction` field (positive or negative delta). `compute_closed_pnl_from_logs()` sums `pnl_correction` from all `exit_correction` records — this is part of canonical closed P&L. ⚠️ `trade_id` on exit_correction records is **NOT a uuid4** — it is `original_trade_id + "_correction"` (appended suffix). The `original_trade_id` field holds the referenced record's ID.

---

### 2.7 Known Issues — Execution Layer

| ID | Description | Severity |
|----|-------------|----------|
| ISSUE-E01 | ~~Failed orders logged as `action='buy'` with `contracts=0`. `get_daily_exposure()` counts `size_dollars` of failed orders.~~ **FIXED Sprint 2 (ISSUE-029/099, commit d286b28):** Failed orders now use `action='failed_order'` and `size_dollars=0.0`. `get_daily_exposure()` explicitly excludes `failed_order` records. | ~~High~~ **Resolved** |
| ISSUE-E02 | `pnl` field missing from most exit paths. `compute_closed_pnl_from_logs()` returns $0 for exits without explicit `opportunity['pnl']` set by caller. **Partially fixed P1-2 (ISSUE-030):** `ruppert_cycle.py` and `post_trade_monitor.py` now set `pnl` on the opportunity dict before logging. Remaining paths may still be affected. | Medium |
| ISSUE-E03 | `run_exit_scan()` raises `RuntimeError` unconditionally. Dead code preserved in `main.py`. | Low |
| ISSUE-E04 | Session-level dedup only. Process restarts allow re-logging same trade. | Medium |
| ISSUE-E05 | `strategy_size` missing → trade skipped + Telegram alert. Guard works, but the failure mode is silent data loss. | Medium |
| ISSUE-E06 | `get_daily_exposure()` START_DATE hardcoded to `'2026-03-26'`. Brittle on redeployment. | Low |
| ISSUE-E07 | `smart` mode runs `check` mode — not implemented. | Medium |
| ISSUE-E08 | Demo mode blocks all orders silently, but `log_trade()` still writes buy records. Trades appear real in logs. | Low |

---

## 3. Exit Pipeline

_Source: `memory/agents/sysmap-section3-exit-pipeline.md`_

### 3.1 Position Lifecycle Overview

```
[Trade Executed]
      │
      ▼
add_position()          ← position_tracker.py — stores key=(ticker,side)
      │                    persists to tracked_positions.json
      │
      ▼
[WS Feed Running]       ← ws_feed.py receives live ticker ticks
      │    Every tick:
      │    check_exits(ticker, yes_bid, yes_ask)
      │    → stop-loss tiers (15m + daily)
      │    → gain thresholds (95c / 70%/90% gain)
      │         │ threshold triggered
      │         ▼
      │    execute_exit() → logs trade, calls sell_position()
      │    remove_position() → removes from in-memory + disk
      │    _recently_exited → 5-min cooldown guard
      │
      │    Every 60 seconds:
      │    check_expired_positions()
      │    → REST-verify settlement for expired tickers
      │         │
      │         ▼
      │    logs settle record, removes position
      │
      ▼
[Settlement Checker]    ← settlement_checker.py (scheduled 3× daily: 11PM, 8AM, 6AM)
      │  Catches: WS was down, cycle-entered positions, multi-buy legs
      ▼
[Done — trade log has buy + exit/settle record]
```

**Key files:**
- Tracker state: `environments/demo/logs/tracked_positions.json`
- CB state: `environments/demo/logs/circuit_breaker_state.json`
- Price cache: `environments/demo/logs/price_cache.json`
- WS heartbeat: `environments/demo/logs/ws_feed_heartbeat.json`

---

### 3.2 position_tracker.py — Core Exit Engine

**Location:** `agents/ruppert/trader/position_tracker.py`

#### Tracked Position Schema

| Field | Type | Description |
|-------|------|-------------|
| `quantity` | int | Contracts held |
| `side` | str | `'yes'` or `'no'` |
| `entry_direction` | str | Same as side (redundant alias) |
| `entry_price` | float | Entry price in **cents**. NO positions: always stored as NO-side price (100 − yes_price). |
| `module` | str | Module that opened the trade |
| `title` | str | Human-readable market title |
| `added_at` | float | `time.time()` at add — used for stop-loss elapsed time guards |
| `exit_thresholds` | list | Threshold dicts |
| `entry_raw_score` | float\|None | Signal score at entry |
| `size_dollars` | float | Actual dollar cost (cost basis) |
| `entry_secs_in_window` | float\|None | Seconds from window open to entry (sets stop-loss guard bracket) |
| `contract_remaining_at_entry` | float\|None | Seconds remaining in window at entry |

**Accumulation:** If `add_position()` is called for same `(ticker, side)`, position is accumulated — quantity summed, entry price blended (weighted average), thresholds recomputed.

**NO-side price normalization (Sprint 5 — ISSUE-042 fix):** The `100 - entry_price` flip has been **removed** from `add_position()`. NO positions now store the raw NO-side price as provided (e.g. 3c for a contract trading at 3c NO). The legacy migration block that attempted to flip pre-existing NO positions has also been removed from `_load()`. Entry prices for NO positions were previously stored as `100 - yes_price` (e.g. 97c) — this was wrong and has been corrected. Historical records from 2026-04-02/03 were corrected via 125 DS-inserted `exit_correction` records.

#### Exit Threshold Schema

```python
{
    'price': float,        # cents trigger level
    'action': 'sell_all',
    'rule': str,           # '95c_rule', '70pct_gain', '95c_rule_no', '70pct_gain_no'
    'compare': str,        # 'gte' (YES) or 'lte' (NO)
}
```

YES thresholds: 95c rule always present; 70%/90% gain threshold if < 95c (not for long_horizon).  
NO thresholds: 5c rule (equivalent to 95c win for NO); 70%/90% gain equivalent.

Config: `EXIT_95C_THRESHOLD = 95`, `EXIT_GAIN_PCT = 0.90` (Phase 2; was 0.70).

**Sprint 5 (ISSUE-043):** `EXIT_GAIN_PCT` is now required in config. `getattr(config, 'EXIT_GAIN_PCT', 0.70)` fallback has been removed — missing key now raises `ImportError` at startup rather than silently using a stale default.

#### Stop-Loss Tiers — 15m Directional Positions

**Applies to:** modules starting with `crypto_dir_15m_`

**Entry guard:** No stops until `elapsed_secs >= min_elapsed`:

| Entry timing | Config key | Default |
|---|---|---|
| ≥ 8 min (`STOP_BRACKET_LATE=480`) | `STOP_GUARD_SECONDARY` | 90s |
| 5–8 min (`STOP_BRACKET_MID=300`) | `STOP_GUARD_LATE_PRIMARY` | 180s |
| 3–5 min (`STOP_BRACKET_EARLY=180`) | `STOP_GUARD_MID_PRIMARY` | 300s |
| < 3 min | `STOP_GUARD_EARLY_PRIMARY` | 480s |

**Three stop-loss tiers:**

| Tier | Price Threshold | Time Check | Rule format |
|------|----------------|------------|-------------|
| Catastrophic | `< 20% of entry` | Any time | `stop_loss_catastrophic_{elapsed}s` |
| Severe | `< 30% of entry` | `< 5 min remaining` | `stop_loss_severe_{elapsed}s` |
| Terminal | `< 40% of entry` | `< 3.5 min remaining` | `stop_loss_terminal_{elapsed}s` |

#### Stop-Loss Tiers — Daily Positions

**Applies to:** `crypto_band_daily_*` and `crypto_threshold_daily_*`

**Entry guard:** `elapsed_secs >= 1800s` (30 min)

| Level | Condition | Time Check | Action |
|-------|-----------|------------|--------|
| Write-off | `yes_bid <= 1` | `< 20 min remaining` | No sell — log and expire |
| Catastrophic | `< max(entry * 15%, 2c)` | Any time | execute_exit |
| Severe | `< entry * 25%` | `< 1h remaining` | execute_exit |
| Terminal | `< entry * 30%` | `< 20 min remaining` | execute_exit |

**Sprint 5 (ISSUE-042) — Design D gate and side resolution:** `side` is now resolved from `key[1]` at the **top** of the `check_exits()` loop, before any stop logic runs. Design D stop tiers (daily catastrophic/severe/terminal) are gated to `side == 'yes'` only. NO-side daily positions skip all Design D stop checks. Previously, NO positions with a flipped `entry_price` (e.g. 97c for a 3c NO) could trigger Design D stops incorrectly because the stored price was near the YES win threshold rather than near zero.

#### execute_exit() — P&L Calculation

```
YES: pnl = (current_bid - entry_price) * quantity / 100
NO:  pnl = (100 - current_bid - entry_price) * quantity / 100
     (entry_price is now the raw NO-side price, e.g. 3c — not the previously-flipped 97c)
settle_loss: pnl = -size_dollars  (cost-basis approach)
```

**Sprint 1 Batch 2 — Exit dedup (ISSUE-002 fix):** `execute_exit()` uses `_exits_lock = asyncio.Lock()` to atomically check-and-set `_exits_in_flight`. The check+add of the in-flight guard is wrapped in `async with _exits_lock`. This eliminates the race condition where two concurrent exit coroutines could both pass the guard before either set the flag.

**Sprint 1 Batch 2 — Exit failure handling (ISSUE-003 fix):** A `_exit_failures` counter is tracked per position dict. After 3 consecutive `sell_position()` failures the position is abandoned: a synthetic `action='exit'`, `action_detail='ABANDONED after 3 exit failures'` JSONL record is written (DS-NEW-001, commit 4a92830), `push_alert` is called (try/except wrapped), and `remove_position()` is called. This prevents infinite retry loops on persistently failing exits.

**Sprint 1 Batch 2 — Stale position refs (ISSUE-107 fix):** `entry_price`, `quantity`, `module`, `title`, and `size_dollars` are snapshotted to local variables before the first `await` in `execute_exit()`. Prevents stale-reference bugs where `_tracked` dict mutation during an await could cause P&L or log records to use wrong values.

**Exit record written** (`action='exit'`):

```json
{
  "trade_id": "<uuid4>",
  "ticker": "<str>",
  "side": "yes|no",
  "action": "exit",
  "action_detail": "WS_EXIT <rule> @ <price>c (yes_bid=<Xc>)",
  "source": "ws_position_tracker",
  "module": "<str>",
  "entry_price": "<float cents>",
  "exit_price": "<float cents>",
  "contracts": "<int>",
  "pnl": "<float dollars, 2dp>",
  "date": "<YYYY-MM-DD in PDT timezone>",
  "edge": "<float|null>",
  "confidence": "<float|null>"
}
```

Note: `edge` and `confidence` fields added by **Fixed P1-5 (ISSUE-074)** — forwarded from position dict by `post_trade_monitor.py` exits. WS-path exits via `position_tracker.execute_exit()` may not populate these unless the position dict has them.

**Sprint 3 (ISSUE-023):** All exit writes now route through `logger.log_exit()` wrapper, which enforces unified schema and dedup fingerprint via `_logged_exit_fingerprints`.

**Sprint 5 (ISSUE-044):** `date` field now uses `_today_pdt()` helper (PDT timezone) instead of `str(date.today())` (system TZ).

After logging: calls `_update_daily_cb()`, removes position, records 5-min cooldown.

#### check_expired_positions() — Expiry Settlement

Every 60s. For each tracked position past `close_dt`: REST-fetches market result, logs settle record (using 100c for wins), removes from tracker.

**`position_monitor._settle_single_ticker()` (Fixed P1-5 / ISSUE-098, commit 8a32658):** `exit_price` changed from 99 to 100 for wins. P&L formula corrected for both YES-win path: `(100 - entry_price) * contracts / 100` and NO-win path. Previously overstated NO-side win P&L by ~2.4×.

**`post_trade_monitor.check_alert_only_position()` (Fixed P1-5 / ISSUE-079):** Now uses `normalize_entry_price(pos)` helper for entry price normalization. Previously used broken inline logic that could produce incorrect entry price values for alert threshold checks.

#### recovery_poll_positions()

Called on WS disconnect. REST-polls all tracked positions to catch missed price moves.

---

### 3.3 ws_feed.py — Real-Time Position Monitor

**Location:** `agents/ruppert/data_analyst/ws_feed.py`  
**Run mode:** Persistent process (Task Scheduler or standalone).

#### Architecture

```
run_ws_feed()
  ├── market_cache.load()
  ├── while True:  [outer reconnect loop]
  │     ├── websockets.connect(wss://...)
  │     ├── subscribe {channels: ['ticker']}  — ALL tickers, no filter
  │     ├── fallback_task = _fallback_poll_loop()
  │     ├── _check_and_fire_fallback()  — immediate bootstrap check
  │     └── while True:  [message loop]
  │           ├── ws.recv(timeout=30)  — 30s zombie detection
  │           ├── handle_message()
  │           ├── [every 60s] market_cache.persist() + _write_heartbeat()
  │           ├── [every 60s] position_tracker.check_expired_positions()
  │           └── [every 300s] cache purge + REST heal + window guard prune
  └── on exception: recovery_poll_positions() + exponential_backoff(5→10→20→60s) + reconnect
```

**WS connect params:** `ping_interval=None, ping_timeout=None` — server-side pings only (client pings caused false 1011 disconnects).

**Reconnect delay:** Exponential backoff — starts at 5s, doubles each reconnect, caps at 60s (sequence: 5→10→20→40→60s). **Fixed P1-5 (ISSUE-096, commit a441a6d).** Applied to both timeout and exception paths.

**Sprint 1 — Async/blocking fixes:**
- **ISSUE-014:** `evaluate_crypto_entry()` inside `_safe_eval_hourly()` now runs via `run_in_executor(None, ...)`. REST-dependent evaluation no longer blocks the WS event loop.
- **ISSUE-061:** `get_market()` calls inside `_rest_refresh_stale()` are wrapped in `run_in_executor` per ticker. The 5-minute stale heal cycle no longer stalls the event loop.
- **ISSUE-070:** Exposure cap corrected — `evaluate_crypto_entry()` now uses `DAILY_CAP_RATIO` (0.70) instead of `CRYPTO_DAILY_CAP_PCT` (0.07). A comment notes the 10× increase from the prior cap and flags monitoring for the first 3 live days.

**Sprint 1 — WS eval dedup (ISSUE-015, ISSUE-060):** `_window_eval_lock = asyncio.Lock()` added. Both `_safe_eval_15m()` and `_check_and_fire_fallback()` check+set the `_window_evaluated` guard atomically inside this lock before evaluating. Prevents duplicate evaluations when WS and REST fallback fire for the same window within the same connection cycle.

#### handle_message() Routing

Processes only `type == 'ticker'` messages. Price conversion: WS sends dollar strings → cent integers.

- Every tick: `market_cache.update()` + `_safe_check_exits()` (background task)
- `KXBTC15M`, `KXETH15M`, `KXSOL15M`, etc. prefix → `_safe_eval_15m()` (15m entry evaluation) — **KXSOL15M added Sprint 4 (ISSUE-001)**
- `KXBTC`, `KXETH`, etc. prefix (NOT 15m) → `_safe_eval_hourly()` (daily/hourly band entry, runs in executor)
- The `elif` logic ensures 15m tickers are NOT double-evaluated by the hourly handler.
- All evaluation tasks are fire-and-forget (`asyncio.create_task`); feed yields every 100 messages.

#### Fallback Poll Loop

`_fallback_poll_loop()` runs as background task. Every 30 seconds:
1. Skip if `elapsed < 90s` or `remaining < 180s`
2. Acquire `_window_eval_lock`; skip if `guard_key in _window_evaluated` (atomic check, Sprint 1 fix)
3. REST-resolve ticker → `evaluate_crypto_15m_entry()`
4. Always mark `_window_evaluated[guard_key]` even on exception (prevents retry storms — see Known Issue 3.8)

#### Heartbeat

`_write_heartbeat()` writes `logs/ws_feed_heartbeat.json`:
```json
{"last_heartbeat": "<ISO>", "pid": <int>, "status": "running"}
```

---

### 3.4 settlement_checker.py — Batch Settlement Resolver

**Location:** `environments/demo/settlement_checker.py`  
**Scheduled:** Task Scheduler at 11:00 PM PDT, 8:00 AM PDT, and 6:00 AM PDT (3× daily).

#### load_all_unsettled() — Identifying Open Positions

FIFO accounting:
- Counts buy/open records per `(ticker, side)` key (chronological)
- Counts exit/settle records
- Skips first N buy legs (N = exit count). Remaining = unsettled.

#### check_settlements() — Resolution Logic

Result determination (priority order — updated Sprint 3 / ISSUE-028):
1. `market.result in ('yes', 'no')` → use directly
2. `market.status in ('settled', 'finalized')` → `yes_bid >= 99` → yes, else no
3. Market expired but result pending → `continue` (do not infer from bid alone)

**Removed (Sprint 3):** Steps 3 and 4 previously inferred settlement outcome from `yes_bid >= 99` or `yes_bid <= 1` without a confirmed `result` or `status`. This could produce phantom settlements on near-expiry contracts that hadn't resolved yet. Bid-only inference is now blocked — settlement requires a confirmed API `result` field or `status in ('settled', 'finalized')`.

#### compute_pnl()

**Fixed P1-2 (ISSUE-026, commit d3584bf):** `settlement_checker.py` now uses `exit_price=100` for wins (was 99). **Fixed P1-2 (ISSUE-027):** Loss formula updated from `-size_dollars` (cost-basis from `size_dollars` field) to computed cost-basis.

```python
if side_won:
    pnl = (100 - entry_price) * contracts / 100
else:
    pnl = -(entry_price * contracts / 100)  # cost-basis computed from entry_price × contracts
```

**API retry (Fixed P1-2 / ISSUE-110):** `settlement_checker` now retries market fetch on API error — 3 attempts, 1s/2s inter-attempt delays (exponential-style backoff).

**Settle record** includes: `trade_id`, `entry_date`, `settlement_result`, `pnl`, `entry_price`, `exit_price`, `contracts`, `size_dollars`, `hold_duration_hours`, `entry_edge`, `confidence`.

⚠️ **Two distinct settle record schemas exist:**
- **settlement_checker path (rich):** 10+ fields including `entry_date`, `hold_duration_hours`, `entry_edge`, `confidence`, `size_dollars`.
- **position_tracker `check_expired_positions()` path (sparse):** Lacks `entry_date`, `hold_duration_hours`, `entry_edge`, `confidence`, `size_dollars`. Has `timestamp`, `date`, `title`, `action_detail`, `source`, `module`.
Downstream readers must handle missing fields when consuming settle records from either path.

**Sprint 3 (ISSUE-023):** All settle writes from both paths now route through `logger.log_settle()` wrapper, which enforces dedup fingerprint.

**Sprint 3 (ISSUE-025):** `check_expired_positions()` now calls `_settle_record_exists(ticker, side)` (checks today + yesterday's trade log) before writing. If a settle record already exists, position is removed from tracker without writing a duplicate.

After each settlement: calls `backfill_outcome()` and `prediction_scorer.score_new_settlements()`.

---

### 3.5 market_cache.py — Shared Price Cache

**Location:** `agents/ruppert/data_analyst/market_cache.py`

⚠️ Values stored as **dollar fractions** (0.0–1.0), not cent integers. `get_market_price()` returns cent integers.

| Config | Value | Meaning |
|--------|-------|---------|
| `WS_CACHE_STALE_SECONDS` | 60 | Age threshold for stale flag |
| `WS_CACHE_PURGE_SECONDS` | 86400 | Age threshold for purge (24h) |

Thread-safe via `threading.Lock()`. Persists to `logs/price_cache.json` via atomic temp-file replace.

**API Surface:**

| Function | Returns |
|----------|---------|
| `update(ticker, bid, ask, source)` | None |
| `get_with_staleness(ticker)` | `(bid, ask, is_stale)` in dollar fractions |
| `get_market_price(ticker, fallback_client)` | `{yes_bid, yes_ask, no_bid, no_ask, source}` in cents |
| `purge_stale()` | None |
| `persist()` / `load()` | None |

---

### 3.6 circuit_breaker.py — CB State Management

**Location:** `agents/ruppert/trader/circuit_breaker.py`  
**State file:** `environments/demo/logs/circuit_breaker_state.json`

**Per-module state:** `consecutive_losses`, `last_window_ts`, `last_window_result`, `date`  
**Global state:** `net_loss_today`, `tripped`, `date`

**Auto-reset:** Day boundary is **PDT** (`America/Los_Angeles`). Module state resets automatically on new day.

**Trip conditions:**
- Per-module: `consecutive_losses >= N` (N=3 for 15m/1h, N=5 for daily). `ADVISORY=False` → hard stop.
- Global: `net_loss_today > capital * 0.05`. Fails closed if capital ≤ 0 or trade log unreadable.

**Atomic write:** `.tmp` → `os.replace()`. Full state file always written.

**Sprint 5 — File locking on read-modify-write (ISSUE-076 fix):** All read-modify-write operations — `increment_consecutive_losses()`, `reset_consecutive_losses()`, and `update_global_state()` — now use a `_rw_locked()` helper that acquires `portalocker.LOCK_EX` on the state file before reading and holds it through the write. Cold-start `FileNotFoundError` is handled with a `w+` fallback inside the lock. This eliminates the TOCTOU race where two processes could read the same state, both increment, and the second write would clobber the first increment.

**Sprint 5 — CB trip logging (ISSUE-047 fix):** When `increment_consecutive_losses()` causes the threshold to be reached, a `WARNING`-level log is emitted identifying the module, current count, and threshold (e.g. `"Circuit breaker tripped: crypto_dir_15m_BTC — 3/3 consecutive losses"`). Previously the trip was silent in the log.

**Update triggers:**
- `position_tracker._update_daily_cb()` — called after daily exits/settlements for `crypto_band_daily_*` and `crypto_threshold_daily_*` modules. Does NOT handle 15m modules (returns immediately for those).
- `post_trade_monitor._update_circuit_breaker_state()` — handles 15m CB increments/resets.
- Global CB state must be explicitly called by trading cycle — WS feed does NOT update it (see Known Issue 3.9).
- All CB read-modify-write ops now file-locked via portalocker (Sprint 5, ISSUE-076).

---

### 3.7 Known Issues — Exit Pipeline

| ID | Description | Severity |
|----|-------------|----------|
| ISSUE-X01 | ~~Double-settle race condition. Both `check_expired_positions()` and `settlement_checker` can process same position. No lock/coordination between paths.~~ **FIXED Sprint 3 (ISSUE-025):** `_settle_record_exists()` guard in `check_expired_positions()` prevents duplicate settle records. | ~~High~~ **Resolved** |
| ISSUE-X02 | ~~99c vs 100c discrepancy. `settlement_checker` uses 99c; `check_expired_positions` uses 100c. Systematic 1-cent-per-contract difference in reported win P&L.~~ **FIXED P1-2 (ISSUE-026, commit d3584bf):** `settlement_checker.py` now uses `exit_price=100` for wins. **FIXED P1-5 (ISSUE-098, commit 8a32658):** `position_monitor.py` win P&L formula also corrected (YES-win and NO-win paths). ✅ RESOLVED (P1) | ~~Medium~~ **Resolved** |
| ISSUE-X03 | ~~Tracker not updated by cycle exits. Cycle-entered positions not in tracker → no WS stop-losses, no gain exits. `settlement_checker` catches them eventually.~~ **FIXED Sprint 2 (ISSUE-031):** `remove_position()` now called in both exit paths of `run_position_check()` in `ruppert_cycle.py`. | ~~High~~ **Resolved** |
| ISSUE-X04 | ~~In-flight guard does not block threshold checks. Stop-loss in flight → threshold check still runs → second `execute_exit()` call (dedup guard catches it but generates warning).~~ **FIXED Sprint 1 Batch 2 (ISSUE-002):** `_exits_lock = asyncio.Lock()` wraps the check+add of `_exits_in_flight` atomically in `execute_exit()`. Race condition eliminated. | ~~Medium~~ **Resolved** |
| ISSUE-X05 | ~~Legacy NO position migration. Pre-migration positions exited before migration may have wrong entry_price in historical trade log records.~~ **FIXED Sprint 5 (ISSUE-042):** Migration block removed from `_load()`. NO `entry_price` now stored as-is. DS inserted 125 `exit_correction` records into trades_2026-04-02/03.jsonl to correct historical P&L. CB global state refreshed. | ~~Low~~ **Resolved** |
| ISSUE-X06 | `_write_off_logged` not cleared on WS reconnect. Same-process write-off suppression persists across reconnects. | Low |
| ISSUE-X07 | Recovery poll without `close_time` bypasses NO-side settlement guard. | Low |
| ISSUE-X08 | Fallback poll marks window evaluated on exception. Transient REST error → window permanently skipped for that connection cycle. | Medium |
| ISSUE-X09 | Global CB written separately from trading cycle. WS feed never calls `update_global_state()`. CB may lag behind reality. | High |

---

## 4. Analytics & Learning

_Source: `memory/agents/sysmap-section4-analytics.md`_

### 4.1 Overview

The analytics pipeline runs in three layers after each trade lifecycle:
1. **Scoring** — `prediction_scorer.py` joins buy records with settle/exit records → `scored_predictions.jsonl`
2. **Calibration** — `brier_tracker.py` logs predictions at entry, scores at resolution
3. **Optimization** — `optimizer.py` reads `scored_predictions.jsonl` and trade logs → proposals
4. **Audit** — `data_agent.py` runs after every scan cycle → validates + auto-repairs
5. **Synthesis** — `synthesizer.py` writes truth files from event logs
6. **Capital** — `capital.py` is single source of truth for all financial figures

---

### 4.2 prediction_scorer.py

**Location:** `environments/demo/prediction_scorer.py`  
**Trigger:** Called by `settlement_checker` after each settlement. Also runnable standalone.

**Join logic:**
```
buy_index = { (ticker, date): buy_rec }   # first buy/open per key
buy_index_by_ticker_side = { (ticker, side): buy_rec }   # fallback for overnight positions
for each settle/exit record:
    key = (ticker, date)
    if key in processed: skip  # idempotent dedup
    buy_rec = buy_index.get(key) or buy_index_by_ticker_side.get((ticker, settle_side))
    ...compose scored record...
```

**Fixed P1-3 (ISSUE-103):** Overnight positions (settlement date ≠ buy date) previously received `null` for `predicted_prob` due to failed date-keyed join. Now maintains secondary `(ticker, side)` fallback index. Warning logged on fallback use; `null` on no-match in either index.

`predicted_prob` priority: `noaa_prob` → `model_prob` → `market_prob`  
`outcome` = `settlement_result` string mapped to int (1=yes, 0=no)  
`brier_score` = `(outcome - predicted_prob)²`

**Output schema — `logs/scored_predictions.jsonl`:**

| Field | Type | Notes |
|---|---|---|
| `domain` | str\|None | e.g. "weather", "crypto" |
| `ticker` | str | Kalshi market ticker |
| `predicted_prob` | float\|None | 4 decimal places |
| `outcome` | int\|None | 0 or 1 |
| `brier_score` | float\|None | None if inputs missing |
| `edge` | float\|None | |
| `confidence` | float\|None | |
| `date` | str | YYYY-MM-DD |
| `settlement_date` | str | Same as date |
| `pnl` | float\|None | |

**Note:** `city` field is extracted internally but NOT included in output schema.

⚠️ `prediction_scorer.py` and `brier_tracker.py` write to the **same** `scored_predictions.jsonl` with **incompatible schemas** (see Known Issue 4.3).

---

### 4.3 brier_tracker.py

**Location:** `environments/demo/brier_tracker.py`  
**Mode:** Push model — called at entry (`log_prediction()`) and at resolution (`score_prediction()`).

**Files:** Resolved at function-call time via `_get_brier_paths()` lazy helper (**Fixed P1-3 / ISSUE-004:** module-level path constants removed; paths no longer hardcoded at import). Paths still resolve to `logs/predictions.jsonl` (entry log) and `logs/scored_predictions.jsonl` (scored output — shared with scorer) under the configured environment.

**Dedup guard (Fixed P1-3 / ISSUE-101):** `brier_tracker` maintains a `(ticker, date)` dedup key on the scoring side (`score_prediction()`). A ticker/date pair is only scored once. Previously, repeated settlement_checker runs could score the same prediction multiple times.

**`log_prediction()` entry schema (→ `predictions.jsonl`):**

| Field | Type |
|---|---|
| `ts` | str (ISO) |
| `domain` | str |
| `ticker` | str |
| `predicted_prob` | float (4dp) |
| `market_price` | float (4dp) |
| `edge` | float (4dp) |
| `side` | str |
| `outcome` | None (placeholder) |
| `brier_score` | None (placeholder) |
| `...extra` | optional |

**`score_prediction()` output schema (→ `scored_predictions.jsonl`):** All entry fields + `outcome` (0/1), `brier_score`, `resolved_at`.

**`get_domain_brier_summary()` output:**
```python
{
  'weather': {
    'count': int,         # scored predictions
    'brier_mean': float,  # mean Brier score
    'threshold_pct': int, # count/30 * 100 (archived — autoresearch pipeline removed)
  }
}
```

**Key difference from `prediction_scorer.py`:** Push vs pull; different schemas; different source files; brier_tracker schema has `ts`, `market_price`, `edge`, `side`, `resolved_at` absent from scorer records.

---

### 4.4 optimizer.py

**Location:** `agents/ruppert/strategist/optimizer.py`  
**Trigger:** Manual/scheduled standalone. NOT called in post-scan loop.

**Fixed P1-3 (ISSUE-005, commit 2e870f6):** Reads from correct path `(LOGS_DIR / "trades").glob("trades_*.jsonl")`. All 6 analysis dimensions now read live trades correctly.

**Six analysis dimensions (Bonferroni N=6, threshold ≈ 0.0083):**

| Dimension | Flag Threshold | Note |
|---|---|---|
| Win rate by module | < 60% | |
| Confidence tier analysis | < 60% per tier | ⚠️ Meaningless for 15m records — `confidence` is a z-score (0–3 range), not a 0–1 probability. Tier thresholds (0.25/0.40/0.50…) are probability-scale. All 15m trades land in incorrect tiers. |
| Exit timing | avg hold > 12h | **Fixed P1-3 (ISSUE-046):** was computing against nonexistent `exit_timestamp` field. Now uses buy/exit join (`buy_index` parameter); `count = len(pnls)` correctly reflects paired trades. |
| Brier score (calibration) | > 0.25 | |
| Daily cap utilization | < 30% | **Fixed P1-3 (ISSUE-041):** was double-counting trades (buy + settle both summed). Now filters to `action in ('buy', 'open')` before summing deployed capital. |
| Sizing review | avg size > $40 | |

**Proposal types:** `WIN_RATE`, `CONFIDENCE_TIER`, `CALIBRATION`, `EXIT`, `SIZING`, `CAP_UTILIZATION`  
**Output:** `logs/optimizer_proposals_YYYY-MM-DD.md`

**Domain eligibility:** ≥ 30 scored trades. `run_domain_experiments()` is a **no-op placeholder** (see Known Issue 4.8).

---

### 4.5 data_agent.py

**Location:** `agents/ruppert/data_scientist/data_agent.py`  
**Triggers:** After every scan cycle (`run_post_scan_audit()`), once daily historical audit, or manually.

**Always-run checks (every cycle):**

| Check | Auto-Fix |
|---|---|
| Duplicate trade IDs | `_cleanup_duplicates()` — removes duplicates, keeps first. **Sprint 2 (ISSUE-056):** `_PROTECTED_ACTIONS = {'exit', 'settle', 'exit_correction'}` — records with these actions are never deleted even if a duplicate `trade_id` exists. Uses streaming pattern (reads all, writes back non-duplicates). Logs preserved duplicates via `log_activity()`. |
| Missing required fields (`ticker`, `side`, `size_dollars`, `module`, `ts`/`timestamp`) | `_mark_invalid()` — adds `_invalid: true` + reason |
| Dry run mismatch (live order in demo) | `_mark_invalid()` + immediate Telegram alert (4h dedup) |
| Module/ticker mismatch | `_fix_module()` — overwrites module, preserves old in `_module_corrected_from` |
| Position tracker drift (orphans + missing) | Orphans: `_remove_tracker_orphans()`. Missing: `_register_missing_positions()` via `add_position()`. **Sprint 2 (ISSUE-055):** `_has_close_record(ticker, side)` guard runs before `add_position()` — if an exit or settle record already exists for this position, it is NOT re-added to the tracker (prevents settled positions from being resurrected). |

⚠️ **Module mismatch auto-fix** maps all `KXHIGH*` to `'weather_band'` — cannot distinguish `weather_threshold` (see Known Issue 4.5).  
⚠️ **Missing-position reconstruction** computes exit thresholds from potentially wrong `entry_price` — can cause wrong stop-losses and WS crashes (known historical issue).

**Fixed P1-2 (ISSUE-102):** `TICKER_MODULE_MAP` and `_cap_map` now include entries for `KXXRPD` (→ `crypto_threshold_daily_xrp`) and `KXDOGED` (→ `crypto_threshold_daily_doge`). Also includes `KXBTCD` mapping. Previously missing — module classification and cap checking were skipped for these tickers.

**Full-cycle-only checks:**
- Entry price outside spread → `_flag_trade()` (adds `_price_anomaly: true`)
- Daily cap violations → Telegram alert (no auto-fix)
- Decision log orphans (non-SKIP decisions with no matching trade)
- Dashboard consistency check (if `localhost:8765` reachable)

**Post-scan monitors:**
- `check_ws_stability()` — ≥5 disconnects in 10 min → alert to `pending_alerts.json`
- `check_15m_entry_drought()` — < 10 decisions in 1h → stalled warning; 0 ENTER in 4h → drought warning

**State:** `logs/data_audit_state.json`. Alert dedup: 4-hour window via MD5 hash key.

---

### 4.6 synthesizer.py

**Location:** `agents/ruppert/data_scientist/synthesizer.py`  
**Trigger:** Called by `data_agent.py` after each scan cycle. Data Scientist is sole writer of `logs/truth/` files.

**Truth files written:**

| File | Source | Content |
|---|---|---|
| `logs/truth/pnl_cache.json` | Trade logs (NOT event log) | `{closed_pnl, open_pnl}` |
| `logs/truth/pending_alerts.json` | ALERT_CANDIDATE events + `data_health_check._push_alert()` (**Fixed P1-5 / ISSUE-121**) | List of `{level, message, ticker, pnl, timestamp}` |
| `logs/truth/state.json` | Most recent STATE_UPDATE event | `{traded_tickers, last_cycle_ts, last_cycle_mode}` |
| `logs/truth/pending_optimizer_review.json` | OPTIMIZER_REVIEW_NEEDED event | `{date, losses, total_loss}` |

⚠️ **`pnl_cache.json` comment/code divergence** — docstring says it was deleted; function still writes it. `capital.py` correctly bypasses it (see Known Issue 4.4).

---

### 4.7 capital.py

**Location:** `agents/ruppert/data_scientist/capital.py`

**`get_capital()` logic:**
1. LIVE mode: `KalshiClient().get_balance()` (API dollars)
2. Demo mode: `sum(demo_deposits.jsonl amounts) + compute_closed_pnl_from_logs()`
3. If deposits ≤ 0: **Sprint 2 (ISSUE-051):** sends Telegram alert + `log_activity()`, with 4-hour dedup via `logs/capital_fallback_alert.json`. Error summary capped at 500 chars. Then returns `$10,000.00`. Previously this was a silent `logger.warning()` only (see Known Issue 4.6 — now resolved).
4. On **any exception** (import failure, path error, etc.) in `get_capital()`: same Telegram alert + 4-hour dedup + returns `$10,000.00`.

**Key functions:**

| Function | Returns |
|----------|---------|
| `get_capital()` | Total capital (deposits + realized P&L or API balance) |
| `get_buying_power(deployed)` | `max(0, capital - deployed)` |
| `get_daily_exposure()` | Delegates to `logger.get_daily_exposure()` |
| `get_pnl()` | `{closed: float, open: 0.0, total: float}` |

**Why not `pnl_cache.json`:** Capital reads `compute_closed_pnl_from_logs()` directly to avoid synthesizer lag — keeps "Account Value" consistent with the dashboard Closed P&L panel.

---

### 4.8 Analytics Data Flow

```
Trade placed
    │
    ├─► brier_tracker.log_prediction()  ─────────────────────────► logs/predictions.jsonl
    └─► logger.log_trade()  ──────────────────────────────────────► logs/trades/trades_YYYY-MM-DD.jsonl
                                                                          │
        ┌─────────────────────────────────────────────────────────────────┘
        │
        ▼ (after each scan cycle)
    data_agent.run_post_scan_audit()
        │ checks + auto-fixes
        └── synthesizer.run_synthesis()
                ├── pnl_cache.json
                ├── pending_alerts.json
                ├── state.json
                └── pending_optimizer_review.json

Contract settles
    ├─► brier_tracker.score_prediction()  ───────────────────────► logs/scored_predictions.jsonl
    └─► settlement_checker
            └── prediction_scorer.score_new_settlements()  ──────► logs/scored_predictions.jsonl

Optimizer (manual/scheduled)
    └── reads logs/trades/trades_*.jsonl  ~~[BUG: wrong path — reads logs/ not logs/trades/]~~ **Fixed P1-3 (ISSUE-005)**
        reads logs/scored_predictions.jsonl
        writes logs/optimizer_proposals_YYYY-MM-DD.md
```

---

### 4.9 Known Issues — Analytics

| ID | Description | Severity |
|----|-------------|----------|
| ISSUE-A01 | ~~Optimizer reads wrong path — `LOGS_DIR.glob("trades_*.jsonl")` scans `logs/` directly, not `logs/trades/`. Reads 0 current trades. All 6 analysis dimensions operate on empty or archive-only data.~~ **FIXED Sprint P1-3 (ISSUE-005, commit 2e870f6):** `LOGS_DIR.glob()` → `(LOGS_DIR / "trades").glob()`. Optimizer now reads live trades correctly. ✅ RESOLVED (P1) | ~~Critical~~ **Resolved** |
| ISSUE-A02 | NO-side Brier score inverted. `prediction_scorer.py` maps YES settlement → `outcome=1` regardless of trade side. NO-side trades have Brier scores computed against wrong probability polarity. | High |
| ISSUE-A03 | Schema conflict in `scored_predictions.jsonl`. Both `prediction_scorer.py` and `brier_tracker.py` write to same file with incompatible schemas. Readers must handle missing fields. | High |
| ISSUE-A04 | `synthesize_pnl_cache()` comment/code divergence. Docstring says deleted; function still writes. Downstream consumers may read stale file. | Low |
| ISSUE-A05 | Module mismatch auto-fix uses imprecise `KXHIGH*` mapping → may write `'weather_band'` on `'weather_threshold'` records. Corrupts per-submodule analytics. | Medium |
| ISSUE-A06 | ~~`$10,000` capital fallback is silent. Missing/empty `demo_deposits.jsonl` → all sizing and cap calculations use fictional $10k without alerting David.~~ **FIXED Sprint 2 (ISSUE-051):** Fallback now sends Telegram alert + `log_activity()` with 4-hour dedup via `logs/capital_fallback_alert.json`. Error message capped at 500 chars. | ~~High~~ **Resolved** |
| ISSUE-A07 | `analyze_brier_score()` excludes records where `win_prob` and `noaa_prob` both absent. Silent exclusion understates sample size. | Low |
| ISSUE-A08 | `run_domain_experiments()` is a no-op. No actual optimization runs. | Medium |
| ISSUE-A09 | `check_daily_cap_violations()` in `data_agent.py` is dead code. All per-module daily caps were removed 2026-03-31. The function still exists but checks will never fire. | Low |

---

## 5. Infrastructure & Configuration

_Source: `memory/agents/sysmap-section5-infrastructure.md`_

### 5.1 config.py — Key Constants

**Location:** `environments/demo/config.py`

#### Mode Detection
- `DRY_RUN` — derived from `mode.json` at import. Requires restart to reflect changes.
- `_MODE_FILE` — `environments/demo/mode.json`

#### Position Sizing

| Constant | Value | Meaning |
|----------|-------|---------|
| `MAX_POSITION_PCT` | 0.01 | 1% of capital per trade |
| `CRYPTO_15M_DIR_HARD_CAP_USD` | $100 | Per-trade hard cap for 15m direction |
| `CRYPTO_15M_DIR_MIN_POSITION_USD` | $5 | Minimum for 15m direction |
| `CRYPTO_15M_WINDOW_CAP_PCT` | 0.04 | 4% of capital per 15-min window |
| `CRYPTO_1D_DAILY_CAP_PCT` | 0.15 | 15% of capital/day for crypto_1d |
| `CRYPTO_1D_WINDOW_CAP_PCT` | 0.05 | 5% per crypto_1d entry |
| `CRYPTO_1D_PER_ASSET_CAP_PCT` | 0.03 | 3% per asset per day |
| `CRYPTO_1D_MAX_POSITION_USD` | $200 | Hard cap per crypto_1d entry |
| `DAILY_CAP_RATIO` | 0.70 | Max fraction of capital deployable per day |
| `TTYPE_PER_TRADE_SIZE` | $50 | Fixed size for weather T-type trades |
| `MIN_VIABLE_TRADE_USD` | $5 | Absolute minimum trade floor |
| `CAPITAL_FALLBACK` | $10,000 | Fallback when API unavailable |

#### Risk / Edge Thresholds

| Constant | Value | Meaning |
|----------|-------|---------|
| `MIN_EDGE_THRESHOLD` | 0.12 | General min edge (weather/econ) |
| `CRYPTO_MIN_EDGE_THRESHOLD` | 0.12 | Crypto module min edge |
| `LOSS_CIRCUIT_BREAKER_PCT` | 0.05 | Halt all trading if daily losses > 5% of capital |
| `GEO_MIN_EDGE_THRESHOLD` | 0.15 | Geo min edge |
| `ECON_MIN_EDGE` | 0.12 | Econ min edge |
| `CRYPTO_15M_MIN_EDGE` | 0.02 | Data collection: 2% (prod: 0.05+) |
| `CRYPTO_1D_MIN_EDGE` | 0.08 | Primary crypto_1d window |
| `CRYPTO_1D_SECONDARY_MIN_EDGE` | 0.12 | Secondary crypto_1d window |

#### Auto-Trade Settings (Current State)

| Constant | Value | Status |
|----------|-------|--------|
| `WEATHER_AUTO_TRADE` | False | **HALTED 2026-04-01** |
| `CRYPTO_AUTO_TRADE` | True | Active |
| `GEO_AUTO_TRADE` | False | **HALTED 2026-04-01** |
| `ECON_AUTO_TRADE` | False | **HALTED 2026-04-01** |

#### Circuit Breakers

| Constant | Value | Meaning |
|----------|-------|---------|
| `LOSS_CIRCUIT_BREAKER_PCT` | 0.05 | 5% daily realized loss → halt all |
| `CRYPTO_15M_CIRCUIT_BREAKER_N` | 3 | Consecutive 15m losses before halt |
| `CRYPTO_15M_CIRCUIT_BREAKER_ADVISORY` | False | Hard stop |
| `CRYPTO_1H_CIRCUIT_BREAKER_N` | 3 | 1h CB |
| `CRYPTO_DAILY_CIRCUIT_BREAKER_N` | 5 | Daily CB |
| `CRYPTO_15M_DIR_DAILY_BACKSTOP_ENABLED` | False | Phase 2: disabled |

#### Stop-Loss Constants — 15m Direction

| Constant | Value |
|----------|-------|
| `STOP_BRACKET_EARLY` | 180s |
| `STOP_BRACKET_MID` | 300s |
| `STOP_BRACKET_LATE` | 480s |
| `STOP_GUARD_EARLY_PRIMARY` | 480s |
| `STOP_GUARD_MID_PRIMARY` | 300s |
| `STOP_GUARD_LATE_PRIMARY` | 180s |
| `STOP_GUARD_SECONDARY` | 90s |
| `STOP_PRICE_CATASTROPHIC` | 0.20 (20% of entry) |
| `STOP_PRICE_SEVERE` | 0.30 |
| `STOP_PRICE_TERMINAL` | 0.40 |
| `STOP_TIME_SEVERE` | 300s (5 min) |
| `STOP_TIME_TERMINAL` | 210s (3.5 min) |
| `STOP_LEGACY_ENTRY_SECS_DEFAULT` | 120s | Default `entry_secs_in_window` for legacy positions lacking the field — places them in the "< 3 min" stop bracket (480s guard). Added P1-5 (ISSUE-045, commit 8a32658). |

#### Stop-Loss Constants — Daily Positions

| Constant | Value |
|----------|-------|
| `DAILY_STOP_ENTRY_GUARD_SECS` | 1800s (30 min) |
| `DAILY_STOP_WRITE_OFF_TIME_SECS` | 1200s (20 min) |
| `DAILY_STOP_CATASTROPHIC_PCT` | 0.15 |
| `DAILY_STOP_CATASTROPHIC_ABS_CENTS` | 2c |
| `DAILY_STOP_SEVERE_PCT` | 0.25 |
| `DAILY_STOP_SEVERE_TIME_SECS` | 3600s (1h) |
| `DAILY_STOP_TERMINAL_PCT` | 0.30 |
| `DAILY_STOP_TERMINAL_TIME_SECS` | 1200s (20 min) |

#### Exit Thresholds

| Constant | Value | Meaning |
|----------|-------|---------|
| `EXIT_95C_THRESHOLD` | 95 | Auto-exit if bid ≥ 95c |
| `EXIT_GAIN_PCT` | 0.90 | Phase 2: exit at 90% of max upside (was 0.70) |
| `SETTLEMENT_GUARD_WINDOW_SECS` | 90 | Verify via REST before phantom-win exit |

#### Per-Module Minimum Confidence (`MIN_CONFIDENCE` dict)

| Module | Min Confidence |
|--------|---------------|
| `weather_band`, `weather_threshold` | 0.25 |
| `crypto_band_daily_*` | 0.50 |
| `crypto_threshold_daily_*` | 0.50 |
| `crypto_dir_15m_*` | 0.40 (Phase 2; was 0.50) |
| `econ_*` | 0.55 |
| `geo` | 0.50 |

#### WS-First Architecture

| Constant | Value |
|----------|-------|
| `WS_ACTIVE_SERIES` | 45+ ticker prefixes |
| `WS_CACHE_STALE_SECONDS` | 60s |
| `WS_CACHE_PURGE_SECONDS` | 86400s (24h) |

---

### 5.2 env_config.py — Environment Isolation

**Location:** `agents/ruppert/env_config.py`

**Environment resolution:** `RUPPERT_ENV` env var, default `'demo'`.

**Path dictionary (`get_paths()`):**

| Key | Resolves to |
|-----|-------------|
| `root` | `environments/{env}/` |
| `logs` | `environments/{env}/logs/` |
| `trades` | `environments/{env}/logs/trades/` |
| `truth` | `environments/{env}/logs/truth/` |
| `raw` | `environments/{env}/logs/raw/` |
| `reports` | `environments/{env}/reports/` |
| `secrets` | `workspace/secrets/` (shared) |
| `audits` | `environments/{env}/logs/audits/` |
| `proposals` | `environments/{env}/logs/proposals/` |
| `memory` | `environments/{env}/memory/` |
| `config` | `environments/{env}/config/` |
| `specs` | `environments/{env}/specs/` |
| `mode_file` | `environments/{env}/mode.json` |

**Two-layer live gate:**
- Layer 1: `RUPPERT_ENV` environment variable must be set to `'live'` (defaults to `'demo'`). This is the env var, **not** `demo/mode.json`.
- Layer 2: `environments/live/mode.json → {"enabled": true}` (re-read live on every call — no restart needed).
Safety default: unknown environment → `is_dry_run() = True`. Additionally, `execute_opportunity()` in trader.py calls `require_live_enabled()` as a runtime defense-in-depth check before placing any live order.

---

### 5.3 mode.json

```json
{"mode": "demo"}
```

Read once at import time by `config.py`. Changes require restart.

---

### 5.4 Watchdog — ws_feed_watchdog.py

**Two copies exist:**
- **Active:** `scripts/ws_feed_watchdog.py` — `CHECK_INTERVAL=60s`, `HEARTBEAT_STALE=180s`
- **Stale:** `environments/demo/scripts/ws_feed_watchdog.py` — different values (300s/600s) ← **DO NOT USE**

**Restart logic:** Reads `ws_feed_heartbeat.json` every 60s. If stale or missing → 2s delay → spawn new ws_feed process (Windows flags: `CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS`). Logs to `logs/watchdog.log`.

~~**⚠️ Double-spawn issue:** Two Task Scheduler tasks both launch ws_feed at boot. At boot, watchdog may see stale heartbeat (ws_feed just started, hasn't written yet) and spawn a second instance. Two ws_feed processes compete for the same WS connection.~~ **FIXED Sprint 1 (ISSUE-049, commit ceba350):** `kill_existing_ws_feed()` is now called before every spawn in `ws_feed_watchdog.py`. This terminates any existing ws_feed process before launching a new one, eliminating the double-spawn race at boot. **Status: Resolved.**

---

### 5.5 Task Scheduler — All Scheduled Tasks

| Task Name | Schedule | Command | State | Purpose |
|-----------|----------|---------|-------|---------|
| `Ruppert-Crypto-8AM` through `8PM` (7 tasks) | Daily 08:00–20:00 PDT (every 2h) | `ruppert_cycle.py crypto_only` | Ready | 15m crypto scan cycles |
| `Ruppert-Crypto-930AM` | Daily 09:30 PDT | `ruppert_cycle.py crypto_only` | Ready | Additional 15m crypto scan |
| `Ruppert-Crypto1D` | Daily 06:30 + 10:30 PDT | `ruppert_cycle crypto_1d` | Ready | Daily crypto above/below |
| `Ruppert-Demo-7AM` | Daily 07:00 PDT | `ruppert_cycle.py full` | **Disabled** | Full scan (all modules) |
| `Ruppert-Demo-3PM` | Daily 15:00 PDT | `ruppert_cycle.py full` | **Disabled** | Full scan |
| `Ruppert-Demo-10PM` | Daily 22:00 PDT | `ruppert_cycle.py check` | **Disabled** | Position check / settlement review |
| `Ruppert-Weather-7PM` | Daily 19:00 PDT | `ruppert_cycle.py weather_only` | **Disabled** | Weather scan |
| `Ruppert-Econ-Prescan` | Daily 05:00 PDT | `ruppert_cycle.py econ_prescan` | **Disabled** | Econ prescan |
| `Ruppert-PostTrade-Monitor` | Every 30 min (starts 06:00) | `post_trade_monitor` | **Disabled** | Position monitoring, 15m CB updates |
| `Ruppert-SettlementChecker` | Daily 11:00 PM + 8:00 AM + 6:00 AM PDT | `settlement_checker` | Ready | Verify settled positions (3× daily) |
| `Ruppert-MidnightRestart` | Daily 00:00 PDT | re-enables disabled tasks + restarts ws_feed/dashboard | Ready | Daily system reset — re-enables Disabled tasks |
| `Ruppert-DailyHealthCheck` | Daily 06:45 PDT | `data_health_check` | Ready | Data health audit |
| `Ruppert-DailyIntegrityCheck` | Daily 06:50 PDT | `data_integrity_check.py` | Ready | Data integrity check |
| `Ruppert-DailyProgressReport` | Daily 20:00 PDT | `brief_generator` | Ready | Daily P&L brief to David |
| `Ruppert-Research-Weekly` | Fridays 08:00 PDT | `research_agent` | Ready | Weekly research scan |
| `Ruppert-SportsOdds` | Hourly 08:00–20:00 PDT (13 triggers) | `sports_odds_collector.py` | Ready | Sports odds data collection |
| `Ruppert-WS-Persistent` | Boot (1-min delay) + Daily 00:01 | `ws_feed` | Ready | Start WebSocket feed |
| `Ruppert-WS-Watchdog` | Boot | `ws_feed_watchdog` | Running | Monitor + restart ws_feed |
| `RuppertDashboard` | User logon | `start_dashboard.ps1` | Ready | Launch dashboard (hidden window) |

**Note on Disabled tasks:** `Ruppert-Demo-7AM`, `Ruppert-Demo-3PM`, `Ruppert-Demo-10PM`, `Ruppert-Weather-7PM`, `Ruppert-Econ-Prescan`, and `Ruppert-PostTrade-Monitor` are currently **Disabled** in Task Scheduler. `Ruppert-MidnightRestart` re-enables them at 00:00 PDT each day as part of the daily system reset cycle. The "Disabled" state reflects the status set at the end of each prior day's run.

**All tasks run from:** `C:\Users\David Wu\.openclaw\workspace`  
**Python path:** `C:\Users\David Wu\AppData\Local\Programs\Python\Python312\python.exe`

---

### 5.6 Dead Config Constants

The following were **removed in Phase 2 (2026-03-31)** — all per-module daily caps commented out. The circuit breaker (`LOSS_CIRCUIT_BREAKER_PCT = 0.05`) is now the sole daily hard stop:

Removed: `WEATHER_DAILY_CAP_PCT`, `ECON_DAILY_CAP_PCT`, `FED_DAILY_CAP_PCT`, `CRYPTO_15M_DAILY_CAP_PCT`, `WEATHER_BAND_DAILY_CAP_PCT`, `WEATHER_THRESHOLD_DAILY_CAP_PCT`, `CRYPTO_1H_BAND_DAILY_CAP_PCT`, `CRYPTO_1H_DIR_DAILY_CAP_PCT`, `CRYPTO_15M_DIR_DAILY_CAP_PCT`, `ECON_CPI_DAILY_CAP_PCT`, `ECON_UNEMPLOYMENT_DAILY_CAP_PCT`, `ECON_FED_RATE_DAILY_CAP_PCT`, `ECON_RECESSION_DAILY_CAP_PCT`, `GEO_DAILY_CAP_PCT`

**Not actually dead** (despite being labeled legacy):
- `CRYPTO_DAILY_CAP_PCT = 0.07` — has 3 active usages: `crypto_band_daily.py` (daily cap fallback), `position_monitor.py`, and `optimizer.py`.
- `CHECK_INTERVAL_HOURS = 6` — has 1 active usage in `main.py` `run_loop()` for standalone/manual loop mode.

**`check_daily_cap_violations()` in `data_agent.py`** — this function is now **dead code**. The per-module daily caps it checks were all removed on 2026-03-31. The function still exists in the codebase but its checks will never fire. See §7 ISSUE-A09.

---

### 5.7 Known Issues — Infrastructure

| ID | Description | Severity |
|----|-------------|----------|
| ISSUE-I01 | Watchdog double-spawn at boot. Two Task Scheduler tasks launch ws_feed. Watchdog may see stale heartbeat and spawn second instance. Two ws_feed processes compete for WS connection. Unresolved. | High |
| ISSUE-I02 | Stale watchdog copy at `environments/demo/scripts/ws_feed_watchdog.py` with different constants (300s/600s vs 60s/180s). Risk of confusion. | Low |
| ISSUE-I03 | `mode.json` changes require process restart. No hot-reload. | Low |
| ISSUE-I04 | `Ruppert-PostTrade-Monitor` (every 30 min) may overlap with WS exit path. `post_trade_monitor` uses `acquire_exit_lock()` but `position_tracker.py` (used by WS feed) does NOT check this lock. Exit locking is asymmetric — `post_trade_monitor` respects it; WS feed does not. Dedup guard in position_tracker is the primary protection. | Medium |

---

## 6. Dashboard & Reporting

_Source: `memory/agents/sysmap-section6-dashboard.md`_

### 6.1 Dashboard Architecture

- **Technology:** FastAPI + uvicorn on port 8765
- **Mode:** Always DEMO — read-only. Mode switching removed in Phase 4.
- **Data sources:** Trade log files in `logs/trades/` + market price cache. No live Kalshi REST calls in DEMO mode.
- **Price cache:** `market_cache` module loaded at startup, refreshed every 60s by background daemon thread.
- **Response caching:** 30s in-process cache for `/api/state`, `/api/pnl`, `/api/positions/active`.
- **Fixed P1-4 (ISSUE-072):** 19 bare `except: pass` blocks replaced with `except Exception as e` with proper logging. `_cache_reload_loop()` is now guarded. Previously, many endpoint failures were silently discarded.

---

### 6.2 API Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/` | GET | Serves `dashboard/templates/index.html` |
| `/api/summary` | GET | Quick stats: entry count, unique positions, exposure totals |
| `/api/account` | GET | Capital + deployment split (bot vs manual) |
| `/api/mode` | GET | Always `{"mode": "demo"}` |
| `/api/mode` | POST | No-op — returns `{"mode": "demo", "ok": True}` |
| `/api/deposits` | GET | Deposit records + running total from `demo_deposits.jsonl` |
| `/api/deposits` | POST | Read-only in Phase 4 — logs DEPOSIT_ADDED event only |
| `/api/trades` | GET | Closed positions table (tickers with exit/settle records) |
| `/api/trades/today` | GET | Raw records from today's trade log |
| `/api/positions/active` | GET | Open (not exited/settled) positions with current prices. **Fixed P1-4 (ISSUE-019):** Previously crashed with `UnboundLocalError` — `side` variable was assigned in a conditional branch; now assigned as first statement in loop body. |
| `/api/positions/prices` | GET | Live orderbook prices from market cache only (no REST fallback) |
| `/api/positions/status` | GET | Market status per ticker (WS cache presence) |
| `/api/kalshi/weather` | GET | Weather scan cache (< 4h old) from `logs/weather_scan.jsonl` |
| `/api/scout/geo` | GET | Geo scan today from `logs/geopolitical_scanner.jsonl` |
| `/api/crypto/15m_summary` | GET | Today's 15m decisions summary from `logs/decisions_15m.jsonl` |
| `/api/crypto/scan` | GET | Crypto scan summary: prices + smart money + opportunities |
| `/api/sports` | GET | Sports odds gaps from `logs/sports_odds_log.jsonl` |
| `/api/pnl` | GET | Full P&L: open (unrealized) + closed (realized), per-module breakdown, time-period bucketing |
| `/api/state` | GET | Single snapshot: account + positions + module stats + smart money |

---

### 6.3 Capital Display

**Account Value (frontend):**
```
Account Value = STARTING_CAPITAL + Open P&L + Closed P&L
```
⚠️ In LIVE mode, Kalshi API balance already reflects open positions — frontend should remove `open_pnl` addition (currently does not).

**Starting Capital** (DEMO): `sum(demo_deposits.jsonl) + compute_closed_pnl_from_logs()`  
**Buying Power:** `max(0, starting_capital − total_deployed)`

**Open P&L (unrealized):** Computed from market cache only. If WS feed is down → open P&L shows $0 (no staleness indicator in `/api/pnl` or `/api/state`).

**Closed P&L — `compute_closed_pnl_from_logs()` is the canonical source:**
- Sums `pnl` from all `exit` + `settle` records
- Sums `pnl_correction` from all `exit_correction` records
- Uses mtime-based in-memory cache (recomputes only when trade files change)

---

### 6.4 Module Breakdown and Win Rate

**`classify_module(src, ticker)`** — single source of truth (in `logger.py`), imported by `api.py`.

**Display buckets (`_stat_bucket()`):**

| Module prefix | Display bucket |
|---|---|
| `crypto_dir_15m*` | `crypto_dir_15m` |
| `crypto_threshold_daily*` | `crypto_threshold_daily` |
| `crypto_band_daily*` | `crypto_band_daily` |
| `crypto*` (other) | `crypto` |
| all others | `other` |

**Win rate formula:**
```
win_rate = round(wins / trade_count * 100, 1)
```
- `wins` = count of closed trades where `pnl > 0`
- Returns `None` (not 0%) when `trade_count = 0`
- `exit_correction` decrements `wins` when `logged_pnl > 0` (phantom win reversal)
- **Fixed P1-4 (ISSUE-066):** `closed_win_rate` is now keyed on `trade_id` with `(ticker, side)` fallback. Previously used ticker-level dedup (last close per ticker), which could undercount multi-leg positions. Each individual close record is now counted.

**`compute_module_closed_stats_from_logs()` — canonical path for module stats.** Both `/api/pnl` and `_build_state()` run their own accumulation loops then **override** with canonical values from this function (resolves prior ~$710 discrepancy from ticker-deduplication differences).

---

### 6.5 brief_generator.py (CEO Daily Brief)

**Location:** `agents/ruppert/ceo/brief_generator.py`  
**Schedule:** Daily 20:00 PDT via Task Scheduler  
**Role boundary:** `CEO_ALLOWED_TASKS` enforced. Trading-only tasks only.

**Data sources:** `compute_closed_pnl_from_logs()`, `get_capital()`, 7-day trade log scan, `logs/raw/events_YYYY-MM-DD.jsonl`, `logs/truth/pending_alerts.json`, `logs/truth/opportunities_backlog.json`

**⚠️ Two conflicting P&L numbers in the brief:**
- `💰 P&L Today:` → `_compute_pnl_from_trades(today_trades)` — today's file only, reads `pnl` field from exit_correction (also falls back to `realized_pnl` for older records)
- `Closed P&L (truth file):` → `compute_closed_pnl_from_logs()` — all-time canonical, reads `pnl_correction` field from exit_correction

These serve different purposes but can show different numbers without explanation. Three field names are tried across the two methods: `pnl`, `pnl_correction`, and `realized_pnl` (legacy fallback).

**Markdown brief structure:**
```
# 📊 Ruppert Daily Brief — YYYY-MM-DD
## 💰 P&L Summary
## 📈 Open Positions  (7-day lookback only — multi-week positions appear as closed)
## 🔧 Module Performance (Today)
## 🔄 Scan Activity
## ✅ Settlements Today
## 🚨 Pending Alerts
## ⛔ Circuit Breaker
## ⚠️ Anomalies Detected
## ❌ Trade Failures
## 🔬 Research Pipeline
```

**Output:** `reports/daily_brief_YYYY-MM-DD.md` + Telegram message.

---

### 6.6 daily_progress_report.py

**Status: DEPRECATED** — shim only since Phase 5 (2026-03-28). Delegates to `brief_generator.main()`. Falls back to legacy report reading `logs/truth/pnl_cache.json` (stale truth file). Task Scheduler entry should point directly to `brief_generator.py`.

---

### 6.7 Known Issues — Dashboard & Reporting

| ID | Description | Severity |
|----|-------------|----------|
| ISSUE-D01 | ~~Fake P&L chart (two-point series). `points` array hardcoded to 2 data points: start date `'2026-03-10'` and today. Not a real per-day cumulative series.~~ **FIXED P1-4/P1-5 (ISSUE-063/CLEANUP-063):** `pnl_by_day` accumulation, hardcoded `points` build block, and `"points": points` key all removed from `dashboard/api.py`. Chart endpoint no longer returns this data. ✅ RESOLVED (P1) | ~~Medium~~ **Resolved** |
| ISSUE-D02 | ~~`BOT_SRC` missing `ws_*` sources in `/api/pnl`. WS-originated trades (`ws_crypto` etc.) classified as neither bot nor manual → underreports deployed capital.~~ **FIXED P1-4 (ISSUE-064):** `_is_auto()`/`_is_manual()` promoted to module scope in `dashboard/api.py`; now correctly covers `ws_*` and `crypto_15m` sources. ✅ RESOLVED (P1) | ~~Medium~~ **Resolved** |
| ISSUE-D03 | ~~Settled positions showing as open. `is_settled_ticker()` may return False for non-standard tickers or near-midnight EDT comparison edge cases.~~ **FIXED P1-4 (ISSUE-065):** `exited` set in `/api/positions/active` now includes both `exit` and `settle` action records. Settled positions no longer appear as open. ✅ RESOLVED (P1) | ~~Medium~~ **Resolved** |
| ISSUE-D04 | `_build_state()` vs `/api/pnl` P&L accumulation duplication. Bug fixes must be applied in both places. | Medium |
| ISSUE-D05 | ~~`AUTO_SOURCES` / `MANUAL_SOURCES` undefined in `get_account()`. May raise `NameError` or return wrong bot/manual trade counts.~~ **FIXED P1-4 (ISSUE-018):** Replaced with `_is_auto()`/`_is_manual()` module-scope helper functions in `dashboard/api.py`. ✅ RESOLVED (P1) | ~~High~~ **Resolved** |
| ISSUE-D06 | Open P&L relies entirely on market cache. WS feed down → all open positions show pnl=0. No staleness indicator in `/api/pnl` or `/api/state`. | Medium |
| ISSUE-D07 | Brief generator uses two different P&L methods. `_compute_pnl_from_trades()` (today only, reads `pnl` from exit_correction) vs `compute_closed_pnl_from_logs()` (all-time, reads `pnl_correction`). Distinction not explained in output. | High |
| ISSUE-D08 | Open positions use 7-day lookback only. Multi-week open positions appear as closed (zero open positions reported). | Medium |

---

## 7. Known Issues Index

_Consolidated list of all known issues across all sections. Severity: Critical / High / Medium / Low._

| Issue ID | One-Line Description | Section | Severity |
|----------|---------------------|---------|----------|
| ISSUE-A01 | ~~Optimizer reads wrong path — reads `logs/` not `logs/trades/`. Sees 0 current trades. All 6 analysis dimensions are blind to live trading.~~ **FIXED Sprint P1-3 (ISSUE-005, commit 2e870f6).** ✅ RESOLVED (P1) | §4 Analytics | ~~Critical~~ **Resolved** |
| ISSUE-E01 | ~~Failed orders logged as `action='buy'` with `contracts=0`. `get_daily_exposure()` counts failed order `size_dollars`.~~ **FIXED Sprint 2 (ISSUE-029/099):** Failed orders now use `action='failed_order'` and `size_dollars=0.0`. `get_daily_exposure()` explicitly excludes `failed_order` records. | §2 Execution | ~~High~~ **Resolved** |
| ISSUE-E02 | `pnl` field missing from most exit paths. `compute_closed_pnl_from_logs()` returns $0 for exits unless caller sets `opportunity['pnl']`. **Partially fixed P1-2 (ISSUE-030):** `ruppert_cycle.py` and `post_trade_monitor.py` now set `pnl` on opportunity dict before logging. | §2 Execution | **Medium** |
| ISSUE-A02 | NO-side Brier score inverted. YES settlement → `outcome=1` regardless of trade side. NO bets have wrong polarity. | §4 Analytics | **High** |
| ISSUE-A03 | Schema conflict in `scored_predictions.jsonl`. `prediction_scorer.py` and `brier_tracker.py` write incompatible schemas to same file. | §4 Analytics | **High** |
| ISSUE-A06 | ~~`$10,000` capital fallback is silent.~~ **FIXED Sprint 2 (ISSUE-051):** Telegram alert + 4-hour dedup on fallback. | §4 Analytics | ~~High~~ **Resolved** |
| ISSUE-X01 | ~~Double-settle race condition. `check_expired_positions()` and `settlement_checker` can both process same position.~~ **FIXED Sprint 3 (ISSUE-025):** `_settle_record_exists()` guard added. | §3 Exit | ~~High~~ **Resolved** |
| ISSUE-X03 | ~~Tracker not updated by cycle exits. Cycle-entered positions without `add_position()` get no WS stop-losses or gain exits.~~ **FIXED Sprint 2 (ISSUE-031):** `remove_position()` called in both paths of `run_position_check()`. | §3 Exit | ~~High~~ **Resolved** |
| ISSUE-X09 | Global CB not updated by WS feed. `update_global_state()` must be called by trading cycle explicitly. CB may lag. | §3 Exit | **High** |
| ISSUE-I01 | ~~Watchdog double-spawn at boot. Two ws_feed instances compete for WS connection.~~ **FIXED Sprint 1 (ISSUE-049, commit ceba350):** `kill_existing_ws_feed()` called before every spawn. | §5 Infrastructure | ~~High~~ **Resolved** |
| ISSUE-D05 | ~~`AUTO_SOURCES` / `MANUAL_SOURCES` undefined in `get_account()`. May raise `NameError` or wrong trade counts.~~ **FIXED P1-4 (ISSUE-018):** Replaced with `_is_auto()`/`_is_manual()` module-scope helpers. ✅ RESOLVED (P1) | §6 Dashboard | ~~High~~ **Resolved** |
| ISSUE-D07 | Brief generator uses two conflicting P&L methods. Different fields, different scope. Not explained in output to David. | §6 Dashboard | **High** |
| ISSUE-E07 | `smart` mode runs `check` mode — no smart logic implemented. | §2 Execution | **Medium** |
| ISSUE-E04 | Session-level dedup only. Process restarts allow re-logging same trade. | §2 Execution | **Medium** |
| ISSUE-E05 | `strategy_size` missing → trade silently skipped + Telegram alert. | §2 Execution | **Medium** |
| ISSUE-X02 | ~~99c vs 100c discrepancy. `settlement_checker` uses 99c for wins; `check_expired_positions` uses 100c. 1-cent-per-contract systematic difference.~~ **FIXED P1-2 (ISSUE-026, commit d3584bf):** `settlement_checker.py` now uses `exit_price=100`. **FIXED P1-5 (ISSUE-098, commit 8a32658):** `position_monitor.py` corrected for YES-win and NO-win paths. ✅ RESOLVED (P1) | §3 Exit | ~~Medium~~ **Resolved** |
| ISSUE-X04 | ~~In-flight guard doesn't block threshold checks. Warning logs generated; dedup guard prevents double-exit.~~ **FIXED Sprint 1 Batch 2 (ISSUE-002):** `_exits_lock = asyncio.Lock()` in `execute_exit()` makes check+add of `_exits_in_flight` atomic. | §3 Exit | ~~Medium~~ **Resolved** |
| ISSUE-X08 | Fallback poll marks window evaluated on exception. Transient error → window permanently skipped for that connection cycle. | §3 Exit | **Medium** |
| ISSUE-A05 | Module mismatch auto-fix maps all `KXHIGH*` to `'weather_band'`. Cannot distinguish `weather_threshold`. Corrupts per-submodule analytics. | §4 Analytics | **Medium** |
| ISSUE-A08 | `run_domain_experiments()` is a no-op placeholder. No actual optimization runs. | §4 Analytics | **Medium** |
| ISSUE-I04 | `Ruppert-PostTrade-Monitor` (every 30 min) may overlap with WS exit path. `post_trade_monitor` uses `acquire_exit_lock()`; `position_tracker` (WS path) does NOT. Asymmetric locking — dedup guard is the only protection for concurrent exits. | §5 Infrastructure | **Medium** |
| ISSUE-D01 | ~~Fake P&L chart (two-point series). Hardcoded `'2026-03-10'` to today. Not real per-day cumulative data.~~ **FIXED P1-4/P1-5 (ISSUE-063/CLEANUP-063):** Removed from `dashboard/api.py`. ✅ RESOLVED (P1) | §6 Dashboard | ~~Medium~~ **Resolved** |
| ISSUE-D02 | ~~`BOT_SRC` missing `ws_*` sources in `/api/pnl`. WS-originated trades undercount in deployed capital.~~ **FIXED P1-4 (ISSUE-064):** `_is_auto()`/`_is_manual()` now at module scope, covers `ws_*` sources. ✅ RESOLVED (P1) | §6 Dashboard | ~~Medium~~ **Resolved** |
| ISSUE-D03 | ~~Settled positions may show as open (non-standard tickers, near-midnight EDT edge cases).~~ **FIXED P1-4 (ISSUE-065):** `exited` set now includes `settle` action records. ✅ RESOLVED (P1) | §6 Dashboard | ~~Medium~~ **Resolved** |
| ISSUE-D04 | P&L accumulation duplicated between `_build_state()` and `/api/pnl`. Bug fixes need double application. | §6 Dashboard | **Medium** |
| ISSUE-D06 | Open P&L shows $0 when WS feed is down. No staleness indicator in `/api/pnl` or `/api/state`. | §6 Dashboard | **Medium** |
| ISSUE-D08 | Brief generator uses 7-day lookback for open positions. Multi-week positions appear as closed. | §6 Dashboard | **Medium** |
| ISSUE-1-01 | `confidence` in crypto_15m is a z-score magnitude, NOT a probability. Strategy confidence gate compares it directly against probability-scale thresholds. | §1 Entry | **Medium** |
| ISSUE-1-03 | `crypto_threshold_daily` bypasses `should_enter()` entirely. No strategy gate runs. | §1 Entry | **Medium** |
| ISSUE-1-12 | Module daily cap config for `crypto_band_daily_*` absent. Strategy gate fails open; relies on module's own 7% check. | §1 Entry | **Medium** |
| ISSUE-E06 | `get_daily_exposure()` START_DATE hardcoded to `'2026-03-26'`. Brittle on redeployment. | §2 Execution | **Low** |
| ISSUE-E03 | `run_exit_scan()` raises `RuntimeError` unconditionally. Dead code in `main.py`. | §2 Execution | **Low** |
| ISSUE-E08 | Demo mode blocks orders but `log_trade()` still writes buy records. Demo trades appear real in logs. | §2 Execution | **Low** |
| ISSUE-X05 | ~~Legacy NO position migration. Pre-migration positions exited before migration may have wrong historical `entry_price`.~~ **FIXED Sprint 5 (ISSUE-042):** Migration block removed from `_load()`. NO `entry_price` now stored as-is. DS inserted 125 exit_correction records for 2026-04-02/03. CB global state refreshed. | §3 Exit | ~~Low~~ **Resolved** |
| ISSUE-X06 | `_write_off_logged` not cleared on WS reconnect. Write-off suppression persists across reconnects. | §3 Exit | **Low** |
| ISSUE-X07 | Recovery poll without `close_time` bypasses NO-side settlement guard. | §3 Exit | **Low** |
| ISSUE-A04 | `synthesize_pnl_cache()` comment/code divergence. Docstring says deleted; function still writes. | §4 Analytics | **Low** |
| ISSUE-A07 | `analyze_brier_score()` silently excludes records without `win_prob` and `noaa_prob`. | §4 Analytics | **Low** |
| ISSUE-I02 | Stale watchdog copy at `environments/demo/scripts/` with different constants. Risk of confusion. | §5 Infrastructure | **Low** |
| ISSUE-I03 | `mode.json` changes require process restart. No hot-reload. | §5 Infrastructure | **Low** |
| ISSUE-1-02 | `crypto_15m` ignores `strategy.py` size recommendation. `decision['size']` discarded; module uses own Half-Kelly. | §1 Entry | **Low** |
| ISSUE-1-04 | Polymarket nudge always 0.0 in `crypto_15m`. Shadow/logging only; never influences decisions. | §1 Entry | **Low** |
| ISSUE-1-05 | OI signal clips to ±2 (not ±3). Smaller max contribution vs other 15m signals. | §1 Entry | **Low** |
| ISSUE-1-06 | `crypto_band_daily` drift always 0.0. `drift` parameter in `band_prob()` has no effect in production. | §1 Entry | **Low** |
| ISSUE-1-07 | ~~OBI EWM direction reversal. Loop iterates backwards; older values influence EWM output more than expected.~~ **FIXED Sprint 4 (ISSUE-087):** EWM now seeds from oldest value and iterates forward; `reversed()` removed. | §1 Entry | ~~Low~~ **Resolved** |
| ISSUE-1-10 | OI snapshot written AFTER trade, read BEFORE signals. First-run bootstrap returns neutral S4. | §1 Entry | **Low** |
| ISSUE-1-11 | Data-collection mode thresholds in crypto_15m. `max_spread=25¢`, `thin_market=0.01`, `min_edge=0.02` — all relaxed. `data_quality` field tags affected trades. | §1 Entry | **Low** |
| ISSUE-A09 | `check_daily_cap_violations()` in `data_agent.py` is dead code. All per-module daily caps removed 2026-03-31. Function exists but will never fire. | §4 Analytics | **Low** |
| ISSUE-I05 | ~~**KXSOL15M actively misrouted.** KXSOL15M ticker not properly routed in WS feed dispatch logic.~~ **FIXED Sprint 4 (ISSUE-001):** 'KXSOL15M' added to `CRYPTO_15M_SERIES` in `ws_feed.py`. | §1 Entry / §3 Exit | ~~High~~ **Resolved** |

---

## 8. Data Flow Reference

_What each section produces and consumes. Files are relative to `environments/demo/`._

### Trade Logs — `logs/trades/trades_YYYY-MM-DD.jsonl`

| Action | Who Writes | Who Reads |
|--------|-----------|-----------|
| Buy records (`action='buy'`) | `Trader.execute_opportunity()` via `logger.log_trade()` | `logger.get_daily_exposure()`, `logger.get_daily_wager()`, `capital.get_capital()`, `data_agent.py` (all audits), `dashboard/api.py` (all endpoints), `ruppert_cycle.load_traded_tickers()`, `settlement_checker.load_all_unsettled()`, `brief_generator.py`, `prediction_scorer.py`, `optimizer.py` (wrong path — doesn't actually read) |
| Exit records (`action='exit'`) | `position_tracker.execute_exit()` | `logger.compute_closed_pnl_from_logs()`, `settlement_checker.load_all_unsettled()` (FIFO), `dashboard/api.py`, `brief_generator.py` |
| Settle records (`action='settle'`) | `position_tracker.check_expired_positions()`, `settlement_checker.py` | Same as exit records |
| Exit correction (`action='exit_correction'`) | Manual / `data_agent._cleanup_duplicates()` indirectly | `logger.compute_closed_pnl_from_logs()` (reads `pnl_correction`), `brief_generator._compute_pnl_from_trades()` (reads `pnl` — different field!) |

⚠️ **Conflict:** `brief_generator._compute_pnl_from_trades()` reads `pnl` from `exit_correction` records; `compute_closed_pnl_from_logs()` reads `pnl_correction`. Same record, different fields. Caller must set both or accept divergence.

---

### Position Tracker — `logs/tracked_positions.json`

| Action | Who Writes | Who Reads |
|--------|-----------|-----------|
| Add position | `position_tracker.add_position()` (called by `Trader.execute_opportunity()` and WS eval functions) | `position_tracker._load()` at module start, `data_agent.check_tracker_drift()`, `ruppert_cycle.run_orphan_reconciliation()` |
| Remove position | `position_tracker.remove_position()` (after exit or settlement) | — |
| Full persist | `position_tracker._persist()` (after every add/remove) | `ws_feed.py` (indirectly via `position_tracker.get_tracked()` for REST stale heal) |

---

### scored_predictions.jsonl — `logs/scored_predictions.jsonl`

| Action | Who Writes | Who Reads |
|--------|-----------|-----------|
| Score on settlement (post-hoc join) | `prediction_scorer.score_new_settlements()` (called from `settlement_checker`) | `optimizer.py` (reads for all analysis), `brier_tracker.get_domain_brier_summary()` |
| Score at resolution (push model) | `brier_tracker.score_prediction()` (called by position monitor on resolution) | Same readers as above |

⚠️ **Both writers write to same file with incompatible schemas** (ISSUE-A03). `prediction_scorer` schema lacks `ts`, `market_price`, `side`, `resolved_at`. `brier_tracker` schema lacks `date`, `settlement_date`, `pnl`, `confidence`.

---

### OI Snapshot — `logs/oi_1d_snapshot.json`

| Action | Who Writes | Who Reads |
|--------|-----------|-----------|
| Update OI baseline | `crypto_threshold_daily.cache_oi_snapshot(write=True)` — written AFTER successful trade | `crypto_threshold_daily.compute_s4_oi_regime()` — read BEFORE signal computation |

⚠️ **Write happens after trade; read happens before.** First-run (bootstrap): no file → S4 returns neutral with full weight.

---

### Decision Logs

| File | Who Writes | Who Reads |
|------|-----------|-----------|
| `logs/decisions_15m.jsonl` | `crypto_15m._log_decision()` — every evaluation (ENTER or SKIP) | `dashboard/api.py` (`/api/crypto/15m_summary`), `data_agent.check_decision_log_orphans()`, `data_agent.check_15m_entry_drought()` |
| `logs/decisions_weather.jsonl` | Weather scan module | `data_agent.check_decision_log_orphans()` |
| `logs/decisions_econ.jsonl` etc. | Respective scan modules | `data_agent.check_decision_log_orphans()` |

---

### Circuit Breaker State — `logs/circuit_breaker_state.json`

| Action | Who Writes | Who Reads |
|--------|-----------|-----------|
| Increment consecutive losses | `circuit_breaker.increment_consecutive_losses()` called by `position_tracker._update_daily_cb()` | `crypto_15m` (checks before entry), `ws_feed.evaluate_crypto_entry()`, `crypto_threshold_daily` (step 1b), `ruppert_cycle.check_loss_circuit_breaker()` |
| Reset consecutive losses | `circuit_breaker.reset_consecutive_losses()` called by `position_tracker._update_daily_cb()` | — |
| Update global state | `circuit_breaker.update_global_state()` called explicitly by trading cycle | `ruppert_cycle.check_loss_circuit_breaker()` → `strategy.check_loss_circuit_breaker()` |

⚠️ **WS feed does NOT call `update_global_state()`** — global CB may lag (ISSUE-X09).

---

### Price Cache — `logs/price_cache.json`

| Action | Who Writes | Who Reads |
|--------|-----------|-----------|
| Update on WS tick | `market_cache.update()` called by `ws_feed.handle_message()` | All entry modules (via `market_cache.get_market_price()`), `dashboard/api.py` (`/api/positions/active`, `/api/positions/prices`), `synthesizer.synthesize_pnl_cache()` (open P&L) |
| REST heal (stale entries) | `ws_feed._rest_refresh_stale()` every 5 min | — |
| Persist to disk | `market_cache.persist()` every 60s + on reconnect | `market_cache.load()` at WS feed startup |

---

### Truth Files — `logs/truth/`

| File | Who Writes | Who Reads |
|------|-----------|-----------|
| `pnl_cache.json` | `synthesizer.synthesize_pnl_cache()` | ⚠️ **`capital.py` does NOT read this** (bypasses for freshness). Dashboard reads it only as fallback. |
| `pending_alerts.json` | `synthesizer.synthesize_alerts()` + `data_agent._append_pending_alert()` directly + `data_health_check._push_alert()` (**Fixed P1-5 / ISSUE-121** — now writes JSON array to `logs/truth/pending_alerts.json`) | `dashboard/api.py`, `brief_generator.py` |
| `state.json` | `synthesizer.synthesize_state()` | `ruppert_cycle.load_traded_tickers()` (merges if same-day) |
| `pending_optimizer_review.json` | `synthesizer.synthesize_optimizer_review()` | `brief_generator.py` (Research Pipeline section) |
| `crypto_prices.json` | Background scan (not detailed in section files) | `dashboard/api.py` (`/api/crypto/scan`) |
| `crypto_smart_money.json` | Bot scan | `dashboard/api.py` (`/api/crypto/scan`) |

---

### Predictions Log — `logs/predictions.jsonl`

| Action | Who Writes | Who Reads |
|--------|-----------|-----------|
| Log at trade entry | `brier_tracker.log_prediction()` | `brier_tracker.score_prediction()` (iterates in reverse to find most recent unscored entry) |

---

### WS Heartbeat — `logs/ws_feed_heartbeat.json`

| Action | Who Writes | Who Reads |
|--------|-----------|-----------|
| Write every 60s + on connect | `ws_feed._write_heartbeat()` | `ws_feed_watchdog.py` (reads every 60s to check freshness) |

---

### Demo Deposits — `logs/demo_deposits.jsonl`

| Action | Who Writes | Who Reads |
|--------|-----------|-----------|
| Manual deposit entries | Human / dashboard POST (Phase 4: logs event only, doesn't write directly) | `capital.get_capital()` (sums all amounts), `dashboard/api.py` (`/api/deposits` GET, `/api/account`) |

---

### State File — `logs/state.json`

| Action | Who Writes | Who Reads |
|--------|-----------|-----------|
| After every cycle | `ruppert_cycle.save_state()` | `ruppert_cycle.load_traded_tickers()` (merges if same-day, ignores if different day) |

⚠️ **Separate from `logs/truth/state.json`** (synthesizer output). Two different state files with similar names.

---

### Watchdog Log — `logs/watchdog.log`

| Action | Who Writes | Who Reads |
|--------|-----------|-----------|
| Every check + restart | `ws_feed_watchdog.py` (appended) | Human review only |

---

### Data Audit State — `logs/data_audit_state.json`

| Action | Who Writes | Who Reads |
|--------|-----------|-----------|
| After every audit run | `data_agent.py` | `data_agent.py` (alert dedup 4h, historical audit once-per-day gate) |

---

### Event Log — `logs/raw/events_YYYY-MM-DD.jsonl`

| Action | Who Writes | Who Reads |
|--------|-----------|-----------|
| ALERT_CANDIDATE, STATE_UPDATE, OPTIMIZER_REVIEW_NEEDED, SETTLEMENT, etc. | Various modules via `scripts/event_logger.log_event()` | `synthesizer.run_synthesis()` (reads today's file once, passes to all four synthesizers), `brief_generator.py` (anomalies, scan activity) |

---

### Optimizer Proposals — `logs/optimizer_proposals_YYYY-MM-DD.md`

| Action | Who Writes | Who Reads |
|--------|-----------|-----------|
| Manual/scheduled optimizer run | `optimizer.py` | Human (David) review only. Also referenced in `brief_generator.py` Research Pipeline section via `logs/truth/pending_optimizer_review.json`. |

---

_End of System Map_

---

## 9. Revision History

- v1.0 (2026-04-02): Initial assembly from 6 research agents
- v1.1 (2026-04-02): Corrections from 10-audit pass (12 factual errors fixed, 12 gaps filled)
- v1.2 (2026-04-03): DS domain updated for Sprints 1-5. Changes: logger `_append_jsonl` portalocker (cross-process safety); `log_exit()`/`log_settle()` wrappers with `_logged_exit_fingerprints` dedup; `capital.py` fallback Telegram alert + 4-hour dedup (ISSUE-051); `settlement_checker` bid-only phantom settlement inference removed (ISSUE-028); `data_agent` `_has_close_record()` guard prevents settled position resurrection (ISSUE-055); `_PROTECTED_ACTIONS` prevents exit/settle/exit_correction deletion (ISSUE-056); exit/settle `date` fields use `_today_pdt()` PDT timezone (ISSUE-044); `exit_correction` action type counted by `compute_closed_pnl_from_logs()`; 5 known issues marked resolved (ISSUE-X01, ISSUE-X03, ISSUE-A06, ISSUE-I01, ISSUE-I05, ISSUE-E01).
- v1.3 (2026-04-03): Trader domain updated for Sprints 1-5. Changes: NO-side entry_price flip removed from `add_position()` and `_load()` — price now stored as-is (ISSUE-042); `EXIT_GAIN_PCT` now required (ImportError if missing, ISSUE-043); Design D stops gated to `side='yes'` only, `side` resolved at top of `check_exits()` loop (ISSUE-042); `_exits_lock` asyncio.Lock for atomic exit dedup (ISSUE-002); 3-strike exit abandon with JSONL audit record (ISSUE-003, DS-NEW-001); stale position ref snapshots before await (ISSUE-107); CB file-locked via portalocker on all read-modify-write ops (ISSUE-076); CB WARNING log on trip with asset name (ISSUE-047); WS eval dedup via `_window_eval_lock` in `_safe_eval_15m()` and `_check_and_fire_fallback()` (ISSUE-015, ISSUE-060); blocking I/O moved to `run_in_executor` in `_safe_eval_hourly()` and `_rest_refresh_stale()` (ISSUE-014, ISSUE-061); exposure cap corrected to `DAILY_CAP_RATIO` (ISSUE-070); KXSOL15M added to WS series (ISSUE-001); OBI EWM direction corrected (ISSUE-087); 5 additional known issues marked resolved (ISSUE-X04, ISSUE-X05, ISSUE-1-07, and re-confirmed ISSUE-X01, ISSUE-X03).
- v1.4 (2026-04-03): QA corrections. §2.7: ISSUE-E01 marked Resolved (Sprint 2, ISSUE-029/099, commit d286b28 — failed orders now use `action='failed_order'`). §5.4: Watchdog double-spawn marked Resolved (Sprint 1, ISSUE-049, commit ceba350 — `kill_existing_ws_feed()` called before every spawn). §7 index entry for ISSUE-I01 updated with commit reference.
- v2.0 (2026-04-03): Applied 40+ corrections from P1 domain audits (DS, Trader, Strategist) verified by QA. All QA-verified P1 known issues marked ✅ RESOLVED. Key changes: settlement exit_price 99→100 (ISSUE-026/027/098); optimizer glob path fixed (ISSUE-005); WS reconnect changed to exponential backoff (ISSUE-096); S5 Polymarket switched to daily function + bounds gate (ISSUE-057/089); daily module cap lock via portalocker (ISSUE-053); exit records gain edge+confidence fields (ISSUE-074); dashboard issues D01/D02/D03/D05 resolved; brier_tracker dynamic paths (ISSUE-004); KXXRPD/KXDOGED added to TICKER_MODULE_MAP (ISSUE-102); signal weight validation at startup (ISSUE-114/069); OI delta near-zero guard (ISSUE-129); normalize_entry_price() in post_trade_monitor (ISSUE-079).
- v2.1 (2026-04-03): Archived environments/live/ (will be rebuilt from scratch before going live). Archived autoresearch.py (will be replaced with new backtest engine). Removed active-component descriptions for both; added archive note in module inventory.
