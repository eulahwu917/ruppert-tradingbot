# Sprint 2 Spec — Capital and Position State Accuracy
_CEO authored. DS + Trader review required before Dev touches code._
_Date: 2026-04-03_

---

## Overview

8 issues across 5 files. Prevents ghost positions, wrong sizing, and silent capital errors.

**Domain assignments:**
- **DS reviews:** ISSUE-029/099, ISSUE-055, ISSUE-056, ISSUE-051
- **Trader reviews:** ISSUE-024, ISSUE-052, ISSUE-078, ISSUE-031

**Pipeline:** DS + Trader review spec → David approves → Dev implements → QA verifies → CEO approves → commit.
Dev does NOT commit without explicit CEO approval.

---

## Fix 1 — ISSUE-024: `state.json` non-atomic write

**File:** `environments/demo/ruppert_cycle.py`
**Function:** `save_state()`

**The problem:** `save_state()` calls `_state_path.write_text(...)` directly. If the process crashes mid-write (power loss, OOM, kill signal), the file is left partially written. On next startup, `load_traded_tickers()` reads a corrupted `state.json` — JSON parse fails silently, `traded_tickers` is empty, and the bot re-enters all positions it already has open.

**The fix:** Write to a temp file first, then atomically rename. This is the standard "write-replace" pattern.

In `save_state()`, replace:
```python
_state_path.write_text(json.dumps(_state_data, indent=2), encoding='utf-8')
```

With:
```python
_tmp_path = _state_path.with_suffix('.tmp')
_tmp_path.write_text(json.dumps(_state_data, indent=2), encoding='utf-8')
_tmp_path.replace(_state_path)
```

`Path.replace()` is atomic on POSIX and best-effort atomic on Windows (NTFS rename is atomic when source and dest are on same volume, which they are here).

**Behavior change:** `state.json` is never partially written. A crash during write leaves the old version intact.

---

## Fix 2 — ISSUE-052: No process lock on scan cycles → overlapping Task Scheduler invocations

**File:** `environments/demo/ruppert_cycle.py`
**Function:** `run_cycle()` — add at the very top

**The problem:** Task Scheduler can fire a second scan cycle before the first one finishes (e.g. a slow 7AM cycle still running when the 3PM one starts). Each cycle loads `traded_tickers` and capital independently at startup. Both can see the same open capacity, both pass strategy gates for the same ticker, and both place orders — doubling position size.

**The fix:** Create a PID lock file at cycle start. If the lock file exists and the PID in it is still running, exit immediately with a log warning. Remove the lock file on exit (clean or crash — use try/finally).

Add a lock file helper at module level:
```python
_LOCK_FILE = Path(__file__).parent / 'logs' / 'ruppert_cycle.lock'

def _acquire_cycle_lock(mode: str) -> bool:
    """Try to acquire cycle lock. Returns True if acquired, False if already running."""
    import os
    if _LOCK_FILE.exists():
        try:
            locked_pid = int(_LOCK_FILE.read_text(encoding='utf-8').strip())
            # Check if that process is still alive
            try:
                os.kill(locked_pid, 0)  # Signal 0 = existence check, no actual signal
                print(f'  [Lock] Cycle already running (PID {locked_pid}) — aborting {mode}')
                log_activity(f'[CycleLock] Aborted {mode}: PID {locked_pid} still running')
                return False
            except (ProcessLookupError, PermissionError):
                # Process is dead — stale lock, remove it
                print(f'  [Lock] Stale lock (PID {locked_pid} dead) — clearing')
                _LOCK_FILE.unlink(missing_ok=True)
        except Exception as _le:
            print(f'  [Lock] Could not read lock file: {_le} — proceeding without lock')
            return True
    _LOCK_FILE.write_text(str(os.getpid()), encoding='utf-8')
    return True

def _release_cycle_lock():
    """Release the cycle lock file."""
    try:
        _LOCK_FILE.unlink(missing_ok=True)
    except Exception:
        pass
```

In `run_cycle()`, add at the very start (before anything else):
```python
if not _acquire_cycle_lock(mode):
    sys.exit(0)
try:
    # ... all existing run_cycle() code ...
finally:
    _release_cycle_lock()
```

