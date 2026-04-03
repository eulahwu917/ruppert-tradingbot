# Sprint 3 Spec — Settlement and Double-Exit Prevention
_CEO authored. DS + Trader review required before Dev touches code._
_Date: 2026-04-03_

---

## Overview

6 issues across 4 files. Prevents double-settlements, phantom settlements, duplicate JSONL writes, and CB bypass on entry.

**Domain assignments:**
- **DS reviews:** ISSUE-025, ISSUE-028, ISSUE-077, ISSUE-023
- **Trader reviews:** ISSUE-033, ISSUE-094

**Pipeline:** DS + Trader review spec → David approves → Dev implements → QA (DS verifies DS-owned fixes, Trader verifies Trader-owned fixes) → CEO approves → commit.
Dev does NOT commit without explicit CEO approval.

---

## Fix 1 — ISSUE-025: Double-settlement race — WS tracker + settlement checker both write settle records

**Files:** `agents/ruppert/trader/position_tracker.py`, `environments/demo/settlement_checker.py`

**The problem:** When a market settles, two separate processes can independently detect it:
1. WS `position_tracker.check_expired_positions()` — detects expiry by ticker parse + REST verify
2. `settlement_checker.py` — runs on schedule, scans all unsettled buys

Both write a `settle` record to the same JSONL file. P&L is counted twice. Capital appears inflated.

`settlement_checker.py` already has an idempotency check via `load_all_unsettled()` — it uses FIFO exit-count matching to skip positions that already have a settle record. But `position_tracker.py`'s `check_expired_positions()` writes DIRECTLY to the JSONL without going through any shared dedup path.

**The fix:** In `position_tracker.check_expired_positions()`, before writing the settle record, check whether a settle or exit record already exists for `(ticker, side)` in today's log. If one exists, skip the write — remove the position from the tracker and return.

Add a pre-write guard inside `check_expired_positions()`:
```python
def _settle_record_exists(ticker: str, side: str) -> bool:
    """Return True if a settle or exit record already exists for (ticker, side) today."""
    log_path = TRADES_DIR / f'trades_{date.today().isoformat()}.jsonl'
    if not log_path.exists():
        return False
    try:
        for line in log_path.read_text(encoding='utf-8').splitlines():
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

In `check_expired_positions()`, before writing `settle_record`:
```python
if _settle_record_exists(ticker, side):
    logger.info(
        '[PositionTracker] check_expired: settle record already exists for %s %s — removing from tracker (no duplicate write)',
        ticker, side
    )
    keys_to_remove.append(key)
    _recently_exited[key] = time.time()
    continue  # skip writing, just clean up tracker
```

**Also scan yesterday's log:** To handle the midnight boundary edge case (position settles just before midnight, process restarts after midnight, check runs again), also scan yesterday's trade log:
```python
def _settle_record_exists(ticker: str, side: str) -> bool:
    from datetime import timedelta
    for day_offset in (0, 1):  # today and yesterday
        check_date = date.today() - timedelta(days=day_offset)
        log_path = TRADES_DIR / f'trades_{check_date.isoformat()}.jsonl'
        if not log_path.exists():
            continue
        try:
            for line in log_path.read_text(encoding='utf-8').splitlines():
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

**Behavior change:** If settlement checker already wrote a settle record, position_tracker skips its own write. Only one settle record per position.

---

## Fix 2 — ISSUE-028: Phantom settlement inferred from `yes_bid >= 99c` without checking `status` field

**File:** `environments/demo/settlement_checker.py`

**The problem:** In `check_settlements()`, when the Kalshi API returns a market without a `result` field, the code falls through to bid-based inference:
```python
elif (yes_bid or 0) >= 99:
    result = 'yes'
elif (yes_bid or 0) <= 1:
    result = 'no'
```

A market priced at 99c is NOT necessarily settled — it can be an active market where the outcome is nearly certain but not yet finalized. Writing a settle record against an active 99c market corrupts the trade log and removes the position from tracking before it actually settles.

**The fix:** Remove the unsafe bid-only inference (no status check). Keep finalized+bid inference ONLY for unambiguous bid values (≥99 or ≤1). Skip with a warning when finalized but bid is ambiguous.

Replace the inference block with:

