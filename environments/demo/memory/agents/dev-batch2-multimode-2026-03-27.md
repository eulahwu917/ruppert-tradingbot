# Dev Batch 2 — Multi-Mode Support in ruppert_cycle.py
**Date:** 2026-03-27
**Agent:** Developer

## Task
Implement three new mode blocks in `ruppert_cycle.py` to support targeted scans scheduled at different times of day, avoiding full-cycle overhead.

## Changes Made

### ruppert_cycle.py
Added three new mode blocks after the `MODE == 'check'` exit and before the `MODE == 'report'` block:

1. **`econ_prescan`** (5am) — Lines 292–393
   - Checks `economics_client.get_upcoming_releases()` for any release with `days_away == 0`
   - If no release today: logs done, exits cleanly
   - If release today: runs `find_econ_opportunities()` from economics_scanner
   - Each opportunity goes through `should_enter()` with full cap/exposure checks
   - Respects `ECON_DAILY_CAP_PCT * capital` daily cap
   - Follows same signal/should_enter/log_trade pattern as fed trades in main.py
   - Wraps everything in try/except, always exits with `sys.exit(0)`

2. **`weather_only`** (7pm) — Lines 395–412
   - Imports and calls `run_weather_scan(dry_run=DRY_RUN)` from main.py
   - Logs weather trade count, exits cleanly

3. **`crypto_only`** (10am, 6pm) — Lines 414–431
   - Imports and calls `run_crypto_scan(dry_run=DRY_RUN, direction=None, traded_tickers=traded_tickers, open_position_value=OPEN_POSITION_VALUE)` from main.py
   - Passes `direction=None` since smart money refresh doesn't run in this mode
   - Logs crypto trade count, exits cleanly

### Docstring updated
Added all three new modes to the module docstring.

## Verification
- `ast.parse()` syntax check: **SYNTAX OK**
- All three modes end with `sys.exit(0)` — no fallthrough
- All use existing `DRY_RUN`, `traded_tickers`, `OPEN_POSITION_VALUE` variables
- All call `log_cycle('done', {...})` before exiting
- All wrapped in try/except for clean error handling

## Key Design Decisions
- `econ_prescan` builds its own trade execution loop (like fed in main.py) because `run_econ_scan()` in main.py only logs opportunities without executing trades
- `weather_only` and `crypto_only` delegate to existing `run_weather_scan` / `run_crypto_scan` which already handle trade execution
- `crypto_only` passes `direction=None` because smart money signal is not refreshed in this mode — crypto_scan handles null direction gracefully
