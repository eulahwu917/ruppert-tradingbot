# Spec: Daily Cap Reset Bug — Weather, Crypto, Fed, Geo Scans
**Date:** 2026-03-30
**Author:** Trader
**Status:** BUG — All four scan functions initialize their deployed counter at 0.0 per invocation instead of loading cumulative daily exposure from logs

---

## Summary

`run_weather_scan()`, `run_crypto_scan()`, `run_fed_scan()`, and `run_geo_trades()` in
`agents/ruppert/trader/main.py` each initialize a local `_X_deployed_this_cycle = 0.0`
variable on every invocation. This means each scan starts with a false zero, allowing the
per-module daily cap to be breached whenever a module runs more than once per day.

A standalone spec (`weather-cap-breach-2026-03-30.md`) documents the observed breach for
weather on 2026-03-30. This spec covers all four affected modules with exact code references
and the uniform fix pattern.

---

## Affected Code — Exact Variables and Approximate Lines

All locations are in `agents/ruppert/trader/main.py`.

### 1. Weather — `run_weather_scan()` (starts ~line 147)

```python
# ~line 260 (inside the opportunity loop setup)
_weather_deployed_this_cycle = 0.0
```

Cap guard (inside loop):
```python
if _weather_deployed_this_cycle >= _weather_daily_cap:
    log_activity(
        f"  [DailyCap] STOP: weather budget ${_weather_daily_cap:.0f} "
        f"exhausted (${_weather_deployed_this_cycle:.2f} deployed this cycle)"
    )
    break
```

`module_deployed_pct` passed to `should_enter()`:
```python
module_deployed_pct=_weather_deployed_this_cycle / total_capital if total_capital > 0 else 0.0,
```

---

### 2. Crypto — `run_crypto_scan()` (starts ~line 386)

```python
# ~line 553 (after cap check block)
_crypto_deployed_this_cycle = 0.0
```

Cap guard (inside loop):
```python
if _crypto_deployed_this_cycle >= _crypto_daily_cap:
    print(f"  [DailyCap] STOP: crypto budget ${_crypto_daily_cap:.0f} exhausted")
    break
```

`module_deployed_pct` passed to `should_enter()`:
```python
module_deployed_pct=_crypto_deployed_this_cycle / _total_capital if _total_capital > 0 else 0.0,
```

---

### 3. Fed — `run_fed_scan()` (starts ~line 663)

```python
# ~line 680 (after fed_signal is obtained, before the trade block)
_fed_deployed_this_cycle = 0.0
```

Used in `module_deployed_pct`:
```python
_fed_deployed_pct = _fed_deployed_this_cycle / _fed_capital if _fed_capital > 0 else 0.0
```

Per-trade guard (not a loop guard; single-trade module):
```python
elif _fed_decision['size'] > _fed_daily_cap:
    print(f"  [DailyCap] SKIP {ticker}: would exceed fed/econ daily cap")
```

Note: Fed is a single-trade module (one signal per scan), so the reset is less likely to
breach on its own. However, if the bot restarts mid-day and runs `run_fed_scan()` again, the
`_fed_deployed_this_cycle` starts at 0.0 and `module_deployed_pct = 0.0`, allowing a second
fed trade even if one was already placed earlier.

---

### 4. Geo — `run_geo_trades()` (starts ~line 835)

```python
# ~line 862 (after _geo_daily_cap is computed)
_geo_deployed_this_cycle = 0.0
```

Cap guard (inside loop):
```python
if _geo_deployed_this_cycle >= _geo_daily_cap:
    log_activity(f"  [DailyCap] STOP: geo budget ${_geo_daily_cap:.0f} exhausted")
    break
```

`module_deployed_pct` passed to `should_enter()`:
```python
module_deployed_pct=_geo_deployed_this_cycle / _geo_capital if _geo_capital > 0 else 0.0,
```

---

## Root Cause

The daily cap enforcement loop uses an **in-cycle-only counter** that is never seeded from
historical trade data. Each invocation of a scan function is blind to all prior-scan trades.

### Why `should_enter()` also fails to catch it