```python
# BEFORE (unsafe — active 99c markets phantom-settled):
if result in ('yes', 'no'):
    pass
elif status in ('settled', 'finalized'):
    result = 'yes' if (yes_bid or 0) >= 99 else 'no'
elif (yes_bid or 0) >= 99:
    result = 'yes'
elif (yes_bid or 0) <= 1:
    result = 'no'
else:
    continue

# AFTER (safe — only bid inference when status confirms settlement AND bid is unambiguous):
if result not in ('yes', 'no'):
    if status in ('settled', 'finalized'):
        # Status confirms settlement — infer from bid only when unambiguous
        if (yes_bid or 0) >= 99:
            result = 'yes'
        elif (yes_bid or 0) <= 1:
            result = 'no'
        else:
            # Finalized but bid is ambiguous (e.g. 50c) — cannot safely infer
            print(f"  [WARN] {ticker}: status={status} but yes_bid={yes_bid} is ambiguous — skipping")
            continue
    else:
        continue  # Not resolved — skip
```

**Key difference from before:** The old code inferred `result='no'` for ANY finalized market where yes_bid < 99 — including 50c bids. The new code only infers when bid is unambiguous (≥99 or ≤1) and skips with a warning otherwise. Active 99c markets (no finalized status) are never settled.

**Behavior change:** No phantom settlements on active 99c markets. Finalized markets with ambiguous bids are skipped and logged, not incorrectly settled as losses.

---

## Fix 3 — ISSUE-033: `position_monitor` fanout — one exit triggers full rescan of ALL positions

**File:** `agents/ruppert/trader/position_monitor.py`

**The problem:** In `run_polling_scan()`, when an auto-exit is detected, the code calls:
```python
from agents.ruppert.trader.post_trade_monitor import run_monitor as _run_monitor_exit
_run_monitor_exit()
```

`run_monitor()` is a FULL rescan of all open positions. So 10 auto-exits = 10 full rescans, each of which can independently detect and double-settle the same positions the previous rescans already handled. Near-certain double-settlement at scale.

**The fix:** Execute the exit inline without triggering `run_monitor()`. Use `client.sell_position()` directly (already available in scope) and log the trade without a full rescan.

Replace the auto-exit block in `run_polling_scan()`:
```python
if action == 'auto_exit':
    print(f"  [Polling] AUTO-EXIT: {ticker} — {reason}")
    # Execute inline — do NOT call run_monitor() (fanout risk)
    _pm_side = pos.get('side', '')
    _pm_contracts = int(pos.get('contracts', 1) or 1)
    _pm_price = cur_price  # cur_price is set by the check_* functions
    if not acquire_exit_lock(ticker, _pm_side):
        print(f"  [Polling] SKIP: {ticker} exit lock held — another process exiting")
        continue
    try:
        _dry_run = getattr(config, 'DRY_RUN', True)
        if _dry_run:
            _pm_result = {'dry_run': True, 'status': 'simulated'}
        else:
            from agents.ruppert.env_config import require_live_enabled
            require_live_enabled()
            # Use place_order() with 'sell' action — KalshiClient has no sell_position() method
            _pm_result = client.place_order(ticker, _pm_side, _pm_price, _pm_contracts, action='sell')
        _pm_entry_price = normalize_entry_price(pos)
        _pm_pnl = round(((_pm_price - _pm_entry_price) if _pm_side == 'yes'
                         else (_pm_entry_price - _pm_price)) * _pm_contracts / 100, 2)
        _pm_opp = {
            'ticker': ticker, 'title': pos.get('title', ticker),
            'side': _pm_side, 'action': 'exit',
            'yes_price': _pm_price if _pm_side == 'yes' else 100 - _pm_price,
            'market_prob': _pm_price / 100, 'edge': None,
            'size_dollars': round(_pm_contracts * _pm_price / 100, 2),
            'contracts': _pm_contracts, 'source': pos.get('source', 'monitor'),
            'module': pos.get('module', ''), 'timestamp': ts(), 'date': str(date.today()),
            'pnl': _pm_pnl,
            'entry_price': _pm_entry_price,
            'exit_price': _pm_price,
            'scan_price': _pm_price,
            'fill_price': _pm_price,
        }
        log_trade(_pm_opp, _pm_opp['size_dollars'], _pm_contracts, _pm_result)
        log_activity(f'[PositionMonitor] AUTO-EXIT {ticker} {_pm_side.upper()} @ {_pm_price}c — {reason}')
        # Notify position tracker
        try:
            from agents.ruppert.trader import position_tracker as _pt
            _pt.remove_position(ticker, _pm_side)
        except Exception as _pte:
            log_activity(f'[PositionMonitor] WARNING: could not remove {ticker} from tracker: {_pte}')
    except Exception as _exit_err:
        print(f"  [Polling] AUTO-EXIT error for {ticker}: {_exit_err}")
    finally:
        release_exit_lock(ticker, _pm_side)
```

