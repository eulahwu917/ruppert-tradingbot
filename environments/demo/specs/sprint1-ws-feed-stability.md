# Sprint 1 Spec — WS Feed Stability + Duplicate Order Prevention
_CEO authored. David reviewed. Dev implements. QA verifies before commit._
_Date: 2026-04-03_

---

## Overview

9 issues, all in `agents/ruppert/data_analyst/ws_feed.py`,
`agents/ruppert/trader/position_tracker.py`, and
`environments/demo/scripts/ws_feed_watchdog.py`.

**Do NOT touch any other files unless explicitly called out below.**

After all 9 fixes are applied, hand to QA before committing anything.
QA pass required. Then commit with message:
`fix: Sprint 1 — WS feed stability + duplicate order prevention (ISSUE-070, 015, 060, 014, 061, 049, 002, 003, 107)`

---

## Fix 1 — ISSUE-070: WS feed daily cap uses 7% instead of 70%

**File:** `environments/demo/config.py`

**The problem:** `evaluate_crypto_entry()` in `ws_feed.py` enforces a `daily_cap` check
using `CRYPTO_DAILY_CAP_PCT` (value: 0.07 = 7%). This is a legacy fallback constant that
was supposed to be deprecated. The real cap is `DAILY_CAP_RATIO = 0.70` (70%). So the WS
feed stops placing new hourly band/threshold trades after only ~$400–$920 deployed, even
when the system has plenty of capacity.

**The fix:**
In `ws_feed.py`, inside `evaluate_crypto_entry()`, replace the daily cap check:

```python
# BEFORE (uses wrong 7% legacy constant):
daily_cap = capital * config.CRYPTO_DAILY_CAP_PCT
current_exposure = get_daily_exposure()
if current_exposure >= daily_cap:
    logger.debug(...)
    _log_skip('daily_cap_reached')
    return
```

Change to:
```python
# AFTER (uses correct 70% global cap):
daily_cap = capital * getattr(config, 'DAILY_CAP_RATIO', 0.70)
current_exposure = get_daily_exposure()
if current_exposure >= daily_cap:
    logger.debug(f"Crypto global daily cap reached: ${current_exposure:.2f} >= ${daily_cap:.2f}")
    _log_skip('daily_cap_reached')
    return
```

**Do NOT touch config.py** — `DAILY_CAP_RATIO = 0.70` is already the correct value there.
This is a one-line fix in `ws_feed.py` only.

**Behavior change:** The WS hourly evaluator will now allow entries up to 70% of capital
deployed for the day (consistent with every other module), instead of stopping at 7%.

---

## Fix 2 — ISSUE-015: WS eval fires duplicate orders on burst price updates

**File:** `agents/ruppert/data_analyst/ws_feed.py`

**The problem:** When multiple WS price ticks arrive in rapid succession for the same 15m
ticker (common during active windows), `handle_message()` spawns a new `_safe_eval_15m()`
background task for each one. All tasks run concurrently. They all check `_window_evaluated`
before writing to it. The first one writes, but by then 2–5 others have already passed the
check and each places a separate order.

**The fix:** Add an `asyncio.Lock` for the window-level eval guard. The lock must be checked
and set atomically so only the first task proceeds; all subsequent ones for the same window
short-circuit.

Add at module level (near `_window_evaluated` dict):
```python
_window_eval_lock = asyncio.Lock()
```