`should_enter()` receives `module_deployed_pct` as a parameter. Because this parameter is
always `0.0` (or near zero) at the start of each invocation, `should_enter()`'s module cap
check always passes:

```python
# In strategy.py / should_enter():
_module_cap = getattr(config, f'{module.upper()}_DAILY_CAP_PCT', None)
if module_deployed_pct >= _module_cap:  # 0.0 >= 0.07 → always False at scan start
    return {'enter': False, 'reason': 'module_daily_cap_reached'}
```

### Why the global cap check at the top of each function doesn't save it

The early-exit guard at the top of each scan uses the **global 70% cap**, not the module cap:

```python
# run_weather_scan() top:
deployed_today = get_daily_exposure()
cap_remaining  = check_daily_cap(total_capital, deployed_today)  # 70% global check
if cap_remaining <= 0:
    return []
```

A module can be over its own cap (e.g. weather at 14% of capital) while the global is still
under 70%. The top-of-function guard does not catch per-module overruns.

---

## BEFORE (Current Behavior — All Four Modules)

```
Scan invocation 1 (e.g. 9am):
  _X_deployed_this_cycle = 0.0        ← starts at 0
  → places $N in module X
  → _X_deployed_this_cycle accumulates to $N by end of scan
  → scan ends; counter is garbage-collected

Scan invocation 2 (e.g. 12pm):
  _X_deployed_this_cycle = 0.0        ← resets to 0; prior $N invisible
  → module_deployed_pct = 0/capital = 0.0
  → should_enter() module cap check: 0.0 >= cap_pct → False → PASSES
  → per-loop guard: 0.0 >= module_daily_cap → False → PASSES
  → places another $N; total = 2×N (may exceed daily cap)

Scan invocation 3 (e.g. 3pm):
  _X_deployed_this_cycle = 0.0        ← resets again
  → same pattern; cap continues to multiply with each scan
```

**Effect:** Per-module daily cap is effectively multiplied by the number of scan
invocations per day. If a module runs 3× per day, its cap is 3× what is configured.

---

## AFTER (Proposed Fix — Uniform Pattern for All Four Modules)

At the top of each scan function, after `_X_daily_cap` is computed, load cumulative
prior-scan deployed from the logger and seed the counter from that value. Add an early-exit
guard before the trading loop.

### Weather fix (`run_weather_scan()`)

```python
# CHANGE: seed _weather_deployed_this_cycle from cumulative logger data
try:
    from agents.ruppert.data_scientist.logger import get_daily_exposure as _get_daily_exp
    _weather_deployed_this_cycle = _get_daily_exp(module='weather')
except Exception:
    _weather_deployed_this_cycle = 0.0

# ADD: early-exit guard before entering the opportunity loop
if _weather_deployed_this_cycle >= _weather_daily_cap:
    log_activity(
        f"[Weather] Daily cap already reached: ${_weather_deployed_this_cycle:.2f} deployed "
        f"(cap ${_weather_daily_cap:.0f}). Skipping scan."
    )
    return []
```

### Crypto fix (`run_crypto_scan()`)

```python
# CHANGE: seed _crypto_deployed_this_cycle from cumulative logger data
try:
    from agents.ruppert.data_scientist.logger import get_daily_exposure as _get_daily_exp
    _crypto_deployed_this_cycle = _get_daily_exp(module='crypto')
except Exception:
    _crypto_deployed_this_cycle = 0.0

# ADD: early-exit guard before the trading loop
if _crypto_deployed_this_cycle >= _crypto_daily_cap:
    print(f"  [DailyCap] Crypto daily cap already reached: ${_crypto_deployed_this_cycle:.2f} deployed "
          f"(cap ${_crypto_daily_cap:.0f}). Skipping scan.")
    return []
```

### Fed fix (`run_fed_scan()`)

