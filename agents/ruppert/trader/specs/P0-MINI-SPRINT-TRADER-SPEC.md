# P0 Mini-Sprint — Trader Spec
**Date:** 2026-04-03  
**Authored by:** Trader  
**Issues:** ISSUE-117, ISSUE-034  
**Reviewer:** David (please review before Dev starts)

---

## Overview

Two P0 bugs. Both are pre-condition to any P1 work — one silently fires full Kelly on missing vol data, the other leaves positions unmonitored by crashing before the polling fallback runs. Neither is subtle. Both need to be fixed before anything else.

Files touched:
- `agents/ruppert/strategist/strategy.py` — ISSUE-117
- `agents/ruppert/trader/position_monitor.py` — ISSUE-034

---

## ISSUE-117 — vol_ratio=0 Bypasses Kelly Shrinkage → Full Unscaled Position

**File:** `agents/ruppert/strategist/strategy.py`  
**Function:** `calculate_position_size()`

### What the bug is

The vol shrinkage block in `calculate_position_size()` reads:

```python
# Vol adjustment: high vol → smaller position
if vol_ratio > 0:
    kelly_size *= (1.0 / vol_ratio)
```

When `vol_ratio=0` (passed in because vol data is missing upstream), the condition is False. The shrinkage block is **skipped entirely**. The function continues, applies the position cap, and returns the full unscaled Kelly size as if vol_ratio were 1.0.

This is the wrong behavior. `vol_ratio=0` does not mean "normal vol." It means "we have no vol data." A trade with missing vol data should be skipped, not executed at full Kelly.

The bug is also present in `should_enter()`, which passes `vol_ratio` from the signal dict through to `calculate_position_size()`. If the signal's `vol_ratio` key is missing, `signal.get('vol_ratio', 1.0)` returns 1.0 (safe default). But if the caller explicitly passes `vol_ratio=0` — which is what happens when the vol computation returns zero due to missing data — the zero flows straight through unchecked.

### What the fix is

Add an explicit guard for `vol_ratio <= 0` at the top of the vol adjustment block in `calculate_position_size()`, **before** the `if vol_ratio > 0:` line:

```python
# Vol adjustment: high vol → smaller position
# Guard: vol_ratio=0 means missing vol data — skip the trade entirely
if vol_ratio <= 0:
    return 0.0
kelly_size *= (1.0 / vol_ratio)
```

The `if vol_ratio > 0:` conditional should be removed entirely. After the guard fires and returns 0.0 for vol_ratio=0, the remaining path is: vol_ratio is positive, so always apply the shrinkage unconditionally.

The corrected block:

```python
# Vol adjustment: high vol → smaller position
if vol_ratio <= 0:
    return 0.0  # missing vol data — do not trade
kelly_size *= (1.0 / vol_ratio)
```

No other changes needed in this function. The position cap and `max(0.0, size)` at the end are unaffected.

### Behavior change after fix

| Scenario | Before | After |
|---|---|---|
| vol_ratio=0 (missing data) | Full unscaled Kelly fires | Returns 0.0 — trade skipped |
| vol_ratio=1.0 (normal) | No change (already correct) | No change |
| vol_ratio=2.0 (high vol) | Shrinkage applied (already correct) | No change |
| vol_ratio=0.5 (low vol) | Size doubled (already correct) | No change |

**Net effect on trading:** Any opportunity where vol data is unavailable will return a $0 size from `calculate_position_size()`. In `should_enter()`, this hits the `if size <= 0: return {'enter': False, ...}` check at the bottom and blocks the trade with reason `'kelly_size_zero'`. The trade is skipped cleanly, no exception, no log corruption.

### What could go wrong

- **False skips on legitimate vol_ratio=0:** If any module intentionally passes `vol_ratio=0` to mean something other than "missing data" — check. As of now, no module does this. `vol_ratio=0` is always a data absence condition, not a deliberate signal. The guard is safe.
- **vol_ratio=0 in signal dict vs default:** `should_enter()` uses `signal.get('vol_ratio', 1.0)` — default 1.0 is safe. The bug only fires when `vol_ratio=0` is explicitly present in the signal. Callers that omit the field are not affected.

### Scope

`agents/ruppert/strategist/strategy.py`, `calculate_position_size()` only. Two-line change: add guard, remove the surrounding conditional. No other files touched.

---

## ISSUE-034 — position_monitor.py WS_ENABLED=True Causes RuntimeError

**File:** `agents/ruppert/trader/position_monitor.py`

### What the bug is

At the top of `position_monitor.py`, there is a hardcoded constant:

```python
WS_ENABLED = True                    # Toggle WebSocket mode
```