**Note for Dev:** `cur_price` and `contracts` are set by the `check_*` functions — confirm their return signature includes these values in scope. If the tuple unpacking differs from what's shown above, adapt accordingly.

**Note:** `run_polling_scan()` is currently dead code — not called by any active execution path. The fix is applied defensively for correctness if the function is ever re-enabled.

**Behavior change:** Auto-exits execute inline. No full rescan triggered. Each exit is isolated.

---

## Fix 4 — ISSUE-077: Multi-process JSONL writes without file lock → cross-process corruption

**Files:** `agents/ruppert/data_scientist/logger.py`, `agents/ruppert/trader/position_tracker.py`, `environments/demo/settlement_checker.py`

**The problem:** Three separate processes write to the same `trades_YYYY-MM-DD.jsonl` file:
1. `logger.py` (`log_trade()`) — from scan cycles
2. `position_tracker.py` (`execute_exit()`) — from WS feed process
3. `settlement_checker.py` (`check_settlements()`) — from settlement task

All use plain `open(log_path, 'a')` with no file-level locking. On Windows, simultaneous appends from multiple processes can interleave, producing invalid JSON on a line (two JSON objects concatenated without a newline separator).

**The fix:** Use `portalocker` for cross-process file locking on all JSONL write paths.

First, verify `portalocker` is in `requirements.txt`. If not, add it.

Create a shared utility function in `logger.py`:
```python
def _append_jsonl(log_path, record: dict) -> None:
    """Atomically append a single JSON record to a JSONL file.
    Uses portalocker for cross-process safety on Windows.
    Falls back to plain append if portalocker unavailable.
    """
    line = json.dumps(record) + '\n'
    try:
        import portalocker
        with open(log_path, 'a', encoding='utf-8') as f:
            portalocker.lock(f, portalocker.LOCK_EX)
            try:
                f.write(line)
            finally:
                portalocker.unlock(f)
    except ImportError:
        # portalocker not available — fall back to plain append
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(line)
```

Then replace all `open(log_path, 'a') as f: f.write(json.dumps(...) + '\n')` patterns in:
- `logger.py` — the `_today_log_path()` write in `log_trade()`
- `position_tracker.py` — all JSONL write calls in `execute_exit()` and `check_expired_positions()`
- `settlement_checker.py` — the write in `check_settlements()`

**Dev: explicit write paths to convert (all 4 in position_tracker.py + 1 in settlement_checker.py):**
1. `execute_exit()` — main exit record write
2. `execute_exit()` — `settle_loss` branch write
3. `execute_exit()` — abandon record write (DS-NEW-001, already uses try/except)
4. `check_expired_positions()` — settle record write
5. `settlement_checker.py` `check_settlements()` — settle record write

**Note for Dev:** `_append_jsonl()` is defined in `logger.py`. Import it in `position_tracker.py` and `settlement_checker.py`:
```python
from agents.ruppert.data_scientist.logger import _append_jsonl
```
`settlement_checker.py` does not currently import from logger — this new import line is required.

**portalocker fallback note:** The fallback to plain `open()` should also emit a one-time `logger.warning()` so the degradation is visible in logs.

**Behavior change:** JSONL writes are serialized per-file across all processes. No interleaved records.

---

## Fix 5 — ISSUE-023: Exit records bypass schema enrichment — missing fields + no dedup fingerprint

**File:** `agents/ruppert/data_scientist/logger.py` (new functions), `agents/ruppert/trader/position_tracker.py` (callers updated)

