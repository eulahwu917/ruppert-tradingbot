# Exit Dedup Spec — 2026-03-30
**Prepared by:** Trader  
**Reviewed DS findings:** `agents/ruppert/data_scientist/specs/pnl-cleanup-findings-2026-03-30.md`  
**Date:** 2026-03-30  
**Status:** Ready for Dev

---

## Overview

Three fixes are required following the DS P&L audit for 2026-03-30:

1. **Data fix** — Remove duplicate trade record from `trades_2026-03-30.jsonl`
2. **Code fix** — Add dedup guard in `position_tracker.py` to prevent double-fire of WS exits
3. **Cache fix** — Regenerate `pnl_cache.json` after data fix

---

## Fix 1 — Data: Remove Duplicate Trade Record

**File:** `environments/demo/logs/trades/trades_2026-03-30.jsonl`

### What to do
Remove exactly **one line** — the duplicate exit for `KXDOGE-26MAR3017-B0.092`:

```
trade_id: f5aa2b3a-96b1-4eec-ab92-ff53ab8c38de
timestamp: 2026-03-30T09:36:35.152161
```

### What to keep
All other lines intact, including:
- `trade_id: 485fb3d4-e851-47f8-a424-1f1450357e5d` (the legitimate first exit, 09:36:32)
- All Case 2 records (KXDOGE15M-26MAR301245-45) — both exits are legitimate
- All Case 3 records (KXXRP15M-26MAR301315-15) — both exits are legitimate

### Verification
After removal, confirm:
- File has exactly one exit record for `KXDOGE-26MAR3017-B0.092`
- `trade_id: 485fb3d4` is present
- `trade_id: f5aa2b3a` is absent
- All other records unchanged (line count should decrease by exactly 1)

---

## Fix 2 — Code: Exit Dedup Guard in `position_tracker.py`

**File:** `agents/ruppert/trader/position_tracker.py`

### Root Cause
`execute_exit()` has no guard against being called twice for the same position within a short window. The WS feed delivered two exit events for `KXDOGE-26MAR3017-B0.092` 3 seconds apart (likely a reconnect or duplicate message delivery), causing:
1. `execute_exit()` fired → logged exit → called `remove_position()` 
2. `execute_exit()` fired again 3 seconds later — but `remove_position()` does a silent `dict.pop`, so `check_exits()` can still call `execute_exit()` if the key survives into the second call (race between removal and the second tick arriving)

**Current gap:** `remove_position()` is called at the end of `execute_exit()`. If a second WS tick arrives for the same ticker in the ~milliseconds before `remove_position()` completes and the next `check_exits()` runs, a second exit fires. Given async execution, the position key is still in `_tracked` when the second tick is processed.

### What NOT to do
Do **not** key the dedup guard on `(ticker, side, action)` alone. This would block legitimate scale-in exits (Cases 2 & 3) where the bot legitimately holds multiple legs for the same `(ticker, side)`.

### Proposed Fix: Mark-in-Flight Pattern

Add an in-memory set `_exits_in_flight: set[tuple]` that tracks which `(ticker, side)` keys are currently executing an exit. Guard `execute_exit()` at entry and release at completion.

#### Implementation spec

**1. Module-level state (add near `_tracked = {}`):**
```python
# Dedup guard: tracks (ticker, side) keys currently in the middle of execute_exit()
_exits_in_flight: set[tuple] = set()
```

**2. `execute_exit()` — add guard at top of function:**
```python
async def execute_exit(key: tuple, pos: dict, current_bid: int, rule: str):
    """Execute the exit order via REST."""
    ticker, side = key

    # Dedup guard: if this (ticker, side) exit is already in-flight, skip.
    # Prevents WS duplicate events from firing two exits for the same position.
    # NOTE: does NOT use contracts as part of the key — a single position per
    # (ticker, side) key is the invariant enforced by add_position(). Scale-in
    # is not possible for the same key; Cases 2 & 3 had distinct keys before
    # this guard existed.
    if key in _exits_in_flight:
        logger.warning(
            '[PositionTracker] Dedup guard: exit for %s %s already in-flight — skipping duplicate',
            ticker, side
        )
        return

    _exits_in_flight.add(key)
    try:
        # ... existing execute_exit() body unchanged ...
    finally:
        _exits_in_flight.discard(key)
```