In `_safe_eval_15m()`, wrap the window-evaluated check in the lock:
```python
async def _safe_eval_15m(...):
    try:
        # ... depth enrichment unchanged ...

        # ── Atomic window dedup guard ──
        if open_time:
            _series = next((s for s in CRYPTO_15M_SERIES if ticker_upper.startswith(s)), None)
            _open_time_norm = open_time.replace('Z', '+00:00') if open_time and open_time.endswith('Z') else open_time
            _guard_key = f"{_series}::{_open_time_norm}" if _series and _open_time_norm else None
        else:
            _guard_key = None

        async with _window_eval_lock:
            if _guard_key and _guard_key in _window_evaluated:
                return  # already evaluated this window — drop silently
            if _guard_key:
                _window_evaluated[_guard_key] = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
            # proceed with evaluation — mark is set inside the lock
        
        # ... rest of eval unchanged (evaluate_crypto_15m_entry call etc.) ...
        # NOTE: do NOT re-mark _window_evaluated after evaluate_crypto_15m_entry —
        # it's already marked above inside the lock.
    except Exception as e:
        logger.warning('[WS Feed] _safe_eval_15m error for %s: %s', ticker, e)
```

**Important:** In the current code, there is NO pre-eval guard — `_window_evaluated` is only written AFTER `evaluate_crypto_15m_entry()` returns (at the bottom of `_safe_eval_15m()`). That post-eval write block (the `if _series and _open_time_norm:` block at the end of `_safe_eval_15m()`) must be **deleted entirely** — it is replaced by the lock+write at the top. Do not just move it; delete it.

**Behavior change:** Only the first WS tick per 15m window fires an evaluation. All
subsequent ticks for the same window are silently dropped until a new window opens.

---

## Fix 3 — ISSUE-060: WS eval and REST fallback can both fire same window

**File:** `agents/ruppert/data_analyst/ws_feed.py`

**The problem:** `_safe_eval_15m()` (WS path) and `_check_and_fire_fallback()` (REST path)
both check `_window_evaluated` before writing. If the WS task hasn't finished yet when
the 30s REST poll fires, both can pass the check and place orders for the same window.

**The fix:** Reuse the same `_window_eval_lock` from Fix 2 in `_check_and_fire_fallback()`.

In `_check_and_fire_fallback()`, replace the guard check/set for each series:
```python
# BEFORE:
if guard_key in _window_evaluated:
    continue
# ... (evaluate and then set guard_key after) ...

# AFTER:
async with _window_eval_lock:
    if guard_key in _window_evaluated:
        continue
    _window_evaluated[guard_key] = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
# ... proceed with evaluation (guard is set) ...
```

Same pattern as Fix 2 — write the guard INSIDE the lock BEFORE the eval.

**Behavior change:** WS and REST paths are now mutually exclusive per window. Whichever
fires first wins; the other is silently dropped.

---

## Fix 4 — ISSUE-014: Blocking I/O in async WS handler causes disconnects

**File:** `agents/ruppert/data_analyst/ws_feed.py`

**The problem:** `evaluate_crypto_entry()` (the hourly band evaluator) is a regular
synchronous function called from `_safe_eval_hourly()`. Inside it, it calls:
- `get_capital()` → reads from disk
- `get_daily_exposure()` → reads from disk
- `get_buying_power()` → makes a REST call to Kalshi API
- `KalshiClient()` + `place_order()` → REST API calls

All of these run on the asyncio event loop thread, blocking it. When a blocking call takes
>10s (e.g. slow Kalshi API), the event loop can't respond to server PINGs → disconnect.

**The fix:** In `_safe_eval_hourly()`, move the blocking call to `run_in_executor`:

```python
async def _safe_eval_hourly(ticker: str, yes_ask: int, yes_bid: int, close_time: str | None):
    """Background task: crypto hourly band entry evaluation."""
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: evaluate_crypto_entry(ticker, yes_ask, yes_bid, close_time)
        )
    except Exception as e:
        logger.warning('[WS Feed] Crypto eval error: %s', e)
```

`evaluate_crypto_entry()` itself does NOT need to be changed — it stays synchronous.
Only `_safe_eval_hourly()` changes.

**Pre-flight check for Dev:** Before implementing, verify that `push_alert()` and `position_tracker.add_position()` (both called at the end of `evaluate_crypto_entry()`) are fully synchronous — no asyncio calls, no event loop usage. If either uses asyncio internally, running the whole function in `run_in_executor` will fail. Inspect both functions before shipping.