**The problem:** `execute_exit()` and `check_expired_positions()` write raw JSON dicts directly to the JSONL file, bypassing `logger.py`. Missing fields: `exit_price`, `settlement_result`, `action_detail`, dedup fingerprint (`_fp`), and schema normalization from `build_trade_entry()`.

**Why NOT routing through `log_trade()`:** `log_trade()` was designed for buy records. It has a dedup fingerprint keyed on `(ticker, side, date, entry_price, contracts)` — if an exit record has the same entry_price and contracts as the original buy, the exit would be silently dropped as a duplicate. Additionally `build_trade_entry()` would overwrite `action_detail` and drop `exit_price` and `settlement_result` fields. Routing through `log_trade()` would break exit logging.

**The fix:** Add two thin wrappers to `logger.py` — `log_exit()` and `log_settle()` — that call `build_trade_entry()` for schema enrichment, use a SEPARATE exit-specific dedup fingerprint set, add pass-through fields for exit/settle-specific data, and call `_append_jsonl()` for the write.

**Step 1: Add a separate dedup set and pass-through field support to `build_trade_entry()` in logger.py.**

Add at module level in `logger.py`:
```python
_logged_exit_fingerprints: set[str] = set()  # separate from buy fingerprints
```

Extend `build_trade_entry()` to accept `**extra_fields` and merge them into the final record after standard fields are set — any key in `extra_fields` that is not already in the built entry is added verbatim:
```python
def build_trade_entry(opportunity, size_dollars, contracts, order_result, **extra_fields):
    # ... existing logic unchanged ...
    entry = { ... }  # existing build logic
    # Merge extra fields (for exit_price, settlement_result, action_detail overrides, etc.)
    for k, v in extra_fields.items():
        entry[k] = v  # extra_fields override built-in values
    return entry
```

**Step 2: Add `log_exit()` in logger.py.**
```python
def log_exit(opportunity: dict, pnl: float, contracts: int, order_result: dict,
             exit_price: float = None, action_detail: str = None) -> None:
    """Log an exit record. Uses separate dedup fingerprint from buy records."""
    global _logged_exit_fingerprints
    try:
        _extra = {}
        if exit_price is not None:
            _extra['exit_price'] = exit_price
        if action_detail is not None:
            _extra['action_detail'] = action_detail

        entry = build_trade_entry(opportunity, pnl, contracts, order_result, **_extra)

        # Exit dedup: key on (ticker, side, date, action, exit_price) — not same as buy key
        _fp_key = f"{entry.get('ticker')}::{entry.get('side')}::{entry.get('date')}::exit::{exit_price}"
        if _fp_key in _logged_exit_fingerprints:
            logger.warning('[Logger] Duplicate exit suppressed: %s', _fp_key)
            return
        _logged_exit_fingerprints.add(_fp_key)
        entry['_exit_fp'] = _fp_key

        log_path = _today_log_path()
        _append_jsonl(log_path, entry)
        log_activity(f"[EXIT] {entry.get('ticker')} {entry.get('side','').upper()} | P&L=${pnl:+.2f}")
    except Exception as e:
        logger.error('[Logger] log_exit() failed: %s', e)
```

**Step 3: Add `log_settle()` in logger.py.**
```python
def log_settle(opportunity: dict, pnl: float, contracts: int, order_result: dict,
               exit_price: float = None, settlement_result: str = None,
               action_detail: str = None) -> None:
    """Log a settle record. Uses separate dedup fingerprint from buy records."""
    global _logged_exit_fingerprints
    try:
        _extra = {}
        if exit_price is not None:
            _extra['exit_price'] = exit_price
        if settlement_result is not None:
            _extra['settlement_result'] = settlement_result
        if action_detail is not None:
            _extra['action_detail'] = action_detail

        entry = build_trade_entry(opportunity, pnl, contracts, order_result, **_extra)

        _fp_key = f"{entry.get('ticker')}::{entry.get('side')}::{entry.get('date')}::settle::{settlement_result}"
        if _fp_key in _logged_exit_fingerprints:
            logger.warning('[Logger] Duplicate settle suppressed: %s', _fp_key)
            return
        _logged_exit_fingerprints.add(_fp_key)
        entry['_exit_fp'] = _fp_key

        log_path = _today_log_path()
        _append_jsonl(log_path, entry)
        log_activity(f"[SETTLE] {entry.get('ticker')} {entry.get('side','').upper()} {settlement_result} | P&L=${pnl:+.2f}")
    except Exception as e:
        logger.error('[Logger] log_settle() failed: %s', e)
```

