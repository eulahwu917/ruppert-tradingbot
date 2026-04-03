# Sprint 5 Dev Notes

**Dev:** Ruppert Dev Agent  
**Date:** 2026-04-03  
**Spec:** `agents/ruppert/data_scientist/specs/SPRINT5-SPEC.md`

---

## Batch 1 — ISSUE-076 + ISSUE-047

**Completed:** 2026-04-03

### ISSUE-076 — Portalocker file lock

Implemented `_rw_locked(path, fn)` in `circuit_breaker.py`:
- Opens state file in `r+` mode; falls back to `w+` on `FileNotFoundError` (cold start)
- Acquires `portalocker.LOCK_EX` before read-modify-write
- Releases lock via `portalocker.unlock(fh)` in `finally` block
- Replaced `increment_consecutive_losses()`, `reset_consecutive_losses()`, and `update_global_state()` to all go through `_rw_locked`
- `_read_full_state()` left as-is (read-only, per spec)

### ISSUE-047 — Per-asset CB key confirmation

Confirmed `_ws_module` in `ws_feed.py` (line ~360) is resolved from `_WS_MODULE_MAP` which maps `(asset, strike_type)` → per-asset key (e.g. `crypto_band_daily_btc`, `crypto_dir_15m_eth`). Per-asset CB coverage is correct — no code change needed to ws_feed.py.

Added CB trip log line in `increment_consecutive_losses()`:
- When `new_count >= threshold`: logs at `WARNING` level with explicit module name, count, and threshold
- Otherwise logs at `INFO` level as before
- Threshold is read from config: `CRYPTO_15M_CIRCUIT_BREAKER_N` → `CRYPTO_DAILY_CIRCUIT_BREAKER_N` → `CRYPTO_1H_CIRCUIT_BREAKER_N` → 3 (fallback chain covers all modules)

### Discrepancies vs Spec

- **Spec says** to use `try r+ / fallback w+`. Implemented exactly. ✅
- **Spec says** `_read_full_state()` does NOT need a lock. Confirmed — left unchanged. ✅
- **Note:** `_write_full_state()` still exists (used by `set_module_state()` and `get_module_state()` reset path). The spec only required locking the three write functions; the existing atomic tmp-write path for `set_module_state` is not a race target (single caller pattern). No change needed there.

---

## Batch 2 — ISSUE-044 + ISSUE-043

**Completed:** 2026-04-03

### ISSUE-044 — Timezone fix

- Added `_today_pdt()` helper to `ws_feed.py` (uses `pytz.timezone('America/Los_Angeles')`)
- Replaced `str(date.today())` on line 563 in `ws_feed.py` with `_today_pdt()`
- Added `_today_pdt()` equivalent to `position_tracker.py`
- Replaced `str(date.today())` in trade record `date` fields (execute_exit, settle path, abandon path)
- Left `datetime.now()` on lines 73 and 943 (cosmetic log timestamps, per spec)
- `date.today()` for `_settle_record_exists` log file lookup left as-is (file-name lookup, not a trade record date)

### ISSUE-043 — EXIT_GAIN_PCT hardened

- Replaced `getattr(config, 'EXIT_GAIN_PCT', 0.70)` with explicit `None` check
- Raises `ImportError` with descriptive message if key is missing from config
- Config has `EXIT_GAIN_PCT = 0.90` — no runtime behavior change expected

### Discrepancies vs Spec

- None found.

---

## Batch 3 — ISSUE-042 Part A

**Completed:** 2026-04-03

### Changes made to `position_tracker.py`

1. **Removed NO-side flip from `add_position()`:**
   - Removed `size_dollars` pre-flip calculation comment/block
   - Removed `if side == 'no' and entry_price < 50: entry_price = 100 - entry_price` block
   - `size_dollars` now computed simply as `entry_price * quantity / 100` (no pre/post distinction)

2. **Removed legacy migration block from `_load()`:**
   - Removed the `if value.get('side') == 'no' and entry_price < 50: entry_price = 100 - entry_price` migration
   - Removed the `migrated` counter and related logging

3. **Added `and side == 'yes'` guard to Design D stop-loss block in `check_exits()`:**
   - Guard condition now: `if pos.get('module', '').startswith('crypto_dir_15m_') and pos.get('added_at') and side == 'yes':`
   - Prevents Design D tier 1/2/3 stops (which compare `yes_bid < entry_price * pct`) from firing on NO positions (where `entry_price=3c` would make `entry_price * 0.20 = 0.6c`, an effectively unreachable threshold)

4. **Cleaned up stale comments in `execute_exit()` and `check_expired_positions()`:**
   - Removed "entry_price is unreliable due to NO-side flip" comments
   - Updated P&L formula comment in execute_exit NO path to reflect correct NO price convention
   - Updated NO-loss settlement path comment in check_expired_positions to remove flip reference

### Discrepancies vs Spec

- **execute_exit settle_loss path:** Spec says clean up "entry_price is unreliable" comments. There was one in the `settle_loss` branch. Removed and replaced with accurate comment.

---

## Batch 3 — ISSUE-042 Part A — QA Blocker Fix

**Fixed:** 2026-04-03 (post-QA crash report)

### Bug: NameError on `side` in `check_exits()` daily stop block

QA identified a NameError: in `check_exits()`, `side` was never assigned as a local variable. The Design D guard used `key[1] == 'yes'` inline, but the daily write-off block below referenced `side` directly:

```python
_wo_key = (ticker, side, int(_mins_left))
```

This would crash on the first daily write-off event.

### Fixes applied to `position_tracker.py`

1. **Added `side = key[1]`** immediately after `if not pos: continue` — ensures `side` is always in scope for all downstream code in the loop body.

2. **Updated Design D guard** from `key[1] == 'yes'` → `side == 'yes'` — now uses the local variable consistently.

3. **Cleaned `add_position()` docstring** — removed stale "BEFORE any NO-side price flip" language. The NO-side flip was removed in the Batch 3 implementation; the docstring was not updated at the time. Now reads cleanly: `computed as entry_price * quantity / 100.`

### Status

Handed to QA. Do NOT commit Batch 2 or Batch 3 until QA pass.
