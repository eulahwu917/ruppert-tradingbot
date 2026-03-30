# Spec: Tracker Sync — Remove Pre-Fix Settled Positions
**Date:** 2026-03-30  
**Author:** Trader (subagent investigation)  
**Status:** Awaiting Dev implementation

---

## Problem Summary

10 crypto_15m positions entered 09:46–11:17 PDT are stuck in `tracked_positions.json` even though they have valid `settle` records in `trades_2026-03-30.jsonl`. The WebSocket position tracker is monitoring them uselessly, and they pollute any display of "open positions."

---

## Root Cause (Confirmed)

### 1. The fix in `post_trade_monitor.py` is correctly placed

Commit `3905a4c` added `position_tracker.remove_position(ticker, side)` **after** the settle record write and **outside** any `continue` path. The placement is correct — it will work for all positions settled from now on.

```python
# post_trade_monitor.py — check_settlements() — confirmed correct order:
try:
    with open(log_path, 'a', ...) as f:
        f.write(json.dumps(settle_record) + '\n')   # 1. write settle record
except Exception as e:
    ...
    continue   # only continue on write FAILURE

log_event(...)       # 2. log event
print(...)           # 3. console output
settled_count += 1   # 4. increment counter

try:
    position_tracker.remove_position(ticker, side)  # 5. ← CORRECTLY placed after write
except Exception as _pt_err:
    ...
```

### 2. The 10 stuck positions settled BEFORE the fix was committed

These positions were settled at ~11:23–11:36 PDT by a `check_settlements()` run that predates commit `3905a4c` (~11:50 PDT). At the time of that settlement run, `remove_position()` did not exist in the code. The settle records were written correctly; the tracker removal was never called.

**Confirmed settle records exist for these 10 tickers:**

| Ticker | Side | Settled At | Result | P&L |
|--------|------|------------|--------|-----|
| KXBTC15M-26MAR301300-00 | yes | 11:23:54 | LOSS | -$78.12 |
| KXETH15M-26MAR301300-00 | yes | 11:23:55 | LOSS | -$78.12 |
| KXBTC15M-26MAR301315-15 | yes | 11:23:55 | LOSS | -$20.16 |
| KXETH15M-26MAR301330-30 | yes | 11:23:56 | LOSS | -$83.16 |
| KXBTC15M-26MAR301330-30 | yes | 11:23:56 | LOSS | -$83.15 |
| KXBTC15M-26MAR301415-15 | yes | 11:23:57 | LOSS | -$83.07 |
| KXXRP15M-26MAR301415-15 | yes | 11:23:58 | LOSS | -$83.16 |
| KXDOGE15M-26MAR301430-30 | yes | 11:36:54 | LOSS | -$82.80 |
| KXXRP15M-26MAR301430-30 | yes | 11:36:55 | LOSS | -$83.05 |
| KXBTC15M-26MAR301430-30 | yes | 11:36:56 | LOSS | -$82.95 |

*(Note: KXETH15M-26MAR301430-30 and the four 1445-45 positions were settled in later runs and are NOT stuck — they were already post-fix or handled by the 12:16 run after the fix.)*

### 3. Why re-running the settlement checker doesn't fix it

`check_settlements()` builds `exit_keys` from all `settle` and `exit` records. Any position with an existing settle record is excluded from `open_positions` before the loop even starts. The checker will never re-process these 10 positions and therefore `remove_position()` will never be called for them via this path.

---

## Fix Specification

### Approach: Startup tracker sync in `check_settlements()`

Add a **tracker sync sweep** at the top of `check_settlements()`, before any other logic. The sweep reads the same trade logs already being scanned and removes from the tracker any position whose `(ticker, side)` key already has a `settle` record.

This is idempotent, cheap (no API calls), and self-healing — it will clean up any future cases where tracker removal was missed, regardless of cause.

### Where to add it

In `check_settlements(client)` in `post_trade_monitor.py`, immediately after the existing log-scanning loop that builds `entries_by_key`, `exit_keys`, and `settle_keys`.

`settle_keys` is already computed in the existing loop (lines that check `if action == 'settle': settle_keys.add(key)`) — it just isn't used yet.

### Logic

```python
# After the existing log-scan loop, before open_positions is used:

# Sync tracker: remove any position that already has a settle record.
# This handles positions settled before remove_position() was in place.
synced = 0
for key in settle_keys:
    ticker_s, side_s = key
    try:
        removed = position_tracker.remove_position(ticker_s, side_s)
        # remove_position() uses .pop() — it's a no-op if key isn't in tracker
        # We want to know if it was actually in the tracker to log meaningfully.
        # Option: check tracker BEFORE calling remove, or just always call it silently.
        synced += 1
    except Exception as _sync_err:
        print(f"  [Settlement Checker] WARN: tracker sync failed for {ticker_s} {side_s}: {_sync_err}")

if synced > 0:
    print(f"  [Settlement Checker] tracker sync: removed {synced} already-settled position(s) from tracker")
```

> **Note to Dev:** `position_tracker.remove_position()` is a no-op (`.pop()` on missing key) so this is safe to call for all settle keys, not just those currently in the tracker. However, if you want to log only actual removals (to avoid misleading counts), check `position_tracker.get_positions()` first to see which keys are present before calling remove. Either approach is acceptable.

### Placement in `check_settlements()`

```
check_settlements(client):
    [existing] scan logs → build entries_by_key, exit_keys, settle_keys
    [NEW] tracker sync sweep using settle_keys          ← ADD HERE
    [existing] build open_positions
    [existing] for pos in open_positions: ... settle ... remove_position()
```

### Alternative considered: one-shot cleanup script

A standalone script that reads the JSONL log and manually calls `remove_position()` for the 10 stuck tickers would fix today's problem. Rejected because:
- It's a one-time bandage, not a systemic fix
- The startup sync approach prevents recurrence automatically
- No additional code surface to maintain

---

## Acceptance Criteria

1. After the fix is deployed, running `post_trade_monitor.py` removes all 10 stuck crypto_15m positions from `tracked_positions.json` on the next execution.
2. Subsequent runs are idempotent — calling `remove_position()` on already-removed keys does not raise exceptions or log spurious warnings.
3. The sync log line (`tracker sync: removed N already-settled position(s)`) appears when stuck entries are found, and does NOT appear (or appears with N=0) once they are gone.
4. Positions with no settle record are unaffected.

---

## Files to Modify

- `agents/ruppert/trader/post_trade_monitor.py` — `check_settlements()` function only

## Files NOT to Modify

- `agents/ruppert/trader/position_tracker.py` — no changes needed
- Any JSONL trade logs — do not retroactively edit records
