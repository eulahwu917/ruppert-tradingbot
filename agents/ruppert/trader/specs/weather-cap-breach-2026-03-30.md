# Spec: Weather Daily Cap Breach — $989 Deployed vs $791 Cap
**Date:** 2026-03-30
**Author:** Data Scientist
**Status:** BUG — `_weather_deployed_this_cycle` resets to 0 each scan; prior-scan weather trades not counted

---

## Observed Breach

At the 3pm scan, weather module placed trades pushing total weather deployed to ~$989
against a daily cap of ~$791.

- Capital at scan time: $11,294.41
- `WEATHER_DAILY_CAP_PCT`: 0.07
- Daily cap = 0.07 × $11,294.41 = **$790.61 ≈ $791**
- Actual weather deployed after 3pm scan: **$989**
- Overage: **~$198**

`should_enter()` did not block entry. This spec documents why.

---

## Cap Calculation

The $791 cap is correct:
```python
# In agents/ruppert/trader/main.py, run_weather_scan():
_weather_daily_cap = total_capital * getattr(config, 'WEATHER_DAILY_CAP_PCT', 0.07)
# = $11,294.41 * 0.07 = $790.61
```

`WEATHER_DAILY_CAP_PCT = 0.07` is set in `environments/demo/config.py`.

---

## Root Cause: In-Cycle-Only Counter

The critical bug is in `run_weather_scan()` in `agents/ruppert/trader/main.py`:

```python
_weather_deployed_this_cycle = 0.0   # ← RESETS TO ZERO EVERY TIME run_weather_scan() IS CALLED

for opp in opportunities:
    # Per-module cap check: only counts trades placed in THIS invocation
    if _weather_deployed_this_cycle >= _weather_daily_cap:
        log_activity("  [DailyCap] STOP: weather budget exhausted ...")
        break

    signal = _opp_to_signal(opp, module='weather')
    signal['open_position_value'] = _open_exposure
    decision = should_enter(
        signal, total_capital, deployed_today,
        module='weather',
        module_deployed_pct=_weather_deployed_this_cycle / total_capital,  # ← ALSO IN-CYCLE-ONLY
        traded_tickers=traded_tickers,
    )
    if decision['enter']:
        if _weather_deployed_this_cycle + decision['size'] > _weather_daily_cap:
            log_activity(f"  [DailyCap] SKIP {opp['ticker']}: would exceed weather daily cap ...")
            continue
        ...
        _weather_deployed_this_cycle += decision['size']
```

`_weather_deployed_this_cycle` starts at 0.0 every call to `run_weather_scan()`. It only tracks trades placed **in the current scan invocation**, not the cumulative total deployed by the weather module for the entire day.

### What gets passed to `should_enter()` for the per-module cap:

```python
module_deployed_pct=_weather_deployed_this_cycle / total_capital  # e.g. 0 / $11,294 = 0.0
```

`should_enter()` then checks:
```python
_module_cap = getattr(config, 'WEATHER_DAILY_CAP_PCT', None)  # = 0.07
if module_deployed_pct >= _module_cap:  # 0.0 >= 0.07 → False → NOT BLOCKED
    return {'enter': False, ...}
```

So at the start of every scan, the per-module check in `should_enter()` always passes because
`module_deployed_pct` is always 0.0 at the first opportunity of each invocation.

---

## Why the Global Check Didn't Save It

The global daily cap check in `should_enter()`:
```python
room = check_daily_cap(capital, deployed_today)
if room <= 0:
    return {'enter': False, 'reason': 'daily_cap_reached'}
```

`deployed_today = get_daily_exposure()` — this is the **global** exposure across all modules.
The global daily cap is 70% of capital = $7,906. At 3pm, global deployed was well below 70%, so this
check passed without issue.

The early-exit guard at the top of `run_weather_scan()`:
```python
deployed_today = get_daily_exposure()
cap_remaining  = check_daily_cap(total_capital, deployed_today)  # 70% global check
if cap_remaining <= 0:
    return []
```
Also uses the 70% global cap — not the 7% weather-specific cap. This would not block weather
even if weather alone was over its 7% limit, as long as total global deployed was < 70%.

There is **no pre-scan check** at the top of `run_weather_scan()` that looks at cumulative
weather-only deployed vs the weather daily cap. The only weather-specific cap enforcement
happens inside the loop, and it only counts within the current cycle.

---

## Scenario Reconstruction