**Step 4: Update `position_tracker.py` to use `log_exit()` and `log_settle()` instead of direct JSONL writes.**

In `execute_exit()`, replace all direct JSONL writes with:
```python
from agents.ruppert.data_scientist.logger import log_exit as _log_exit
exit_opp = {
    'ticker': ticker, 'title': title, 'side': side, 'action': 'exit',
    'source': 'ws_position_tracker', 'module': module,
    'entry_price': entry_price, 'contracts': quantity, 'pnl': round(pnl, 2),
    'timestamp': datetime.now().isoformat(), 'date': str(date.today()),
}
_log_exit(exit_opp, round(pnl, 2), quantity, {'rule': rule},
          exit_price=exit_price_logged,
          action_detail=f'WS_EXIT {rule} @ {action_detail_price}c (yes_bid={current_bid}c)')
```

In `check_expired_positions()`, replace the direct write with:
```python
from agents.ruppert.data_scientist.logger import log_settle as _log_settle
settle_opp = {
    'ticker': ticker, 'title': pos.get('title',''), 'side': side, 'action': 'settle',
    'source': 'ws_position_tracker', 'module': module,
    'entry_price': entry_price, 'contracts': quantity, 'pnl': round(pnl, 2),
    'timestamp': datetime.now().isoformat(), 'date': str(date.today()),
}
_log_settle(settle_opp, round(pnl, 2), quantity, {'result': result},
            exit_price=settlement_price,
            settlement_result=result,
            action_detail=f'EXPIRY result={result} settlement={settlement_price}c')
```

**Also apply to the settle_loss path** in `execute_exit()` — use `log_settle()` with `settlement_result='yes'` (YES won, our NO is worthless).

**Note for Dev:** Apply Fix 4 (`_append_jsonl`) before this fix — `log_exit()` and `log_settle()` both call `_append_jsonl()`.

**Behavior change:** Exit and settle records are schema-enriched, dedup-protected (separately from buys), and have `exit_price`, `settlement_result`, and `action_detail` preserved. Data quality is consistent.

---

## Fix 6 — ISSUE-094: `position_monitor` places orders without circuit breaker check

**File:** `agents/ruppert/trader/position_monitor.py`

**The problem:** In `evaluate_crypto_entry()` inside `position_monitor.py`, the strategy gate (`should_enter()`) is called but the circuit breaker is NOT checked. This is the same function as in `ws_feed.py` but it's a separate copy that never got the CB gate added. A runaway entry loop in position_monitor bypasses all CB protections.

**The fix:** Add the CB check to `evaluate_crypto_entry()` in `position_monitor.py`, mirroring the pattern already in `ws_feed.py`'s `evaluate_crypto_entry()`.

After the `load_traded_tickers()` / already-traded check, and before building the `opp` dict, add:
```python
# ── Circuit breaker gate ────────────────────────────────────────────────────
# Mirror the exact _WS_MODULE_MAP from ws_feed.py
_WS_MODULE_MAP_PM = {
    ('BTC', 'between'): 'crypto_band_daily_btc',
    ('ETH', 'between'): 'crypto_band_daily_eth',
    ('XRP', 'between'): 'crypto_band_daily_xrp',
    ('DOGE', 'between'): 'crypto_band_daily_doge',
    ('SOL', 'between'): 'crypto_band_daily_sol',
    ('BTC', 'greater'): 'crypto_threshold_daily_btc',
    ('BTC', 'less'):    'crypto_threshold_daily_btc',
    ('ETH', 'greater'): 'crypto_threshold_daily_eth',
    ('ETH', 'less'):    'crypto_threshold_daily_eth',
    ('SOL', 'greater'): 'crypto_threshold_daily_sol',
    ('SOL', 'less'):    'crypto_threshold_daily_sol',
}
_ws_module = _WS_MODULE_MAP_PM.get((asset, strike_type), f'crypto_band_daily_{asset.lower()}')
try:
    import agents.ruppert.trader.circuit_breaker as _cb
    _cb_n = getattr(config, 'CRYPTO_DAILY_CIRCUIT_BREAKER_N',
                    getattr(config, 'CRYPTO_1H_CIRCUIT_BREAKER_N', 3))
    _cb_advisory = getattr(config, 'CRYPTO_DAILY_CIRCUIT_BREAKER_ADVISORY', False)
    _cb_losses = _cb.get_consecutive_losses(_ws_module)
    if _cb_losses >= _cb_n:
        if not _cb_advisory:
            logger.warning(
                '[PositionMonitor] CB TRIPPED: %d consecutive losses for %s — entry blocked',
                _cb_losses, _ws_module
            )
            return
except Exception as _cb_err:
    logger.warning('[PositionMonitor] CB gate failed for %s: %s', _ws_module, _cb_err)
# ── End circuit breaker gate ─────────────────────────────────────────────────
```