WS mode was retired on 2026-03-31. The two WS mode functions are stubs that immediately raise:

```python
async def run_ws_mode(client: KalshiClient):
    """WS mode retired 2026-03-31. Use ws_feed.py directly."""
    raise RuntimeError("WS mode retired — use ws_feed.py directly")

async def run_persistent_ws_mode():
    """Persistent WS mode retired 2026-03-31. Use ws_feed.py directly."""
    raise RuntimeError("WS mode retired — use ws_feed.py directly")
```

In `main()`, the code path when `WS_ENABLED = True`:

```python
if WS_ENABLED:
    try:
        from ws.connection import KalshiWebSocket, WS_AVAILABLE
        ws_available = WS_AVAILABLE
    except ImportError:
        print("  [Monitor] WebSocket module not available — using polling mode")
```

If the `ws.connection` import **succeeds** (the module exists even though WS is retired), `ws_available = WS_AVAILABLE` may be True. Then:

```python
if ws_available:
    print("  [Monitor] Starting WebSocket mode...")
    asyncio.run(run_ws_mode(client))   # ← raises RuntimeError immediately
else:
    run_polling_mode(client)           # ← never reached
```

`run_ws_mode()` raises `RuntimeError` before `run_polling_mode()` can execute. The process crashes. Positions go unmonitored until the next Task Scheduler run.

The same failure happens on the `--persistent` flag path if `ws_feed.py` import fails and fallback reaches `asyncio.run(run_persistent_ws_mode())`.

This is not an edge case — WS mode is always retired. `WS_ENABLED = True` guarantees this code path is always attempted.

### What the fix is

**Change `WS_ENABLED = True` to `WS_ENABLED = False`.**

This is a single-line change to the constant at the top of the file:

```python
WS_ENABLED = False                   # WS mode retired 2026-03-31 — polling only
```

With `WS_ENABLED = False`, the `if WS_ENABLED:` block in `main()` is skipped. `ws_available` stays False. The code falls straight through to `run_polling_mode(client)` — which is the correct behavior.

This is a **config constant**, not a hardcoded value scattered throughout the code. Changing it in one place is sufficient.

### Secondary effect: settlement source label

`_settle_single_ticker()` uses `WS_ENABLED` to stamp the `source` field on settlement records:

```python
"source": "ws_settlement" if WS_ENABLED else "poll_settlement",
```

After the fix, this will always write `"poll_settlement"`, which is accurate. Any existing settlement records already written with `"ws_settlement"` are historical — no retroactive correction needed.

### Whether to remove the WS path entirely

The WS path is dead code. Removing it is cleaner than leaving stubs. However, removing it is a larger diff and carries some risk of merge conflicts with in-flight work. The minimal fix (flip the constant) is sufficient to unblock monitoring. If Dev wants to clean up the dead stubs in the same commit, that is fine — but it is not required.

### Behavior change after fix

| Scenario | Before | After |
|---|---|---|
| `ws.connection` import succeeds, WS_AVAILABLE=True | RuntimeError, process crashes, positions unmonitored | WS path never attempted, polling runs correctly |
| `ws.connection` import fails (ImportError) | Falls back to polling (safe path) | Same — but now guaranteed |
| `--persistent` mode (ws_feed import fails) | RuntimeError from stub | Falls back to legacy persistent mode (same as before) |
| Settlement source label | "ws_settlement" (wrong) | "poll_settlement" (correct) |

**Net effect:** position_monitor.py completes successfully on every run. Polling-based settlement checks, exit scans, and position monitoring all execute as intended.

### What could go wrong

- **Nothing.** WS mode is retired. Disabling it cannot break live position monitoring because live position monitoring is already broken whenever the WS import succeeds. The polling path is the only working path — we are just making it the guaranteed path.
- If WS is ever re-enabled in the future, this constant would need to be revisited alongside a full WS re-implementation. That is a future decision, not a concern for this fix.

### Scope

`agents/ruppert/trader/position_monitor.py`. One-line change: `WS_ENABLED = True` → `WS_ENABLED = False`. No other files touched.

---

## Summary

| Issue | File | Change | Risk |
|---|---|---|---|
| ISSUE-117 | `strategy.py` | Add `if vol_ratio <= 0: return 0.0` guard; remove `if vol_ratio > 0:` conditional | Low — only affects missing-data case |
| ISSUE-034 | `position_monitor.py` | `WS_ENABLED = True` → `WS_ENABLED = False` | None — WS path is retired dead code |

Both are pre-conditions to P1 work. Ship together or separately — they are independent changes.

---

_Trader sign-off: these are both safe, narrow fixes. Awaiting David review before Dev builds._