**Note on Windows:** `os.kill(pid, 0)` works on Windows for existence check (raises `ProcessLookupError` if dead, `PermissionError` if alive-but-restricted). This is safe to use here.

**Behavior change:** Only one scan cycle can run at a time. Concurrent invocations exit immediately with a log entry. Lock is always released on exit.

---

## Fix 3 — ISSUE-029 + ISSUE-099: Failed orders logged as real trades → phantom capital deployment

**Files:** `agents/ruppert/trader/trader.py`, `agents/ruppert/trader/main.py`

**The problem:** In `Trader.execute_opportunity()`, when `client.place_order()` throws an exception, the failure path logs the trade with `action='buy'` (inherited from the opportunity dict) and `size_dollars=strategy_size` (the full requested amount). This means `get_daily_exposure()` counts the failed order's full size against the daily cap, even though no contracts were filled. Ghost capital deployment accumulates all day.

ISSUE-099: the `fill_contracts=0` is already logged correctly on failure, but `size_dollars` is still the strategy-requested size — not $0. Both bugs combined mean: failed order logs as a real buy at full cost.

**The fix:** Move `log_trade()` to AFTER a successful `place_order()`. On failure, log with `action='failed_order'` so it's traceable but excluded from cap calculations.

In `Trader.execute_opportunity()`:

1. Remove the `log_trade()` call that currently happens before `place_order()`.
2. After a successful order result, call `log_trade()` with the actual fill data.
3. On exception, log a `failed_order` record instead:

```python
try:
    if self.dry_run:
        result = {'dry_run': True, 'status': 'simulated'}
    else:
        require_live_enabled()
        result = self.client.place_order(ticker, side, price_cents, contracts)
except Exception as e:
    # Log as failed_order — excluded from daily cap calculations
    log_activity(f'[Trader] Order FAILED for {ticker}: {e}')
    failed_record = {
        'action': 'failed_order',
        'ticker': ticker,
        'side': side,
        'size_dollars': 0.0,   # zero cost — no fill
        'contracts': 0,
        'reason': str(e),
        'timestamp': ts(),
        'date': str(date.today()),
        'module': opportunity.get('module', ''),
        'source': opportunity.get('source', ''),
    }
    log_trade(failed_record, 0.0, 0, {})
    return False

# Success path — log with actual fill data
log_trade(opportunity, size, contracts, result)
```

**Critical implementation note for Dev:** `build_trade_entry()` in logger.py derives `action` from `opportunity.get('action', 'buy')`. If you pass the failed_record dict to `log_trade()`, you must set `failed_record['action'] = 'failed_order'` explicitly — otherwise it logs as `action='buy'` and the bug is not fixed.

**Also fix in `get_daily_exposure()`** (logger.py): `'failed_order'` must be explicitly added to the exclusion filter. Check `get_daily_exposure()` for the list of actions it sums — `'failed_order'` is NOT currently excluded. Add it to the exclusion set alongside any other non-buy actions already excluded.

**Also preserve the inner try/except:** The current code wraps the failure log call. Do not drop that wrapper in the refactor.

**Behavior change:** Failed orders no longer consume daily cap. They are traceable in logs with `action='failed_order'`. Capital accounting is accurate.

---

## Fix 4 — ISSUE-078: `Trader.__init__` crashes on API error → entire scan cycle dies

**File:** `agents/ruppert/trader/trader.py`
**Method:** `Trader.__init__()`

**The problem:**
```python
def __init__(self, dry_run=True):
    self.client = KalshiClient()
    self.dry_run = dry_run
    self.bankroll = self.client.get_balance()   # ← raises on API error
```
If Kalshi returns a 429, 5xx, or network timeout here, the exception propagates uncaught and kills the entire scan cycle before any evaluation happens. Not a single market gets evaluated.

**The fix:** Wrap `get_balance()` in try/except. On failure, fall back to `capital.get_capital()`:

```python
def __init__(self, dry_run=True):
    self.client = KalshiClient()
    self.dry_run = dry_run
    try:
        self.bankroll = self.client.get_balance()
        log_activity(f"Trader initialized. Balance: ${self.bankroll:.2f} | Dry run: {dry_run}")
    except Exception as _e:
        from agents.ruppert.data_scientist.capital import get_capital as _get_capital
        self.bankroll = _get_capital()
        log_activity(
            f"[Trader] WARNING: get_balance() failed ({_e}) — using capital.get_capital() fallback: ${self.bankroll:.2f}"
        )
```

**Also fix in the same commit:** `refresh_balance()` has the same unguarded `get_balance()` call. Wrap it identically:
```python
def refresh_balance(self):
    try:
        self.bankroll = self.client.get_balance()
    except Exception as _e:
        from agents.ruppert.data_scientist.capital import get_capital as _get_capital
        self.bankroll = _get_capital()
        log_activity(f'[Trader] WARNING: refresh_balance() failed ({_e}) — using capital.get_capital() fallback')
```

**Behavior change:** A transient Kalshi API error at startup no longer kills the cycle. Trader initializes with the last-known capital figure and the cycle proceeds.

---

## Fix 5 — ISSUE-031: `ruppert_cycle.py` auto-exits don't call `position_tracker.remove_position()`

**File:** `environments/demo/ruppert_cycle.py`
**Function:** `run_position_check()`

**The problem:** When `run_position_check()` decides to auto-exit a weather position, it calls `log_trade()` and `client.sell_position()`, but never calls `position_tracker.remove_position()`. The WS position tracker still thinks that position is open and will attempt to exit it again on the next price tick. This causes duplicate exit orders.

**The fix:** After every successful auto-exit in `run_position_check()`, call `position_tracker.remove_position()`.

In the auto-exit execution block (inside the `for action, ticker, side, price, contracts, pnl in actions_taken:` loop), after the `log_trade()` call:

```python
# Notify position tracker — prevent WS from attempting a second exit
try:
    from agents.ruppert.trader import position_tracker as _pt
    _pt.remove_position(ticker, side)
    log_activity(f'[PositionCheck] Removed {ticker} {side} from tracker after auto-exit')
except Exception as _pt_err:
    log_activity(f'[PositionCheck] WARNING: could not remove {ticker} from tracker: {_pt_err}')
```

Add this in BOTH the dry-run path and the live path (after their respective `log_trade()` calls).

**Lock ordering (critical):** Call `remove_position()` BEFORE `release_exit_lock()`. Do not reverse this order.

**Note for Dev:** `_recently_exited` cooldown dict in position_tracker is not updated by this cycle path — only `_tracked` removal is the primary guard. Add a comment in the code documenting this so future maintainers don't assume `_recently_exited` is always populated on exit.

**Behavior change:** Auto-exits from the scan cycle are immediately reflected in the WS position tracker. No duplicate exit attempts.

---

## Fix 6 — ISSUE-055: Settled positions resurrected by post-scan audit

**File:** `agents/ruppert/data_scientist/data_agent.py`
**Function:** `run_post_scan_audit()` (and specifically the `add_position()` call path inside it)

**The problem:** `run_post_scan_audit()` reads open buy records and calls `position_tracker.add_position()` for any position it finds in the trade log. But it doesn't check whether a settle/exit record exists for that position. So recently settled positions (settle record written in the last few minutes) get re-added to the tracker and the WS feed attempts to exit them again.

**The fix:** Before calling `add_position()` for any buy record, check whether a settle or exit record exists for that (ticker, side) pair in today's trade log. If one exists, skip — the position is already closed.

In `run_post_scan_audit()`, wherever `position_tracker.add_position()` is called, add a pre-check:

```python
def _has_close_record(ticker: str, side: str, trades_dir: Path) -> bool:
    """Return True if a settle or exit record exists for (ticker, side) today."""
    today_log = trades_dir / f'trades_{date.today().isoformat()}.jsonl'
    if not today_log.exists():
        return False
    try:
        for line in today_log.read_text(encoding='utf-8').splitlines():
            try:
                rec = json.loads(line.strip())
                if (rec.get('ticker') == ticker and
                        rec.get('side') == side and
                        rec.get('action') in ('exit', 'settle')):
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False
```