**Also required in the same diff:** after the CB gate, when building the `opp` dict, set `opp['module'] = _ws_module` (not `'crypto'`). This ensures losses from this path increment the correct per-asset CB counter.

**Note:** `evaluate_crypto_entry()` in position_monitor.py is currently dead code — not reachable from any active execution path (ws_feed.py is the live entry evaluator). Fix applied defensively.

**Behavior change:** `position_monitor`'s `evaluate_crypto_entry()` now respects the CB. A tripped breaker blocks new entries from this path too.

---

## Batch split

- **Batch 1 (DS):** Fixes 1, 2, 4, 5 — position_tracker.py, settlement_checker.py, logger.py
- **Batch 2 (Trader):** Fixes 3, 6 — position_monitor.py

Apply Batch 1 first. Fix 4 (`_append_jsonl`) must be implemented before Fix 5 (routes through log_trade which uses _append_jsonl).

---

## QA Checklist

**DS verifies (Batch 1):**
1. ISSUE-025: In `check_expired_positions()`, confirm `_settle_record_exists()` called before writing. Confirm positions with existing settle records are removed from tracker without a duplicate write.
2. ISSUE-028: In `settlement_checker.check_settlements()`, confirm bid-only inference (`yes_bid >= 99` without status check) is gone. Confirm only `result in ('yes','no')` or `status in ('settled','finalized')` triggers settlement.
3. ISSUE-077: Confirm `_append_jsonl()` in `logger.py`. Confirm portalocker used with fallback. Confirm all three write paths (logger, position_tracker, settlement_checker) use it.
4. ISSUE-023: Confirm exit records in `execute_exit()` route through `log_trade()`. Confirm settle records in `check_expired_positions()` route through `log_trade()`. Confirm `action` field explicitly set before `log_trade()` call.

**Trader verifies (Batch 2):**
5. ISSUE-033: In `run_polling_scan()`, confirm `run_monitor()` is no longer called on auto-exit. Confirm inline exit logic uses `acquire_exit_lock/release_exit_lock`. Confirm `position_tracker.remove_position()` called after exit.
6. ISSUE-094: In `evaluate_crypto_entry()` in position_monitor.py, confirm CB check present before `opp` dict construction. Confirm it mirrors the ws_feed.py pattern.

**After all QA passes:** DS checks for existing duplicate settle records in today's trade log and removes any found.

---

## Change Log Entry (after commit)

Add to `memory/agents/fix-changelog.md`:

```
## Sprint 3 — 2026-04-03

| Issue ID | Title | Fix Summary | Commit |
|----------|-------|-------------|--------|
| ISSUE-025 | Double-settlement race | position_tracker.py: _settle_record_exists() check before write in check_expired_positions() | TBD |
| ISSUE-028 | Phantom settlement from high bid | settlement_checker.py: removed bid-only inference; status=finalized required | TBD |
| ISSUE-077 | Multi-process JSONL writes | logger.py: _append_jsonl() with portalocker; used by position_tracker + settlement_checker | TBD |
| ISSUE-023 | Exit records bypass log_trade() | position_tracker.py: execute_exit() + check_expired_positions() routed through log_trade() | TBD |
| ISSUE-033 | position_monitor fanout on exit | position_monitor.py: inline exit replaces run_monitor() call | TBD |
| ISSUE-094 | position_monitor no CB check | position_monitor.py: CB gate added to evaluate_crypto_entry() | TBD |
```
