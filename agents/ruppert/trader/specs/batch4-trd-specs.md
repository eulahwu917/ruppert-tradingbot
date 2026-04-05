# Batch 4 Trader Fix Specs

**Author:** Trader  
**Date:** 2026-04-04  
**Status:** Revised after adversarial review  
**Pipeline stage:** Spec → Adversarial Review → Revise → Dev → QA → Commit

---

## Revision Log

| Rev | Date | Author | Changes |
|-----|------|--------|---------|
| v1.0 | 2026-04-04 | Trader | Initial batch 4 specs — sent to adversarial review |
| v1.1 | 2026-04-04 | Trader | B4-TRD-3: Addressed three gaps flagged by adversarial reviewer — singleton clarification, `_window_retry_after` lock coverage, and "block" result counted as success. B4-TRD-4: Revised from "catch broader exceptions" to "remove dead code entirely" — `run_persistent_ws_mode()` unconditionally raises RuntimeError, fallback path always crashes, dead code must be deleted. B4-TRD-5: Added note to fix hardcoded series tuple at `crypto_15m.py:846`. |

---

## B4-TRD-1: Heartbeat TZ Mismatch (naive vs aware timestamps)

### Problem

The heartbeat writer (`ws_feed.py`, write_heartbeat function around line 991) writes the timestamp using `datetime.now().isoformat()` — this produces a **naive** datetime (no timezone info). The watchdog (`scripts/ws_feed_watchdog.py`, around line 75) then reads that timestamp back via `datetime.fromisoformat(last_ts)` and compares it against `datetime.now()` — also naive. Today this works fine because both sides are naive and both use local time. But it is fragile: if either side ever switches to UTC-aware (or the system TZ changes, or Python's default TZ behavior shifts), the comparison will throw a `TypeError: can't compare offset-naive and offset-aware datetimes`, and the watchdog will crash or treat a live feed as stale — forcing an unnecessary restart.

### Current Code (confirmed)

- **`agents/ruppert/data_analyst/ws_feed.py` ~line 991:** `'last_heartbeat': datetime.now().isoformat()` — naive local time written to heartbeat file.
- **`scripts/ws_feed_watchdog.py` ~line 75:** `last_dt = datetime.fromisoformat(last_ts)` reads the naive string back; `stale_threshold = datetime.now() - timedelta(seconds=HEARTBEAT_STALE_SECONDS)` computes a naive local-time threshold; then `last_dt > stale_threshold` compares the two.

Both sides are currently naive and both use local time, so the comparison works. The risk is that any future change on either side to UTC-aware breaks it silently.

### Fix

Standardize both sides on UTC-aware datetimes using `timezone.utc`.

**In `ws_feed.py` write_heartbeat (~line 991):**  
Change `datetime.now().isoformat()` to `datetime.now(timezone.utc).isoformat()`.  
This writes an ISO string that includes the `+00:00` offset, e.g. `2026-04-04T18:00:00+00:00`.

**In `scripts/ws_feed_watchdog.py` (~line 75):**  
When parsing the heartbeat timestamp, `datetime.fromisoformat(last_ts)` will correctly parse the `+00:00` offset and return a UTC-aware datetime.  
Change `datetime.now()` to `datetime.now(timezone.utc)` when computing `stale_threshold`.

Both `datetime` and `timezone` are already available in the standard library. Confirm `from datetime import datetime, timezone, timedelta` is imported in both files.

### Acceptance Criteria

- Both files import `timezone` from `datetime`.
- `ws_feed.py` writes `datetime.now(timezone.utc).isoformat()` to the heartbeat JSON.
- `ws_feed_watchdog.py` computes stale threshold using `datetime.now(timezone.utc)`.
- No `TypeError` when comparing timestamps.
- No behavior change to watchdog restart logic — only the timestamp type is normalized.

---

## B4-TRD-2: `_prune_window_guard()` Strips tzinfo Then String-Compares

### Problem

`_prune_window_guard()` in `agents/ruppert/data_analyst/ws_feed.py` (~line 144) computes the pruning cutoff like this:

```
cutoff = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)).isoformat()
```

It deliberately strips the tzinfo (via `.replace(tzinfo=None)`) and produces a naive ISO string for the cutoff. It then compares that naive string against the values stored in `_window_evaluated`.

The values stored in `_window_evaluated` are written at ~line 264:

```
_window_evaluated[guard_key] = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
```

Both sides strip tzinfo before storing/comparing, so string comparison works today. However, this is fragile for two reasons:

1. If any future code stores a UTC-aware ISO string in `_window_evaluated` (e.g. `datetime.now(timezone.utc).isoformat()` without stripping), the string comparison will misbehave — a UTC-aware string like `2026-04-04T18:00:00+00:00` will sort differently from a naive string like `2026-04-04T18:00:00` because of the appended offset characters.
2. The pattern of "get a UTC time, then immediately strip the UTC info" is confusing and error-prone.

### Fix

Remove the `.replace(tzinfo=None)` stripping throughout. Store and compare UTC-aware datetimes everywhere in this flow.

**In `_window_evaluated` writes (~line 264):**  
Change `datetime.now(timezone.utc).replace(tzinfo=None).isoformat()` to `datetime.now(timezone.utc).isoformat()`.  
This stores a UTC-aware ISO string including the `+00:00` offset.

**In `_prune_window_guard()` (~line 144):**  
Change `(datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)).isoformat()` to `(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()`.  
This produces a UTC-aware cutoff string. Since both the stored values and the cutoff are now UTC-aware ISO strings with identical format (`+00:00`), lexicographic string comparison remains valid and correct.

### Acceptance Criteria

- No `.replace(tzinfo=None)` calls remain in the `_window_evaluated` write path or in `_prune_window_guard()`.
- All values stored in `_window_evaluated` include the UTC offset.
- `_prune_window_guard()` cutoff also includes the UTC offset.
- String comparison logic is preserved (no behavior change to pruning logic, just data format normalization).
- No new imports required — `timezone` is already imported.

---

## B4-TRD-3: Window Marked Evaluated BEFORE Eval Succeeds *(Revised v1.1)*

### Problem

In `agents/ruppert/data_analyst/ws_feed.py` around lines 252–284, the fallback poll loop checks whether a 15-minute crypto window has already been evaluated using `_window_evaluated`. The critical bug is the **order of operations**:

1. `_window_evaluated[guard_key]` is **set first** (inside the `async with _window_eval_lock` block at ~line 264), before any market fetch or evaluation attempt.
2. Then `_fetch_15m_market_price()` is called. If this REST call returns `None` (e.g. transient failure, market not found yet), the code does `continue` and skips the rest of the loop.
3. On the next poll cycle (30 seconds later), `guard_key` is already in `_window_evaluated`, so the window is skipped permanently for the rest of its lifetime.

The result: a single transient REST failure permanently prevents evaluation of that window. The window is silently dead.

### Architecture Clarification (from code review)

**Is `_fallback_poll_loop` a singleton?** No — it is created as a new `asyncio.create_task(_fallback_poll_loop())` on each WS connection cycle (line 877) and cancelled on disconnect (line 948). This means a new coroutine is spawned per reconnect. However, `_window_retry_after` is a **module-level dict** — it is NOT recreated when a new `_fallback_poll_loop` task is spawned. The retry state persists correctly across reconnects. There is no double-eval race from task recreation.

**Is `_window_retry_after` covered by `_window_eval_lock`?** Currently no — the proposed design in v1.0 did not specify locking for `_window_retry_after`. Since `_fallback_poll_loop` is not a singleton (multiple tasks can theoretically exist briefly during reconnect overlap), reads and writes to `_window_retry_after` must also be protected. See Fix section below.

**Does a "block" result count as success for `_window_evaluated`?** Yes — the evaluated flag should be written on **any** non-exception return from `evaluate_crypto_15m_entry()`, including when a rule (e.g. R9) fires and returns without placing a trade. The purpose of `_window_evaluated` is to prevent duplicate evaluation of the same window, not to gate on trade outcome. A blocked evaluation is still a completed evaluation — the window has been assessed and the answer is "no trade." Writing the flag prevents wasted REST calls and duplicate rule evaluations on subsequent poll cycles.

### Fix

Move the `_window_evaluated[guard_key] =` write to **after** a successful evaluation. Add a single delayed retry on REST `None` — not an infinite retry. Protect `_window_retry_after` under the existing `_window_eval_lock`.

**Step 1 — Do the guard check early, but don't write yet.**  
Inside the `async with _window_eval_lock` block:
- Check if `guard_key` is already in `_window_evaluated` → `continue` if so (as today).
- Also check if `guard_key` is in `_window_retry_after` and the retry time has not yet passed → `continue` (not ready yet).
- Do NOT write to `_window_evaluated` yet. Release the lock.

**Step 2 — Attempt the market fetch.**  
Call `_fetch_15m_market_price()`. If it returns `None`:

- Acquire `_window_eval_lock`.
- If `guard_key` is already in `_window_retry_after` (this is the second miss): mark the window as permanently evaluated with a warning log, remove from `_window_retry_after`, `continue`.
- If `guard_key` is NOT in `_window_retry_after` (this is the first miss): write `_window_retry_after[guard_key] = now + 30s`. Do NOT write `_window_evaluated`. Release lock. `continue`.

**Step 3 — Mark evaluated only on completion (success or block).**  
After `evaluate_crypto_15m_entry()` returns without exception — regardless of whether a trade was placed — acquire `_window_eval_lock` and:
- Write `_window_evaluated[guard_key]` (UTC-aware ISO string, per B4-TRD-2 fix).
- Remove `guard_key` from `_window_retry_after` if present (cleanup).

This covers both happy path (trade placed) and blocked path (e.g. R9 fires, no trade). Both outcomes represent completed evaluation of the window.

**Step 4 — Clean up retry dict.**  
`_prune_window_guard()` must also prune `_window_retry_after` entries. Acquire `_window_eval_lock` before pruning `_window_retry_after`, the same as it does for `_window_evaluated`. Use the same 1-hour TTL. Since `_window_retry_after` values are timestamps (not ISO strings), compare against `now - timedelta(hours=1)` as a datetime object.

**What this is NOT:**  
This is not an infinite retry. After one retry attempt, if REST returns `None` again, the window is permanently skipped. This prevents runaway loops while allowing recovery from single transient failures.

### Acceptance Criteria

- `_window_evaluated[guard_key]` is only set after `evaluate_crypto_15m_entry()` returns without exception — including when the evaluator returns with no trade (block result counts as completed).
- A first REST `None` result does not permanently skip the window — it queues a retry for the next poll cycle (~30s).
- A second REST `None` result permanently skips the window with a `logger.warning()` log.
- No infinite retry loops.
- All reads and writes to `_window_retry_after` are protected under `_window_eval_lock`. This covers the brief reconnect overlap window where two `_fallback_poll_loop` tasks could briefly coexist.
- `_window_retry_after` is pruned by `_prune_window_guard()` under `_window_eval_lock`, same TTL as `_window_evaluated`.
- Existing behavior is unchanged for the happy path (REST returns a valid market on the first attempt, evaluate_crypto_15m_entry returns, window is marked done).
- Dev note: `_fallback_poll_loop` is spawned per WS connection cycle — not a singleton. `_window_retry_after` is module-level and persists across reconnects. This is correct and intentional; do not change the lifecycle.

---

## B4-TRD-4: `--persistent` Flag Dead Code — `run_persistent_ws_mode()` Always Crashes *(Revised v1.1)*

### What the Adversarial Reviewer Found

The v1.0 spec proposed broadening the `except ImportError` to `except Exception` to catch more failure modes. That was wrong. The actual problem is more fundamental.

### What the Code Actually Does (confirmed by reading position_monitor.py lines 614–670)

**`run_persistent_ws_mode()` (line 614):**
```python
async def run_persistent_ws_mode():
    """Persistent WS mode retired 2026-03-31. Use ws_feed.py directly."""
    raise RuntimeError("WS mode retired — use ws_feed.py directly")
```

This function is **unconditionally retired**. It raises `RuntimeError` on every call, no exceptions.

**The `--persistent` entry point (lines 654–670):**
```python
if args.persistent:
    try:
        from agents.ruppert.data_analyst.ws_feed import run
        print("  [Monitor] Delegating to ws_feed.py (WS-first architecture)")
        run()
        return
    except ImportError as e:
        print(f"  [Monitor] ws_feed import failed ({e}) — falling back to legacy persistent mode")
    if not _in_market_hours():
        ...
        return
    asyncio.run(run_persistent_ws_mode())  # ← ALWAYS RAISES RuntimeError
    return
```

**The fallback path always crashes.** If `ws_feed` imports successfully, `run()` is called and returns normally — that's fine. But if `ws_feed` import fails for any reason, the code falls through to `asyncio.run(run_persistent_ws_mode())`, which unconditionally raises `RuntimeError`. The `--persistent` flag has no working fallback. Broadening the `except` clause (as v1.0 proposed) would only catch more ws_feed import failures and route them into the same guaranteed crash.

### Correct Fix: Remove the Dead Code

The dead code path (`run_persistent_ws_mode()` and the fallback after the `except` block) must be removed entirely. The `--persistent` entry point should:

1. Try `ws_feed.run()`.
2. If it fails for any reason, log the error and **exit cleanly** (or raise, depending on operator preference — see below).

There is no valid legacy fallback. `run_persistent_ws_mode()` was retired 2026-03-31 and has never been a real fallback since then — it has always crashed. The comment "falling back to legacy persistent mode" is misleading and must be removed.

**Revised `--persistent` block:**
```python
if args.persistent:
    try:
        from agents.ruppert.data_analyst.ws_feed import run
        logger.info("[Monitor] Starting ws_feed (WS-first architecture) via --persistent")
        run()
        return
    except Exception as e:
        logger.error(
            "[Monitor] ws_feed failed to start (%s: %s) — no fallback available, exiting",
            type(e).__name__, e
        )
        sys.exit(1)
```

**Why `except Exception` here (not `except ImportError`):** Now that there is no false fallback to route into, a broad catch is correct. We want to log any failure — import errors, initialization errors, runtime errors — and exit cleanly rather than crashing with an unformatted traceback.

**Why `sys.exit(1)` not a silent return:** The caller (scheduled task / cron) needs a non-zero exit code to know the persistent session failed to start. A silent `return` would look like a successful run to the scheduler.

### Dead Code to Remove

- `run_persistent_ws_mode()` function (lines 614–617) — the entire function.
- The `except ImportError` block's fallback message referencing "legacy persistent mode."
- The `if not _in_market_hours(): return` block that gates the now-removed function.
- The `asyncio.run(run_persistent_ws_mode())` call.
- The `return` after it.

Dev should confirm no other code in the codebase calls `run_persistent_ws_mode()`. A grep for the function name before deletion is required.

### Acceptance Criteria

- `run_persistent_ws_mode()` function is deleted from `position_monitor.py`.
- The `--persistent` entry point attempts `ws_feed.run()` and exits with `sys.exit(1)` on any failure.
- The failure is logged via `logger.error()` with exception type and message.
- No reference to "legacy persistent mode" or fallback-to-polling remains in the `--persistent` code path.
- Grep for `run_persistent_ws_mode` across the codebase returns zero results after the change.
- `--persistent` flag with a working `ws_feed` import: runs normally, exits 0.
- `--persistent` flag with a broken `ws_feed` import: logs error, exits 1, no unhandled exception traceback.

---

## B4-TRD-5: `KXSOL15M` Missing from `position_monitor.py` Series List *(Updated v1.1)*

### Problem

`agents/ruppert/trader/position_monitor.py` line ~69 defines:

```python
CRYPTO_15M_SERIES = ['KXBTC15M', 'KXETH15M', 'KXXRP15M', 'KXDOGE15M']
```

`KXSOL15M` (SOL 15-minute binary) was added to `ws_feed.py`'s active series list in a prior sprint, meaning the WS feed now monitors and trades SOL 15m positions. However, `position_monitor.py`'s `CRYPTO_15M_SERIES` list was not updated. This means:

- SOL 15m open positions will not appear in polling-mode monitoring.
- The 70% global cap enforcement path that reads from this list will not account for open SOL 15m exposure.
- Any polling-based exit logic for SOL 15m positions will not fire.

This is a silent monitoring gap — the system will trade SOL 15m but not watch it in the polling fallback.

### Fix

Add `'KXSOL15M'` to the `CRYPTO_15M_SERIES` list in `agents/ruppert/trader/position_monitor.py` line ~69.

The list should read:  
`CRYPTO_15M_SERIES = ['KXBTC15M', 'KXETH15M', 'KXXRP15M', 'KXDOGE15M', 'KXSOL15M']`

Dev should also verify whether any other series lists elsewhere in the codebase (e.g. in `crypto_15m.py`, `position_tracker.py`, or `main.py`) need the same update for consistency. That cross-check is in scope for this fix.

**Additional fix in the same pass — `crypto_15m.py:846` hardcoded series tuple:**  
The adversarial reviewer identified that `crypto_15m.py` line 846 contains a hardcoded duplicate of the series tuple (listing the same series as `CRYPTO_15M_SERIES`) instead of referencing the constant. This was confirmed in the code review — the tuple at line 846 lists `('KXBTC15M', 'KXETH15M', 'KXXRP15M', 'KXDOGE15M', 'KXSOL15M')` explicitly rather than importing and referencing `CRYPTO_15M_SERIES`. Dev must fix this site in the same pass: replace the hardcoded tuple with a reference to `CRYPTO_15M_SERIES` (importing it from `position_monitor` if not already available in that module). This eliminates the divergence risk — if another series is added later, both sites update together.

### Acceptance Criteria

- `KXSOL15M` is present in `CRYPTO_15M_SERIES` in `position_monitor.py`.
- No other series list in the active codebase is missing `KXSOL15M` (Dev to audit and fix any gaps found).
- `crypto_15m.py` line ~846: hardcoded series tuple is replaced with a reference to `CRYPTO_15M_SERIES`. No hardcoded series list remains at that site.
- Polling mode monitors SOL 15m positions the same way it monitors BTC/ETH/XRP/DOGE.
- No behavior change to any existing series.

---

*End of Batch 4 Trader specs (v1.1 — post adversarial review). Send to Dev.*