Then before each `add_position()` call:
```python
if _has_close_record(ticker, side, TRADES_DIR):
    logger.debug('[DataAgent] Skipping add_position for %s %s — close record exists', ticker, side)
    continue
```

**Implementation note for Dev:** Place the `_has_close_record()` guard inside `_register_missing_positions()` itself (the function that calls `add_position()`), not just at its call sites. This ensures the protection applies regardless of how the function is invoked.

**Behavior change:** The post-scan audit never resurrects a position that has already been closed in today's log.

---

## Fix 7 — ISSUE-056: `_cleanup_duplicates()` deletes exit/settle records sharing a `trade_id` with a buy

**File:** `agents/ruppert/data_scientist/data_agent.py`
**Function:** `_cleanup_duplicates()` (or equivalent dedup function)

**The problem:** The dedup logic finds records with the same `trade_id` and keeps only one. If an exit or settle record somehow shares a `trade_id` with a buy record (can happen when `trade_id` is derived from the ticker rather than truly random), the dedup logic deletes the exit record. The position appears permanently open; capital is never freed.

**The fix:** In `_cleanup_duplicates()`, never delete a record with `action` in `('exit', 'settle', 'correction', 'failed_order', 'abandoned')` when deduplicating by `trade_id`. Only deduplicate `action='buy'` or `action='open'` records against each other.

**Implementation note for Dev:** `_cleanup_duplicates()` uses a **streaming seen-set pattern**, not a grouping approach. Do NOT rewrite the function. Instead, adapt the guard to the existing pattern: when a record has a protected action, always keep it regardless of whether its `trade_id` has been seen. Also add `'exit_correction'` to the protected set. Example:

```python
_PROTECTED_ACTIONS = {'exit', 'settle', 'correction', 'exit_correction', 'failed_order', 'abandoned'}

for rec in records:
    trade_id = rec.get('trade_id')
    action = rec.get('action', 'buy')
    if action in _PROTECTED_ACTIONS:
        keep.append(rec)   # always keep — never dedup protected records
        continue
    if trade_id and trade_id in seen_ids:
        continue  # duplicate buy — discard
    seen_ids.add(trade_id)
    keep.append(rec)
```

Adapt to the exact variable names in the existing function.

**Also:** When a protected record IS preserved despite being in the dupe list, add a `log_activity()` warning so audits can see it:
```python
if action in _PROTECTED_ACTIONS:
    log_activity(f'[DataAgent] Preserved protected record (action={action}, trade_id={trade_id}) — not deduped')
    keep.append(rec)
    continue
```

**Behavior change:** Exit and settle records are never deleted by the dedup pass, regardless of `trade_id` collision.

---

## Fix 8 — ISSUE-051: `get_capital()` silently returns $10,000 on any failure

**File:** `agents/ruppert/data_scientist/capital.py`
**Function:** `get_capital()`

**The problem:** The `except Exception` at the bottom of `get_capital()` returns `_DEFAULT_CAPITAL` ($10,000) with only a `logger.warning()`. No Telegram alert. If the deposits file is missing, the API fails, or the P&L compute crashes, every module happily sizes trades against $10,000 even if actual capital is $500 or $50,000. The error is invisible until David manually checks.

**The fix:** Add a Telegram alert with 4-hour dedup on fallback. The dedup prevents alert spam if every scan cycle triggers the same failure.

Add a dedup file path at module level:
```python
_CAPITAL_FALLBACK_ALERT_FILE = _LOGS_DIR / 'capital_fallback_last_alert.json'
_CAPITAL_FALLBACK_ALERT_COOLDOWN_SECS = 4 * 3600  # 4 hours
```