```python
# CHANGE: seed _fed_deployed_this_cycle from cumulative logger data
try:
    from agents.ruppert.data_scientist.logger import get_daily_exposure as _get_daily_exp
    _fed_deployed_this_cycle = _get_daily_exp(module='fed')
except Exception:
    _fed_deployed_this_cycle = 0.0

# ADD: early-exit guard before the trade block
if _fed_deployed_this_cycle >= _fed_daily_cap:
    print(f"  [DailyCap] Fed daily cap already reached: ${_fed_deployed_this_cycle:.2f} deployed "
          f"(cap ${_fed_daily_cap:.0f}). Skipping scan.")
    return []
```

### Geo fix (`run_geo_trades()`)

```python
# CHANGE: seed _geo_deployed_this_cycle from cumulative logger data
try:
    from agents.ruppert.data_scientist.logger import get_daily_exposure as _get_daily_exp
    _geo_deployed_this_cycle = _get_daily_exp(module='geo')
except Exception:
    _geo_deployed_this_cycle = 0.0

# ADD: early-exit guard before the opportunity loop
if _geo_deployed_this_cycle >= _geo_daily_cap:
    log_activity(
        f"[Geo] Daily cap already reached: ${_geo_deployed_this_cycle:.2f} deployed "
        f"(cap ${_geo_daily_cap:.0f}). Skipping scan."
    )
    return executed
```

### Key properties of the fix (all modules):

1. `get_daily_exposure(module='X')` reads all trade files from 2026-03-26 forward and
   returns the sum of open (non-exited, non-settled) positions for that module. This is
   already the correct source of truth used by capital.py for deployed reporting.

2. The counter is seeded **before** the trading loop, so `module_deployed_pct` passed to
   `should_enter()` reflects cumulative deployment from the first opportunity evaluated.

3. The early-exit guard short-circuits the entire scan if the module cap is already
   exhausted — no opportunities are evaluated, no orders attempted.

4. In-loop guards remain unchanged; they now enforce correctly against the cumulative total.

---

## Module Cap Values (reference)

| Module  | Config Key              | Default | Notes                                    |
|---------|-------------------------|---------|------------------------------------------|
| Weather | `WEATHER_DAILY_CAP_PCT` | 0.07    | 7% of capital per day                    |
| Crypto  | `CRYPTO_DAILY_CAP_PCT`  | 0.07    | 7% of capital per day                    |
| Fed     | `FED_DAILY_CAP_PCT`     | 0.03    | 3% of capital; single-trade module       |
| Geo     | `GEO_DAILY_CAP_PCT`     | 0.04    | 4% of capital; requires `GEO_AUTO_TRADE` |

---

## Acceptance Criteria

1. At the start of each scan invocation, the module's deployed counter reflects **all prior
   trades for that module since bot launch** (not just trades in the current invocation).
2. If `_X_deployed_this_cycle >= _X_daily_cap` before the loop begins, the scan returns
   immediately with no trades placed.
3. `module_deployed_pct` passed to `should_enter()` on the first opportunity equals
   `get_daily_exposure(module='X') / capital`, not `0 / capital`.
4. A module that placed trades at 9am and 12am will correctly be blocked at 3pm if
   cumulative deployed ≥ module daily cap.
5. No regression: a module that has not placed any trades today (`get_daily_exposure(module='X') == 0.0`)
   behaves identically to the current implementation.
6. Exception in `get_daily_exposure()` falls back to `0.0` (preserves current behavior on
   logger failure) — do NOT let a logger error silently block all trading.

---

## Files to Change

- `agents/ruppert/trader/main.py`
  - `run_weather_scan()` — seed `_weather_deployed_this_cycle`; add early-exit guard
  - `run_crypto_scan()` — seed `_crypto_deployed_this_cycle`; add early-exit guard
  - `run_fed_scan()` — seed `_fed_deployed_this_cycle`; add early-exit guard
  - `run_geo_trades()` — seed `_geo_deployed_this_cycle`; add early-exit guard

No changes required to `logger.py`, `strategy.py`, or `config.py`.

---

## Related Specs

- `weather-cap-breach-2026-03-30.md` — specific breach incident that surfaced this pattern
- `deployed-discrepancy-2026-03-30.md` — separate bug: notification vs dashboard deployed
  discrepancy (crypto_15m settled positions; does not affect this fix)
