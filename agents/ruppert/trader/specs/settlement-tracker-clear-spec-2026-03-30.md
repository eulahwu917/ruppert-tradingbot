# Bug Fix Spec: Settlement Checker Must Remove Positions from Tracker

**Date:** 2026-03-30  
**File:** `agents/ruppert/trader/post_trade_monitor.py`  
**Function:** `check_settlements()`  
**Severity:** High — settled positions stay stuck as "open" in `tracked_positions.json` indefinitely  

---

## Bug Confirmed

### What happens today

After `check_settlements()` resolves a position (writes a `"settle"` record to the JSONL trade log), it does **not** call `position_tracker.remove_position()`.

The WS-driven `position_tracker` (`tracked_positions.json`) is completely unaware that the position settled. The position remains in the in-memory `_tracked` dict and on disk as "open", showing stale prices on the dashboard until the process restarts or a manual intervention occurs.

### Root cause

`check_settlements()` correctly builds `exit_keys` from the JSONL logs (it scans `action == 'settle'` entries), but it only uses that to filter positions out of its own local `open_positions` list. It never tells `position_tracker` to remove the position from `tracked_positions.json`.

---

## Investigation Details

### `check_settlements()` — what it does after settling

After writing the settle record (lines ~219–234 in `post_trade_monitor.py`), the function:

1. Calls `log_event('SETTLEMENT', ...)` ✅
2. Prints a summary line ✅
3. Increments `settled_count` ✅
4. ❌ **Does NOT call `position_tracker.remove_position(ticker, side)`**

### `position_tracker.remove_position()` — confirmed signature

```python
# position_tracker.py, line ~107
def remove_position(ticker: str, side: str):
    """Call after exit execution."""
    _tracked.pop((ticker, side), None)
    _persist()
```

**Args:** `ticker: str`, `side: str`  
**Effect:** removes `(ticker, side)` key from `_tracked` dict and writes updated state to `tracked_positions.json`  
**Safe to call if key doesn't exist** — uses `.pop(..., None)`, no KeyError raised.

### Is there any other place that clears settled positions from the tracker?

- `execute_exit()` in `position_tracker.py` calls `remove_position()` after a WS-triggered exit ✅ — but this path is only reached by the WS feed, not by the settlement checker.
- The `load_open_positions()` function in `post_trade_monitor.py` filters settled positions from its own return value, but this is a local filter — it does **not** mutate `tracked_positions.json`.
- There is no periodic sweep or cleanup job that removes settled positions from the tracker.

**Conclusion:** `check_settlements()` is the correct and only place to add this call.

---

## Import Requirement

`post_trade_monitor.py` does **not** currently import `position_tracker`. The import must be added.

---

## Fix Spec

### Change 1 — Add import near top of file

**Location:** `post_trade_monitor.py`, after the existing imports block (after the `from agents.ruppert.data_scientist.logger import ...` line, ~line 38)

**BEFORE:**
```python
from agents.ruppert.data_scientist.logger import log_trade, log_activity, acquire_exit_lock, release_exit_lock, normalize_entry_price
```

**AFTER:**
```python
from agents.ruppert.data_scientist.logger import log_trade, log_activity, acquire_exit_lock, release_exit_lock, normalize_entry_price
from agents.ruppert.trader import position_tracker
```

---

### Change 2 — Call `remove_position()` after writing the settle record

**Location:** `post_trade_monitor.py`, inside `check_settlements()`, immediately after the `log_event('SETTLEMENT', ...)` call and the print line.

**BEFORE:**
```python
        log_event('SETTLEMENT', {
            'ticker': ticker,
            'side': side,
            'result': result,
            'pnl': round(pnl, 2),
            'entry_price': entry_price,
            'exit_price': exit_price,
            'contracts': contracts,
        })
        print(f"  [Settlement] {ticker} {side.upper()} → {result.upper()} | P&L=${pnl:+.2f}")
        settled_count += 1
```

**AFTER:**
```python
        log_event('SETTLEMENT', {
            'ticker': ticker,
            'side': side,
            'result': result,
            'pnl': round(pnl, 2),
            'entry_price': entry_price,
            'exit_price': exit_price,
            'contracts': contracts,
        })
        print(f"  [Settlement] {ticker} {side.upper()} → {result.upper()} | P&L=${pnl:+.2f}")
        settled_count += 1

        # Remove from WS position tracker so it no longer shows as open
        try:
            position_tracker.remove_position(ticker, side)
        except Exception as _pt_err:
            print(f"  [Settlement Checker] WARN: could not remove {ticker} {side} from tracker: {_pt_err}")
```

---

## Notes for Dev

- The `try/except` wrapper is intentional. `remove_position()` is safe to call for non-tracked tickers (no-op), but defensive error handling prevents a tracker failure from aborting the rest of the settlement loop.
- No changes needed to `position_tracker.py` — `remove_position(ticker, side)` already handles missing keys gracefully.
- The `settled_count += 1` line stays in the same position — it counts JSONL writes, not tracker removals.
- This fix covers both DRY_RUN and live modes since `position_tracker` is mode-agnostic.

---

## Not In Scope

- Backfilling already-stuck positions in `tracked_positions.json` (manual cleanup or separate one-shot script, not part of this fix).
- Changes to `ws_feed.py` or `position_tracker.py`.
