# SA-3: Developer Memory
_Build log, architecture decisions, and known issues._

---

## Mandate

Build and test code assigned by CEO. Git commit all changes.
Never deploy to live without CEO + David approval.
Always read `team_context.md` before starting a build task.

---

## Build Log

### 2026-03-11 (Build 2)

**Built: `bot/strategy.py`** (NEW)
- Trading Strategy Layer — module-agnostic
- 6 functions: calculate_position_size, check_daily_cap, should_enter, should_add, should_exit, get_strategy_summary
- All thresholds as module-level constants (self-contained, no config.py dependency)
- Has __main__ test block

**Updated: `crypto_client.py`**
- Student's t-distribution (df=3) — scipy not installed, using pure-Python fallback
- EWMA vol (λ=0.94)
- Multi-timeframe RSI (1h + 4h)
- Magnitude-weighted momentum scoring (threshold: 3.5 points)
- Expanded wallet list (8 total, 5 are placeholders)
- Backward-compatible: kept legacy bull_signals/bear_signals int fields

**Fixed: `main.py` + `trader.py`** — Reversal stop + double-sizing fixes
- Added `_load_trade_record(ticker)` helper in `main.py`: searches `logs/trades_*.jsonl` for most recent matching record
- `run_exit_scan()`: now loads real `entry_price` (from `market_prob` × side) and `entry_edge` from trade log; computes `current_edge = abs(current_bid/100 - (1 - entry_price/100))`; falls back to conservative defaults if no record
- `run_weather_scan()`: sets `opp['strategy_size'] = decision['size']` after `should_enter()` approves
- `trader.py`: imports `contracts_from_size` from `risk`; `execute_opportunity()` checks `opp.get('strategy_size')` — uses it directly (skips `risk.py` re-sizing); falls back to `check_pre_trade()` if not set
- Both files pass `py_compile` with no errors

**Updated: `edge_detector.py`**
- Removed T-market hard NO-only rule and -10% YES bias
- Added soft confidence prior (±15% adjustment, overridden by strong signals >30% edge)

**Built: `bot/position_monitor.py`** (NEW)
- Risk monitor with 95¢ rule, 70% gain rule, near-settlement hold, reversal stops
- DEMO mode only — logs exits, has TODO stubs for live execution
- Reads API key from secrets/kalshi_config.json

---

## Pending Build Tasks

- [x] Wire `bot/strategy.py` into `main.py` (replace old sizing logic) — 2026-03-11
- [x] Fix reversal stop: read real entry data from trade logs in `run_exit_scan()` — 2026-03-11
- [x] Fix double-sizing: `strategy_size` takes priority over `risk.py` in `trader.py` — 2026-03-11
- [ ] Wire `bot/position_monitor.py` into Task Scheduler
- [ ] Install scipy: `pip install scipy`
- [ ] Replace 5 placeholder Polymarket wallets with real addresses
- [ ] Fix Miami NWS grid 404 (MFL office, gridX=110, gridY=37 may be wrong)
- [ ] Add ECMWF ensemble to openmeteo_client.py (post-Friday)
- [ ] Build Jobs/Labor module: `bot/jobs.py` (BLS NFP + unemployment)
- [ ] Build Commodities module: `bot/commodities.py` (EIA oil/gas, FRED gold)
- [ ] Demo/Live toggle in dashboard header + confirmation modal

---

## Architecture Decisions

- **strategy.py is self-contained**: No imports from config.py. Thresholds live in strategy.py. This prevents circular dependencies and makes the layer testable in isolation.
- **position_monitor.py in bot/ subdirectory**: Separate from the root-level position_monitor.py (which is weather-specific). The bot/ version is the new unified risk layer.
- **crypto_client.py backward compat**: Kept legacy `bull_signals`/`bear_signals` int fields alongside new float `bull_score`/`bear_score` to avoid breaking existing dashboard signal display.
- **DEMO mode flag**: position_monitor.py checks `DEMO_MODE = True` at top of file — flip to False for live execution (requires CEO + David approval).

---

## Known Issues / Tech Debt

| Issue | Severity | Fix |
|-------|----------|-----|
| scipy not installed → t-dist fallback | Medium | `pip install scipy` |
| 5 placeholder Polymarket wallets | Medium | Get real addresses from leaderboard |
| Miami NWS grid 404 | Medium | Find correct MFL grid coordinates |
| strategy.py not wired into main.py | High | Next build task |
| position_monitor.py not in Task Scheduler | High | Add after CEO review |
| `import requests as req` inside get_trades() | Low | Move to module level |