In the `except Exception` block of `get_capital()`:
```python
except Exception as e:
    logger.warning(f"[Capital] get_capital() failed: {e} — using ${_DEFAULT_CAPITAL:.0f} default")
    try:
        _should_alert = True
        if _CAPITAL_FALLBACK_ALERT_FILE.exists():
            _last = json.loads(_CAPITAL_FALLBACK_ALERT_FILE.read_text(encoding='utf-8'))
            _elapsed = time.time() - _last.get('ts', 0)
            if _elapsed < _CAPITAL_FALLBACK_ALERT_COOLDOWN_SECS:
                _should_alert = False
        if _should_alert:
            from agents.ruppert.data_scientist.logger import send_telegram as _send_tg
            _send_tg(f'🚨 CAPITAL ERROR: get_capital() failed — using ${_DEFAULT_CAPITAL:.0f} fallback. All sizing may be wrong. Reason: {e}')
            _CAPITAL_FALLBACK_ALERT_FILE.write_text(
                json.dumps({'ts': time.time(), 'reason': str(e)}), encoding='utf-8'
            )
    except Exception as _alert_err:
        logger.warning(f'[Capital] Could not send fallback alert: {_alert_err}')
    return _DEFAULT_CAPITAL
```

Add `import time` at the top of `capital.py` if not already present.

**Dev notes:** (1) Add `import time` at the top of `capital.py` if not already present. (2) Cap the error string in the Telegram message to 500 chars: `str(e)[:500]`. (3) Add a `log_activity()` call alongside the Telegram alert so the failure appears in the activity log too.

**Behavior change:** When `get_capital()` falls back to $10,000, David gets a Telegram alert within seconds. Subsequent failures within 4 hours are suppressed to avoid spam.

---

## QA Checklist (after Dev implements all 8 fixes)

1. **ISSUE-024:** In `save_state()`, confirm `_tmp_path.write_text()` + `_tmp_path.replace()` pattern. Confirm no direct `write_text()` on `_state_path`.
2. **ISSUE-052:** Confirm `_acquire_cycle_lock()` called at top of `run_cycle()`. Confirm `_release_cycle_lock()` in `finally` block. Confirm stale lock detection uses `os.kill(pid, 0)`.
3. **ISSUE-029/099:** Confirm `log_trade()` is called AFTER `place_order()` succeeds. Confirm `failed_order` records have `size_dollars=0.0`. Confirm `get_daily_exposure()` excludes `action='failed_order'` records.
4. **ISSUE-078:** Confirm `get_balance()` wrapped in try/except. Confirm fallback to `capital.get_capital()`. Confirm fallback is logged.
5. **ISSUE-031:** Confirm `position_tracker.remove_position()` called after every auto-exit in `run_position_check()`. Confirm in both dry-run and live paths.
6. **ISSUE-055:** Confirm `_has_close_record()` helper exists in `data_agent.py`. Confirm it's called before every `add_position()` in post-scan audit. Confirm positions with close records are skipped.
7. **ISSUE-056:** Confirm `_PROTECTED_ACTIONS` set defined. Confirm dedup logic never deletes records with protected actions. Confirm buy-only dedup still works correctly.
8. **ISSUE-051:** Confirm `send_telegram()` called in `except` block of `get_capital()`. Confirm 4-hour cooldown file check. Confirm `import time` present.

**After QA passes:** DS runs full data audit to verify capital figure is correct.

---

## Change Log Entry (after commit)

Add to `memory/agents/fix-changelog.md`:

```
## Sprint 2 Changes — 2026-04-03

| Issue ID | Title | Fix Summary | Commit |
|----------|-------|-------------|--------|
| ISSUE-024 | state.json atomic write | ruppert_cycle.py: write-to-tmp + replace in save_state() | TBD |
| ISSUE-052 | Process lock on scan cycles | ruppert_cycle.py: PID lock file, stale detection, try/finally release | TBD |
| ISSUE-029/099 | Failed orders phantom capital | trader.py: log_trade() moved after place_order(); failed_order action logs 0 size | TBD |
| ISSUE-078 | Trader init crash on API error | trader.py: get_balance() wrapped try/except, fallback to capital.get_capital() | TBD |
| ISSUE-031 | Cycle exits don't remove from tracker | ruppert_cycle.py: remove_position() called after every auto-exit | TBD |
| ISSUE-055 | Settled positions resurrected | data_agent.py: _has_close_record() check before add_position() | TBD |
| ISSUE-056 | _cleanup_duplicates deletes exit records | data_agent.py: PROTECTED_ACTIONS guard — never dedup exit/settle/correction | TBD |
| ISSUE-051 | Capital fallback silent | capital.py: send_telegram() on fallback, 4-hour dedup | TBD |
```