Assuming two weather scans ran before 3pm:

| Scan | Weather Deployed (this cycle) | Cumulative Weather Deployed | Weather Cap Check at entry |
|---|---|---|---|
| 9am | $400 (5 trades) | $400 | module_deployed_pct=0/0.07 → passes |
| 12pm | $390 (4 trades) | $790 | module_deployed_pct=0/0.07 → passes |
| 3pm | $199 (2 trades) | **$989** ← BREACH | module_deployed_pct=0/0.07 → passes |

At each scan, the weather cap check sees 0 prior-scan deployment and allows new trades.

---

## BEFORE (Current Behavior)

```python
# run_weather_scan():
_weather_deployed_this_cycle = 0.0   # always starts at 0

for opp in opportunities:
    if _weather_deployed_this_cycle >= _weather_daily_cap:  # 0.0 >= 790 → always False at scan start
        break
    ...
    decision = should_enter(..., module_deployed_pct=_weather_deployed_this_cycle / capital)
    # module_deployed_pct = 0/capital = 0.0 → per-module check in should_enter always passes
```

Result: weather cap is only enforced within a single scan invocation — across multiple scans
per day, cap is effectively multiplied by the number of scan invocations.

---

## AFTER (Proposed Fix)

Initialize `_weather_deployed_this_cycle` from the actual cumulative weather deployed today,
NOT from zero. Use `logger.get_daily_exposure(module='weather')` to get the prior-scan total.

```python
# run_weather_scan():
from agents.ruppert.data_scientist.logger import get_daily_exposure as _get_daily_exp

# Load cumulative weather deployed today (all prior scans + any open positions)
try:
    _weather_deployed_prior = _get_daily_exp(module='weather')
except Exception:
    _weather_deployed_prior = 0.0

_weather_deployed_this_cycle = _weather_deployed_prior  # ← start from cumulative, not 0

# Early-exit guard: if already at or over cap, skip entirely
if _weather_deployed_this_cycle >= _weather_daily_cap:
    log_activity(
        f"[Weather] Daily cap already reached: ${_weather_deployed_this_cycle:.2f} deployed "
        f"(cap ${_weather_daily_cap:.0f}). Skipping scan."
    )
    return []

for opp in opportunities:
    if _weather_deployed_this_cycle >= _weather_daily_cap:
        break
    signal = _opp_to_signal(opp, module='weather')
    signal['open_position_value'] = _open_exposure
    decision = should_enter(
        signal, total_capital, deployed_today,
        module='weather',
        module_deployed_pct=_weather_deployed_this_cycle / total_capital,  # now includes prior scans
        ...
    )
    if decision['enter']:
        if _weather_deployed_this_cycle + decision['size'] > _weather_daily_cap:
            continue
        ...
        _weather_deployed_this_cycle += decision['size']
```

`get_daily_exposure(module='weather')` already reads all trade files from start date forward
and correctly counts only open weather positions (those without an exit/settle record).

---

## Note on Interaction with logger.get_daily_exposure() Bug (Q2)

`logger.get_daily_exposure(module='weather')` has the same filter gap as the general version:
it includes weather positions that have expired by time but don't yet have settle records.
However, weather positions don't use time-embedded tickers (unlike crypto_15m), so
`is_settled_ticker()` would not apply to them. Weather positions only close via explicit
`exit` or `settle` records. The Q2 fix does not impact the weather module.

---

## Acceptance Criteria

1. At start of each `run_weather_scan()` invocation, cumulative prior-scan weather deployed
   is loaded from `logger.get_daily_exposure(module='weather')`
2. If prior deployed ≥ `_weather_daily_cap`, scan returns immediately with no trades
3. Per-opportunity checks use the cumulative deployed, not just in-cycle deployed
4. `module_deployed_pct` passed to `should_enter()` reflects cumulative deployed / capital
5. No weather scan can breach the WEATHER_DAILY_CAP_PCT limit unless each individual trade
   passes the budget check against the correct cumulative total

---

## Files to Change

- `agents/ruppert/trader/main.py` — `run_weather_scan()` function (~lines 147–360)
- Specifically: initialization of `_weather_deployed_this_cycle` and early-exit guard

## Related Modules to Audit

The same pattern exists for all other modules. Confirm whether crypto (`run_crypto_scan`),
geo (`run_geo_scan`), fed (`run_fed_scan`) have the same in-cycle-only counter pattern.
If so, identical fix should be applied to each.
