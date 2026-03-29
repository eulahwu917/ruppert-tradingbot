# Opus Deep Codebase Audit — 2026-03-26 (Evening Session 3)

Bottom-up, 10-layer audit. Full findings below.

---

# RUPPERT TRADING BOT — CODEBASE AUDIT

## 1. Data Layer — CONCERN

**kalshi_client.py:**
- Orderbook enrichment swallows exceptions silently (line 103-104: `except Exception: pass`). If orderbook fetch fails, bid/ask remain None but market still returned.
- No backoff on 429 responses (only 50ms sleep).
- `search_markets()` returns markets with potentially null `yes_bid`/`no_bid`.

**crypto_client.py:**
- `_cache_get()` returns None for both "not cached" and "cached value is None" (line 126-128) — ambiguous.
- 5 placeholder wallet addresses starting with `0xTODO` (lines 66-70) — filtered at runtime but should be removed.
- Binance funding rate API may be geo-blocked in US (documented but still called).

**Staleness:**
- crypto staleness check (>25h) ✓
- FOMC calendar cache (<7 days) ✓
- MISSING: No staleness check on GHCND bias cache at runtime.

---

## 2. Signal Generation — CONCERN

**edge_detector.py (Weather):**
- `parse_date_from_ticker()` returns `date.today()` as fallback — silent wrong date (line 178-187).
- Fields: ticker, edge, win_prob, confidence, side, yes_price, bet_price — consistently populated ✓

**crypto_client.py (Crypto):**
- Signal dict uses different field names: `prob_model` instead of `win_prob`, `price` instead of `bet_price`.
- Confidence scoring not calibrated against actual outcomes.

**geopolitical_scanner.py (Geo):**
- CRITICAL: No edge calculation — only `news_volume` and `requires_human_review: True`.
- `GEO_AUTO_TRADE = True` in config.py line 59 — can't auto-trade without a real signal.

**fed_client.py (Fed):**
- Uses CME FedWatch OAuth token that expires in ~30 min. Token fetch failure → entire Fed scan returns None.

---

## 3. Risk / Strategy Layer (bot/strategy.py) — SOLID with concerns

**should_enter() walkthrough:**
1. Time gate (0.5h)
2. Confidence gate (0.25)
3. Edge gate (module-specific)
4. Direction filter (weather-only NO)
5. Global 70% exposure cap
6. Daily cap
7. Kelly sizing
8. Market impact ceiling
9. Final cap: min(impact_size, room)
10. MIN_VIABLE_TRADE ($5 floor)

**Kelly sizing:**
- BUG: `kelly_fraction_for_confidence()` tiers (lines 46-74) don't match `get_strategy_summary()` reported tiers (lines 466-469). Actual: 0.16/0.14/0.12/0.10. Reported: 0.25/0.20/0.15/0.10.

**Daily caps:**
- Per-cycle counter tracks within cycle only. Intra-day restarts reset cycle counters but `get_daily_exposure()` still counts all-day trades — no double counting but logic is fragmented.

**OI cap:**
- `open_interest` often None for weather markets (not fetched) — OI cap effectively inactive for weather.

**Capital read:** `get_capital()` reads from `demo_deposits.jsonl` + `pnl_cache.json`.

---

## 4. Execution Layer (main.py + modules) — BUG-RISK

**CRITICAL: risk.py is missing**
- `trader.py` line 6: `from risk import check_pre_trade, contracts_from_size`
- Only `__pycache__/risk.cpython-312.pyc` exists — will crash on cache clear or Python version change.

**Uniformity issues:**
- Weather: uses `Trader` class (trader.py)
- Crypto/Fed: inline execution in main.py with direct `client.place_order()` calls
- Crypto `opp` dict missing `source: 'crypto'` field

**DRY_RUN:**
- `capital.py` line 33 checks `config.DEMO_MODE` — **never defined** in config.py — always evaluates to True (safe but wrong).

**Error handling:** API failures caught, logged only, no retries.

---

## 5. Post-Trade / Exit Layer — CONCERN (duplication)

**Two separate monitoring systems:**
1. `post_trade_monitor.py` — reads today's `trades_{today}.jsonl` only
2. `bot/position_monitor.py` — reads ALL `trades_*.jsonl` files, different implementation, hardcoded `mode: "demo"`

**BUG: `post_trade_monitor.py` only reads today's log** — misses multi-day positions entered yesterday.

---

