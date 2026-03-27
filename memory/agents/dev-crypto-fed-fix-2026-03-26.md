# Dev Fix Summary — Crypto + Fed Strategy Wiring
**Date:** 2026-03-26  
**Agent:** SA-3 Developer  
**File modified:** `ruppert_cycle.py` only

---

## New Imports Added

**Line 24** — added `should_enter` to existing bot.strategy import:
```python
from bot.strategy import check_daily_cap, check_open_exposure, should_enter
```
(`get_buying_power` was already present at line 25 via `from capital import get_capital, get_buying_power`)

---

## Fix 1 — P0: Crypto sizing crash + strategy bypass

### Lines changed in scan loop (approximately lines 418–437)

**Removed** (crash line):
```python
size = min(config.CRYPTO_MAX_POSITION_SIZE, 25)
contracts = max(1, int(size / best_price * 100))
actual_cost = round(contracts * best_price / 100, 2)
```

**Replaced** with `_hours_left` calculation from `close_time` and updated `new_crypto.append()` dict to carry:
- `yes_ask`: ya (raw ask cents)
- `yes_bid`: ya (proxy; no bid field on market)
- `prob_model`: computed band probability
- `confidence`: edge (proxy for logger)
- `hours_to_settlement`: computed from close_time or default 18.0

### Lines changed in execution loop (approximately lines 459–530)

**Replaced** entire old `for t in new_crypto[:3]:` block with new pattern:
1. Compute `_crypto_daily_cap = _total_capital * getattr(config, 'CRYPTO_DAILY_CAP_PCT', 0.07)`
2. Get `_open_exposure` from `get_buying_power()` (falls back to `OPEN_POSITION_VALUE`)
3. Per-iteration: `check_open_exposure()` global 70% guard
4. Per-iteration: per-module daily cap guard
5. Build `signal` dict and call `should_enter(signal, _total_capital, _deployed_today)`
6. Skip if `decision['enter']` is False
7. Skip if `decision['size']` would exceed remaining daily cap
8. `size = decision['size']` (Kelly-sized, market impact capped)
9. Track `_crypto_deployed_this_cycle`, `_open_exposure` after each trade

Added `'confidence'` field to the `opp` dict for logger.

### Summary line
Changed `min(len(new_crypto), 3)` to `_crypto_trades_executed` (accurate count of actually-executed trades).

---

## Fix 2 — P1: Fed sizing bypass

### Lines changed (approximately lines 559–660)

**Replaced** old sizing block:
```python
size = min(25.0, _fed_cap_ok)
```

**Replaced** with full `should_enter()` routing:
1. Added `_fed_daily_cap = _fed_capital * getattr(config, 'ECON_DAILY_CAP_PCT', 0.04)`
2. Computed `_fed_hours = max(1.0, days_to_meeting * 24)` for Kelly
3. Get `_fed_open_exposure` from `get_buying_power()`
4. Added `check_open_exposure()` guard
5. Built `_fed_signal_dict` with all required fields (`edge`, `win_prob`, `confidence`, `hours_to_settlement`, `module='fed'`, etc.)
6. Called `should_enter(_fed_signal_dict, _fed_capital, _fed_deployed)`
7. Skip if strategy says no
8. Skip if size exceeds fed daily cap
9. `size = min(_fed_decision['size'], _fed_cap_ok)`

**Re-indented** the entire `opp` dict + DRY_RUN/LIVE execution block one extra level (16→20 spaces) to be inside the new inner `else:` branch.

---

## Verification

- ✅ `config.CRYPTO_MAX_POSITION_SIZE` — **no longer referenced anywhere** in `ruppert_cycle.py`
- ✅ `python -c "import ast; ast.parse(...)"` — **SYNTAX OK**
- ✅ `should_enter` imported and called in both crypto (line ~491) and fed (line ~597) sections
- ✅ `check_open_exposure` called in both sections
- ✅ `get_buying_power` already imported, reused for live exposure checks
- ✅ `prob_model`, `yes_ask`, `yes_bid`, `hours_to_settlement` carried through scan loop into entry dicts
- ✅ `'confidence'` added to crypto `opp` dict for logger
