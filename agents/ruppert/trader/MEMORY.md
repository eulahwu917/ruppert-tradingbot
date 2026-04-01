# MEMORY.md — Trader Long-Term Memory
_Owned by: Trader agent. Updated after execution issues, position management changes, or risk discoveries._

---

## Execution Architecture
- Trader executes autonomously within thresholds — CEO NOT in per-trade loop
- CEO involvement: exceptions only (hard limit, circuit breaker, anomaly, new instrument)
- WS-first: position exits via position_tracker.py (<1s latency). post_trade_monitor.py = safety net only.
- Orders + startup + reconnect = REST only

## Risk Limits (current)
- MAX_POSITION_PCT = 1% of capital (~$10-25 depending on capital)
- MAX_POSITION_SIZE = $100 hard cap (legacy fallback in config.py)
- MAX_DAILY_EXPOSURE = $700 hard cap (legacy fallback in config.py)
- Per-module daily caps: Weather 7%, Crypto 7%, Geo 4%, Econ 4% of capital
- Global 70% open exposure cap: checked in real-time via should_enter()
- OI cap: no single position > 5% of market open interest

## Exit Rules
- 95c rule: exit when price hits $0.95 (weather + crypto)
- 70% gain exit: exit when unrealized gain ≥ 70% (weather + crypto)
- Econ/Geo/Fed: alert-only exits (no auto-exit)
- YES-side 95c rule: added 2026-03-28 (was missing)

## Position Tracking
- Positions keyed by (ticker, side) — not ticker alone (fixed 2026-03-28)
- Disk persistence: tracked_positions.json
- Weather trades: must call tracker.add_position() in trader.py (fixed 2026-03-28)

## Known Issues / Fixed
- Weather trades not registered in position tracker — fixed 2026-03-28
- Fed P&L bug: scan_price/fill_price were missing — fixed 2026-03-28
- Crypto/Fed bypassing should_enter() 70% global cap — fixed 2026-03-26
- post_trade_monitor YES-side 95c missing — fixed 2026-03-28
- crypto_15m: hardcoded LOGS_DIR → fixed to env_config

## Lessons Learned
- Every module must call tracker.add_position() or exits silently never fire
- (ticker, side) keying required — same ticker can have YES and NO positions simultaneously
- P&L fields (scan_price, fill_price) must be logged at entry or post-trade P&L is wrong
- Live flip requires 3 explicit David confirmations — never self-authorize

---

## 2026-03-31 Evening Session Update

### P&L Architecture — BREAKING CHANGE
- **`pnl_cache.json` deleted permanently.** Do not reference or recreate.
- Single canonical P&L path: raw logs → `compute_closed_pnl_from_logs()` → `get_capital()`
- mtime-based in-process cache handles performance — no file-based caching

### CB (Capital Bridge) Bugs Fixed
- `realized_pnl` field bug fixed → now reads `pnl` field (matching actual log record schema)
- Negative capital guard added — prevents impossible capital values from corrupting downstream

### NO-side P&L Formula
- Formula bug corrected in ws_feed
- ws_feed restarted to load corrected logic
- 3 correction records applied to fix affected historical entries

### Brief Generator Fixed
- Was showing $19K P&L (wrong) due to missing `exit_correction` records
- Now uses canonical `compute_closed_pnl_from_logs()` — same source as `get_capital()`
- Module list now dynamic — no hardcoded `KNOWN_MODULES`

### Capital at EOD: ~$13,146