**Behavior change:** Hourly band evaluations run in a thread pool instead of blocking
the event loop. Server PINGs are answered on time. Disconnects caused by slow API calls
are eliminated.

---

## Fix 5 — ISSUE-061: `_rest_refresh_stale()` blocks event loop every 5 min

**File:** `agents/ruppert/data_analyst/ws_feed.py`

**The problem:** `_rest_refresh_stale()` is called directly (not as a task) from the
main WS loop every 5 minutes. Inside, it calls `_get_kalshi_client().get_market(ticker)`
for every tracked position — blocking REST calls on the event loop thread.

**The fix:** `_rest_refresh_stale()` is already async — the call site in `run_ws_feed()` stays unchanged (`await _rest_refresh_stale()`). The fix is to make the internal blocking REST calls non-blocking by wrapping them in `run_in_executor`.

**⚠️ WARNING FOR DEV — DO NOT USE `run_coroutine_threadsafe` HERE:** Submitting a coroutine to the running event loop from within the running event loop (via `run_coroutine_threadsafe(...).result()`) causes a deadlock — the thread blocks waiting for the coroutine to complete, but the coroutine needs the event loop to run, but the event loop is blocked waiting for the thread. Use the `run_in_executor` approach below ONLY.

Change `_rest_refresh_stale()` to:
```python
async def _rest_refresh_stale() -> None:
    try:
        tracked = position_tracker.get_tracked()
    except Exception as e:
        logger.warning('[WS Feed] _rest_refresh_stale: could not get tracked: %s', e)
        return

    loop = asyncio.get_running_loop()
    for key_str in tracked:
        ticker = key_str.split('::')[0]
        try:
            _, _, is_stale = market_cache.get_with_staleness(ticker)
            if not is_stale:
                continue
            result = await loop.run_in_executor(
                None,
                lambda t=ticker: _get_kalshi_client().get_market(t)
            )
            if result and result.get('yes_bid') is not None and result.get('yes_ask') is not None:
                bid_d = result['yes_bid'] / 100
                ask_d = result['yes_ask'] / 100
                market_cache.update(ticker, bid_d, ask_d, source='rest_heal')
                logger.debug('[WS Feed] REST heal: %s', ticker)
        except Exception as e:
            logger.warning('[WS Feed] _rest_refresh_stale error for %s: %s', ticker, e)
```

**Behavior change:** REST heals no longer block the event loop. Each ticker's REST call
runs in a thread pool. The function signature stays async — the call site in `run_ws_feed()`
is unchanged.

---

## Fix 6 — ISSUE-049: Watchdog spawns second ws_feed without killing hung process

**File:** `environments/demo/scripts/ws_feed_watchdog.py`

**The problem:** When ws_feed hangs (not crashed, just stuck — not writing heartbeats),
the watchdog calls `start_ws_feed()` which launches a new process via `subprocess.Popen`.
The hung original process is still running. Now two ws_feed processes exist, both subscribing
to the same WS feed, both watching the same positions, and both firing exits for the same
positions.

**The fix:** Read the PID from the heartbeat file before spawning a new process. Kill the
old process if it's still running.

Add a helper function:
```python
def kill_existing_ws_feed():
    """Kill any existing ws_feed process before spawning a new one."""
    hb_file = get_heartbeat_file()
    if not hb_file.exists():
        return

    try:
        data = json.loads(hb_file.read_text(encoding='utf-8'))
        pid = data.get('pid')
        if not pid:
            return

        import psutil
        try:
            proc = psutil.Process(pid)
            # Only kill if it looks like our ws_feed process
            if 'python' in proc.name().lower():
                proc.terminate()
                log(f"Terminated stale ws_feed PID {pid}")
                # Give it 3s to die gracefully, then force kill
                try:
                    proc.wait(timeout=3)
                except psutil.TimeoutExpired:
                    proc.kill()
                    log(f"Force-killed stale ws_feed PID {pid}")
        except psutil.NoSuchProcess:
            pass  # already dead, that's fine
        except Exception as e:
            log(f"Could not kill PID {pid}: {e}")
    except Exception as e:
        log(f"kill_existing_ws_feed: heartbeat read failed: {e}")
```