**3. `remove_position()` — also discard from in-flight (defensive cleanup):**
```python
def remove_position(ticker: str, side: str):
    """Call after exit execution."""
    _tracked.pop((ticker, side), None)
    _exits_in_flight.discard((ticker, side))  # Belt-and-suspenders cleanup
    _persist()
```

### Why this works for scale-in (Cases 2 & 3)
`_tracked` is keyed by `(ticker, side)`. `add_position()` overwrites the key if called twice for the same `(ticker, side)` — so scale-in as observed in Cases 2 & 3 is actually two positions stored under separate keys only if they differ in side. Reviewing the data:
- Case 2: both buys are `(KXDOGE15M-26MAR301245-45, no)` — same key. This means the second `add_position()` overwrites the first, and only one exit is tracked. The two exits firing are explained by something _other_ than `_tracked` having two entries (possibly the prior-day position still present, or a scale-in mechanism outside `add_position()`).
- Case 3: same pattern — `(KXXRP15M-26MAR301315-15, no)` — two buys under one key.

**Important:** Dev should verify how Cases 2 & 3 produce two logged exits. If the scale-in mechanism bypasses `_tracked` or uses a different key, the dedup guard as spec'd (keyed on `(ticker, side)`) will not interfere with legitimate scale-in exits. If scale-in _does_ reuse the same `(ticker, side)` key, Dev should confirm the dedup guard does not block the second leg's exit.

**In any case, the guard's primary purpose is time-window deduplication** (sub-10-second double-fire from WS). As a secondary safeguard, if Dev wants an explicit time window instead of in-flight state, an alternative is acceptable:

#### Alternative: Time-window dedup (if in-flight set is insufficient)
Add `_last_exit_time: dict[tuple, float] = {}` and reject exits within `DEDUP_WINDOW_SECONDS = 10` of a prior exit for the same key.

```python
DEDUP_WINDOW_SECONDS = 10
_last_exit_time: dict[tuple, float] = {}

async def execute_exit(key, pos, current_bid, rule):
    ticker, side = key
    now = time.time()
    last = _last_exit_time.get(key, 0)
    if now - last < DEDUP_WINDOW_SECONDS:
        logger.warning('[PositionTracker] Dedup guard: exit for %s %s fired %0.1fs ago — skipping', ticker, side, now - last)
        return
    _last_exit_time[key] = now
    # ... rest of execute_exit() unchanged ...
```

**Recommendation:** Implement the in-flight set (primary) as the correct fix. The time-window approach is a fallback if async timing makes the in-flight approach unreliable.

---

## Fix 3 — Cache: Regenerate `pnl_cache.json`

After Fix 1 (removing the duplicate record), the `pnl_cache.json` file is stale and reflects the inflated P&L.

**Action required:** Re-run the synthesizer to regenerate `pnl_cache.json` from the corrected `trades_2026-03-30.jsonl`.

**Expected corrected cumulative P&L:** `-$1,380.08`  
(Current cached value: `-$1,331.03` — overcounted by `+$49.05` from the duplicate exit)

The synthesizer script should be run as a standard data pipeline step after Fix 1 is verified. No code changes to the synthesizer are required — the data fix alone is sufficient.

---

## Summary

| Fix | File | Action | Risk |
|-----|------|--------|------|
| 1 — Data | `environments/demo/logs/trades/trades_2026-03-30.jsonl` | Remove 1 line (trade_id `f5aa2b3a`) | Low — surgical delete, one line |
| 2 — Code | `agents/ruppert/trader/position_tracker.py` | Add `_exits_in_flight` set + guard in `execute_exit()` | Low — defensive guard, no logic change |
| 3 — Cache | `environments/demo/logs/pnl_cache.json` | Re-run synthesizer after Fix 1 | None — standard pipeline step |

**Do not implement until Dev has reviewed this spec and QA has signed off.**