## 6. Logging (logger.py) — SOLID

**build_trade_entry() fields:** trade_id, timestamp, date, ticker, title, side, action, source, module, noaa_prob, market_prob, edge, confidence, size_dollars, contracts, order_result

**Confidence fallback:** Falls back to `abs(edge)` if confidence is None — approximation.

**P&L calc:** Uses `size_dollars` diff between entry/exit — ignores contract count and price movement.

**Log rotation: NOT IMPLEMENTED** — files grow unbounded.

---

## 7. Config Consistency — CONCERN

**OPTIMIZER_* constants vs optimizer.py:** All match ✓

**Magic numbers in non-config files:**
- `strategy.py` line 37: `KELLY_FRACTION = 0.25` — different from `kelly_fraction_for_confidence()` tiers
- `crypto_client.py` line 437: `SIGNAL_THRESHOLD = 3.5`
- `economics_scanner.py` line 38: `MIN_VOLUME = 100`

**mode.json → DRY_RUN chain: Airtight ✓**

---

## 8. Orchestration (ruppert_cycle.py) — SOLID

- Mode routing: full/check/report implemented; `smart` mode falls through to full (bug or design?)
- Partial failure handling: each step wrapped in try/except ✓
- No sub-agents spawned internally ✓

---

## 9. Cross-Cutting Concerns — CONCERN

**Single responsibility violations:**
- `main.py` (800+ lines): weather scan + crypto scan + fed scan + exit scan + test_connection + inline execution
- `crypto_client.py` (1000+ lines): price data + RSI + funding rates + smart money + probability models

**Modules with own risk logic (bypassing strategy.py):**
- `geopolitical_scanner.py`: no risk check
- `economics_scanner.py`: inline MIN_EDGE + MIN_VOLUME checks (lines 101-105)

**LIVE/DEMO safety:**
- `KalshiClient._demo_block()` blocks order methods when `self.is_live = False`
- CONCERN: `is_live` set from `kalshi_config.json`, NOT from mode.json/DRY_RUN — dual control plane

**Security:** No hardcoded secrets ✓

---

## 10. Logic Sanity Check — CONCERN

**Zombie paths:**
- `best_bets_scanner.py`: imported but never called
- `trader.py`: only used by weather; crypto/fed bypass it
- `baselines.py`: `log_always_no_weather()` called but results never analyzed

**Off-by-one in daily cap:**
- `get_daily_exposure()` sums ALL `size_dollars` today including EXITS
- Entry $10 + exit $10 = $20 "deployed" → could prematurely hit daily cap

**10pm check vs full cycle:** Identical position check logic, correct behavior.

---

# PRIORITIZED ISSUES

## P0 — Crash / Silent Loss Risk
| Issue | File:Line | Description |
|---|---|---|
| Missing risk.py | trader.py:6 | Import will crash after cache clear |
| Undefined DEMO_MODE | capital.py:33 | Checks nonexistent attribute |

## P1 — Logic Error
| Issue | File:Line | Description |
|---|---|---|
| Kelly tier mismatch | strategy.py:46-74 vs 466-469 | Actual tiers don't match reported |
| Daily exposure includes exits | logger.py:100-114 | Overstates deployed capital |
| Today-only position loading | post_trade_monitor.py:48 | Misses multi-day positions |
| Geo AUTO_TRADE=True with no edge | config.py:59, geopolitical_scanner.py | Can't auto-trade without signal |
| yes_bid same as yes_ask | main.py:608 | Spread always 0 on crypto opp dict |

## P2 — Reliability
| Issue | File:Line | Description |
|---|---|---|
| Orderbook errors swallowed | kalshi_client.py:103-104 | Markets returned with null prices |
| No API retry logic | kalshi_client.py | 429/5xx not retried |
| Dual position monitors | post_trade_monitor.py, bot/position_monitor.py | Redundant, divergent |
| Cache None ambiguity | crypto_client.py:126-128 | Can't distinguish "not cached" vs "cached None" |
| CME token expiry | fed_client.py:232-237 | Single fetch failure blocks Fed scan |

## P3 — Cleanup
| Issue | File:Line | Description |
|---|---|---|
| TODO wallet placeholders | crypto_client.py:66-70 | Remove |
| Unbounded log files | logger.py | No rotation |
| main.py too large | main.py | 800+ lines |
| Hardcoded magic numbers | crypto_client.py:437, economics_scanner.py:38 | Move to config |
