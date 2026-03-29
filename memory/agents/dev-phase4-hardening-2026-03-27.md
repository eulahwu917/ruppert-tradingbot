# Dev Phase 4: Architectural Hardening
**Date**: 2026-03-27
**Agent**: Developer (Opus 4.6)
**Status**: COMPLETE

## Summary
Three hardening components: persistent state file for cross-cycle dedup, KalshiMarket dataclass for future type safety, and a loss circuit breaker to halt trading on bad days.

## Changes Made

### Component 1: state.json for persistent cross-cycle dedup

#### ruppert_cycle.py
- Added `save_state()` helper function — writes `logs/state.json` with `traded_tickers`, `last_cycle_ts`, and `last_cycle_mode`
- At startup (after trade log dedup load): reads `state.json` if it exists and is from today, merges tickers into `traded_tickers` set
- Handles missing/corrupt state.json gracefully — trade log remains the primary fallback
- Added `save_state()` calls at **all 7 exit points**: check mode, econ_prescan (2 exits), weather_only, crypto_only, report, and full cycle end

#### state.json schema
```json
{
  "traded_tickers": ["KXHIGHNY-26MAR27-T62", ...],
  "last_cycle_ts": "2026-03-27 07:03:25",
  "last_cycle_mode": "full"
}
```

### Component 2: KalshiMarket dataclass in kalshi_client.py
- Added `KalshiMarket` dataclass with fields: ticker, yes_ask, no_ask, yes_bid, no_bid, status, close_time, title, volume_fp, open_interest_fp
- Includes `from_dict(cls, d)` classmethod and `to_dict()` instance method
- `get_markets()` and `get_market()` still return plain dicts — dataclass is available infrastructure only
- Added TODO comment: `# TODO: migrate callers to use KalshiMarket.from_dict() for type safety`
- Added `from dataclasses import dataclass` and `from typing import Optional` imports

### Component 3: Loss circuit breaker

#### config.py
- Added `LOSS_CIRCUIT_BREAKER_PCT = 0.05` (5% of capital)

#### bot/strategy.py
- Added `check_loss_circuit_breaker(logs_dir, capital)` function
- Reads today's trade log, sums `realized_pnl` from exit records where pnl < 0
- Returns `{'tripped': bool, 'reason': str, 'loss_today': float}`
- Handles missing log and read errors gracefully (returns tripped=False)
- Added `import json`, `from datetime import date`, `from pathlib import Path`

#### ruppert_cycle.py
- Added `check_loss_circuit_breaker` to imports from `bot.strategy`
- Circuit breaker check runs after dedup loading, before exposure computation
- If tripped: pushes warning alert, saves state, logs event, exits cleanly
- If losses exist but within threshold: prints status message

## Test Results
- Syntax check: all 4 files (ruppert_cycle.py, kalshi_client.py, bot/strategy.py, config.py) parse clean
- pytest: 18/18 tests passed (test_cycle_modes, test_dedup, test_kelly, test_patterns, test_strategy_routing)

## Files Modified
1. `ruppert_cycle.py` — state.json read/write + circuit breaker integration
2. `kalshi_client.py` — KalshiMarket dataclass added
3. `bot/strategy.py` — check_loss_circuit_breaker() added
4. `config.py` — LOSS_CIRCUIT_BREAKER_PCT added