Then in `run_watchdog()`, call it before spawning:
```python
if not is_heartbeat_fresh():
    log("Heartbeat stale or missing — ws_feed appears dead or hung")
    kill_existing_ws_feed()   # ← ADD THIS LINE
    time.sleep(2)
    start_ws_feed()
    log("Restarted ws_feed.py")
```

**Dependency:** `psutil` — already in `requirements.txt`? Check before implementing.
If not present, add `import os` fallback:
```python
os.kill(pid, signal.SIGTERM)  # Windows: use os.kill(pid, signal.CTRL_C_EVENT) or taskkill
```
On Windows, use:
```python
import subprocess
subprocess.run(['taskkill', '/F', '/PID', str(pid)], capture_output=True)
```
Use `psutil` if available, otherwise `taskkill` subprocess as fallback.

**Behavior change:** Before spawning a new ws_feed, the watchdog kills any existing one.
No more duplicate feed processes.

---

## Fix 7 — ISSUE-002: No asyncio.Lock on `_exits_in_flight` → double-exits

**File:** `agents/ruppert/trader/position_tracker.py`

**The problem:** `_exits_in_flight` is a plain Python `set`. Two concurrent WS ticks for
different positions can both call `execute_exit()` simultaneously. Each checks
`if key in _exits_in_flight` and both see False. Both add their key and proceed — this is
fine for different positions. BUT the same position can have multiple tickers trigger exit
conditions simultaneously (e.g. both 95c rule AND stop loss fire). Both tasks see the guard
as clear, both pass, both place orders.

The existing guard (`if key in _exits_in_flight: return`) is correct logic but NOT
thread-safe — two concurrent awaits on `execute_exit` for the same key both pass the check
before either writes to the set.

**The fix:** Add an `asyncio.Lock` per key (or a global lock around the check+add):

Add at module level:
```python
_exits_lock = asyncio.Lock()
```

In `execute_exit()`, replace the current dedup guard:
```python
# BEFORE:
if key in _exits_in_flight:
    logger.warning(...)
    return
_exits_in_flight.add(key)
```

With:
```python
# AFTER: atomic check-and-set under lock
async with _exits_lock:
    if key in _exits_in_flight:
        logger.warning(
            '[PositionTracker] Dedup guard: exit for %s %s already in-flight — skipping duplicate',
            ticker, side
        )
        return
    _exits_in_flight.add(key)
```

The `try/finally` block that discards from `_exits_in_flight` is unchanged — it's the
only cleanup path and runs AFTER the await resolves.

**Behavior change:** The check and set are now atomic. Only one exit per (ticker, side)
can be in flight at any time.

---

## Fix 8 — ISSUE-003: `execute_exit()` swallows API failure → infinite retry

**File:** `agents/ruppert/trader/position_tracker.py`

**The problem:** In `execute_exit()`, when the Kalshi `sell_position()` call fails, the
code currently returns early but does NOT remove the position from the tracker:
```python
try:
    order_result = client.sell_position(ticker, side, current_bid, quantity)
except Exception as e:
    logger.error('[WS Exit] Execute failed for %s: %s', ticker, e)
    return   # ← position stays in tracker, retried on every subsequent tick
```

On persistent API failure, the position is retried on every price tick until the market
closes. This can generate hundreds of failed API calls and false log entries.

**The fix:** On API failure, implement exponential back-off with a max retry count.
Add a retry counter to `_tracked` positions. After N consecutive failures (N=3), remove
the position from the tracker, send a Telegram alert, and log the abandonment.

Simple approach — track failures in the position dict itself:

```python
try:
    order_result = client.sell_position(ticker, side, current_bid, quantity)
except Exception as e:
    logger.error('[WS Exit] Execute failed for %s: %s', ticker, e)
    # Track consecutive failures
    pos['_exit_failures'] = pos.get('_exit_failures', 0) + 1
    _persist()
    if pos['_exit_failures'] >= 3:
        # Give up — remove from tracker and alert
        logger.error(
            '[WS Exit] %s %s: 3 consecutive exit failures — abandoning position',
            ticker, side
        )
        try:
            from agents.ruppert.trader.utils import push_alert
            push_alert('error', f'EXIT ABANDONED after 3 failures: {ticker} {side.upper()}', ticker=ticker)
        except Exception as _alert_err:
            logger.error('[WS Exit] push_alert failed on abandonment: %s', _alert_err)
        remove_position(ticker, side)
        _recently_exited[key] = time.time()
    return
```

**Notes for Dev:**
- `_exit_failures` is persisted to disk via `_persist()` on every failure. This means the counter survives ws_feed restarts — a position that hit 2 failures before restart will abandon on the next failure after restart. This is intentional and documented behavior.
- The 3-strike threshold has no time gate. A 3-second API blip could kill a live position permanently. This is an accepted tradeoff for simplicity — document it in the code comment.
- Wrap the `push_alert` import in its own try/except (shown above) — if the import fails on abandonment, the abandonment itself must still complete.

**Behavior change:** Failed exits get 3 attempts. After that, the position is removed
from the tracker and David gets a Telegram alert. No more infinite retry storms.

---

## Fix 9 — ISSUE-107: `_tracked` mutated during `await` in `execute_exit()` → stale refs

**File:** `agents/ruppert/trader/position_tracker.py`

**The problem:** In `execute_exit()`, `pos` is a direct reference to `_tracked[key]`.
After the function enters the `try` block, it does `await loop.run_in_executor(...)` or
similar awaits. During that await, another asyncio task can call `remove_position()` or
`add_position()` for the same key, mutating `_tracked`. The `pos` reference now points to
stale or modified data.

Specifically:
- `entry_price`, `quantity`, `module`, `title` are all read from `pos` after the `await`
  in the dry run branch (order_result fetch). If `pos` was updated in-between, wrong values
  are used for P&L logging.

**The fix:** Snapshot the position data at the start of `execute_exit()`, before any await:

```python
async def execute_exit(key: tuple, pos: dict, current_bid: int, rule: str,
                       settle_loss: bool = False):
    ticker, side = key

    # Dedup guard (with asyncio.Lock from Fix 7) ...

    _exits_in_flight.add(key)
    try:
        # ── Snapshot position data before any await ──────────────────────────
        # Prevents stale reads if another task modifies _tracked during an await.
        entry_price = pos['entry_price']
        quantity    = pos['quantity']
        module      = pos.get('module', '')
        title       = pos.get('title', '')
        size_dollars = pos.get('size_dollars')
        # ── End snapshot ─────────────────────────────────────────────────────

        # ... rest of function uses local variables (entry_price, quantity, etc.)
        # instead of pos['entry_price'] etc. ...
```

Go through the rest of `execute_exit()` and replace all `pos['entry_price']`,
`pos['quantity']`, `pos.get('module', '')`, `pos.get('title', '')`,
`pos.get('size_dollars', ...)` with the local snapshot variables.

Keep `pos.get('_exit_failures', 0)` reads from `pos` directly (needed for Fix 8 — that
mutation must write back to the live dict).

**Dev warning:** This requires a careful manual replacement pass through the entire body of `execute_exit()`. Replace ALL occurrences of `pos['entry_price']`, `pos['quantity']`, `pos.get('module', '')`, `pos.get('title', '')`, and `pos.get('size_dollars', ...)` with the local snapshot variables. A single missed replacement is the only realistic regression path here — do not use find-and-replace blindly.

