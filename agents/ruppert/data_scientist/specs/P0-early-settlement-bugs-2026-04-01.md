# P0 DEV SPEC: Early Settlement Bugs in position_tracker.py

**Priority:** P0 — live positions being force-settled as full losses
**File:** `agents/ruppert/trader/position_tracker.py`
**Author:** Data Scientist (Ruppert)
**Date:** 2026-04-01

---

## Summary

Two bugs in `position_tracker.py`'s `check_expired()` function cause live positions to be incorrectly settled as full losses. The timezone bug settles positions ~4 hours early; the empty-string bug settles unsettled markets at 0c.

---

## Bug 1: Timezone Mismatch — EST Parsed as UTC

### Location
`position_tracker.py` lines 673-674

### Current Code (WRONG)
```python
# Line 673-674
open_dt = datetime(yr, mon, dd, hh, mm, tzinfo=timezone.utc)
close_dt = open_dt + timedelta(minutes=15)
```

### Problem
Kalshi ticker timestamps encode the close time in **EST (America/New_York)**, not UTC. The code treats the raw digits as UTC, making `close_dt` 4 hours too early (5 hours during EST, 4 during EDT). This causes the `if now_utc < close_dt: continue` guard at line 678 to pass prematurely, triggering REST settlement verification on still-live contracts.

`crypto_15m.py` (lines 906-911) already handles this correctly:
```python
est = pytz.timezone('America/New_York')
close_est = est.localize(datetime(yr, mon, day, hour, minute))
close_dt = close_est.astimezone(timezone.utc)
```

### Fix
Replace lines 673-674 with:
```python
import pytz
est = pytz.timezone('America/New_York')
# Ticker encodes the CLOSE time in EST
close_est = est.localize(datetime(yr, mon, dd, hh, mm))
close_dt = close_est.astimezone(timezone.utc)
# No need to add 15 minutes — the ticker already encodes close time
```

**Note:** The `import pytz` should be added at the top of the file with other imports. `pytz` is already a project dependency (used in `crypto_15m.py`).

### Also Fix: Same Bug in Time-to-Expiry Stop-Loss (lines 376-377)
The same timezone bug exists in the crypto_15m_dir stop-loss block:
```python
# Line 376-377 — ALSO WRONG
_open_dt = datetime(_yr, _mon, _dd, _hh, _mm, tzinfo=timezone.utc)
_close_dt = _open_dt + timedelta(minutes=15)
```
Apply the same EST-to-UTC conversion here.

---

## Bug 2: Empty String Bypasses None Check

### Location
`position_tracker.py` line 689

### Current Code (WRONG)
```python
# Line 688-689
result = market.get('result')
if result is None:
    continue  # not yet settled, retry next cycle
```

### Problem
When the Kalshi API returns `result: ""` (empty string) for an unsettled market, the `is None` check does not catch it. The empty string falls through to line 700-702:
```python
if side == 'yes':
    settlement_price = 100 if result == 'yes' else 0
```
Since `"" != 'yes'`, the settlement price is set to **0c**, and the position is closed as a total loss.

### Fix
Replace line 689:
```python
# Before (line 689):
if result is None:

# After:
if not result:
```

This catches both `None` and `""` (empty string), correctly skipping unsettled markets.

---

## Test Plan

1. **Bug 1:** Create a ticker with EST close time in the future (e.g., 14:00 EST = 18:00 UTC). Verify `check_expired()` does NOT attempt settlement before 18:00 UTC.
2. **Bug 2:** Mock `client.get_market()` to return `{'result': ''}`. Verify the position is NOT settled and the loop continues.
3. **Regression:** Verify that positions with `result='yes'` and `result='no'` still settle correctly.
4. **Stop-loss block (lines 376-377):** Verify the time-to-expiry stop-loss fires at the correct UTC time after the fix.