**Apply Fix 7 and Fix 9 in a single pass** — they modify adjacent lines at the top of `execute_exit()`.

**Behavior change:** P&L calculations and log entries always use the data from when the
exit started, even if another task modifies the position mid-exit.

---

## QA Checklist (hand to QA after all 9 fixes)

QA does NOT need to run live trading. Static analysis + code inspection is sufficient.

1. **ISSUE-070**: In `ws_feed.py`, grep for `CRYPTO_DAILY_CAP_PCT` in `evaluate_crypto_entry()` — should be gone. `DAILY_CAP_RATIO` should be used instead.
2. **ISSUE-015**: In `_safe_eval_15m()`, confirm `_window_eval_lock` is acquired before checking and setting `_window_evaluated`. Confirm the old post-eval write is removed.
3. **ISSUE-060**: In `_check_and_fire_fallback()`, confirm same `_window_eval_lock` pattern used.
4. **ISSUE-014**: In `_safe_eval_hourly()`, confirm `evaluate_crypto_entry()` is called via `run_in_executor`.
5. **ISSUE-061**: In `_rest_refresh_stale()`, confirm all `get_market()` calls are wrapped in `run_in_executor`.
6. **ISSUE-049**: In `ws_feed_watchdog.py`, confirm `kill_existing_ws_feed()` is called before `start_ws_feed()`. Confirm PID read from heartbeat file. Confirm `taskkill` or `psutil` used (not just `os.kill`).
7. **ISSUE-002**: In `position_tracker.py`, confirm `_exits_lock = asyncio.Lock()` exists at module level. Confirm `execute_exit()` uses `async with _exits_lock` for the check+add.
8. **ISSUE-003**: In `execute_exit()`, confirm failed `sell_position()` increments `_exit_failures`. Confirm abandonment after 3 failures. Confirm `push_alert` called on abandonment.
9. **ISSUE-107**: In `execute_exit()`, confirm `entry_price`, `quantity`, `module`, `title` are snapshotted to local variables before any `await`. Confirm the rest of the function uses the locals.

After all 9 checks pass, QA commits with:
`fix: Sprint 1 — WS feed stability + duplicate order prevention (ISSUE-070, 015, 060, 014, 061, 049, 002, 003, 107)`

QA then updates `SYSTEM_MAP.md` under the relevant sections to reflect fixed behavior.

---

## Change Log Entry (after commit)

Add to `memory/agents/fix-changelog.md`:

```
## Sprint 1 Changes — 2026-04-03

| Issue ID | Title | Fix Summary | Commit |
|----------|-------|-------------|--------|
| ISSUE-070 | WS feed 7% cap → 70% | ws_feed.py: CRYPTO_DAILY_CAP_PCT → DAILY_CAP_RATIO in evaluate_crypto_entry() | TBD |
| ISSUE-015 | WS eval dedup | ws_feed.py: asyncio.Lock on _window_evaluated check+set in _safe_eval_15m() | TBD |
| ISSUE-060 | WS + REST fallback dedup | ws_feed.py: same lock in _check_and_fire_fallback() | TBD |
| ISSUE-014 | Blocking I/O in async handler | ws_feed.py: evaluate_crypto_entry() → run_in_executor in _safe_eval_hourly() | TBD |
| ISSUE-061 | _rest_refresh_stale blocks loop | ws_feed.py: get_market() → run_in_executor in _rest_refresh_stale() | TBD |
| ISSUE-049 | Watchdog spawns duplicate ws_feed | ws_feed_watchdog.py: kill_existing_ws_feed() before Popen | TBD |
| ISSUE-002 | _exits_in_flight race | position_tracker.py: asyncio.Lock on _exits_in_flight check+add | TBD |
| ISSUE-003 | Exit failure → infinite retry | position_tracker.py: 3-strike abandonment + push_alert | TBD |
| ISSUE-107 | _tracked mutated during await | position_tracker.py: snapshot pos data before first await in execute_exit() | TBD |
```
