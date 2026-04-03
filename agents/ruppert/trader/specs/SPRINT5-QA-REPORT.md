# Sprint 5 QA Report
**QA Agent:** Ruppert QA  
**Date:** 2026-04-03  
**Spec:** `agents/ruppert/data_scientist/specs/SPRINT5-SPEC.md`  
**Dev Notes:** `agents/ruppert/dev/SPRINT5-DEV-NOTES.md`  
**Files Reviewed:**
- `agents/ruppert/trader/circuit_breaker.py`
- `agents/ruppert/data_analyst/ws_feed.py`
- `agents/ruppert/trader/position_tracker.py`

---

## ISSUE-076 — CB TOCTOU Race (File Lock)

**Verdict: PASS**

### Checks

1. **`increment_consecutive_losses()` uses `_rw_locked()`** — ✅ CONFIRMED  
   Calls `_rw_locked(path, _mutate)` with a closure that reads, mutates, and writes back.

2. **`reset_consecutive_losses()` uses `_rw_locked()`** — ✅ CONFIRMED  
   Same pattern — `_rw_locked(path, _mutate)`.

3. **`update_global_state()` uses `_rw_locked()`** — ✅ CONFIRMED  
   Calls `_rw_locked(path, _mutate)` wrapped in a try/except.

4. **`_rw_locked()` handles cold start (FileNotFoundError → w+)** — ✅ CONFIRMED  
   ```python
   try:
       fh = open(path, 'r+', encoding='utf-8')
   except FileNotFoundError:
       fh = open(path, 'w+', encoding='utf-8')
   ```
   Exactly per spec. `os.makedirs()` also called first.

5. **`_read_full_state()` left unlocked** — ✅ CONFIRMED  
   Opens with a plain `open()`, no portalocker call.

6. **Lock released in `finally`** — ✅ CONFIRMED  
   ```python
   with fh:
       portalocker.lock(fh, portalocker.LOCK_EX)
       try:
           ...
       finally:
           portalocker.unlock(fh)
   ```
   Lock is always released even if `fn(state)` raises.

**All ISSUE-076 checks pass.**

---

## ISSUE-047 — CB Trip Logging (Per-Asset)

**Verdict: PASS**

### Checks

1. **CB trip log in `increment_consecutive_losses()` names the module** — ✅ CONFIRMED  
   ```python
   if _new_count[0] >= cb_n:
       logger.warning(
           '[circuit_breaker] TRIP: %s consecutive_losses=%d hit threshold=%d (window=%s)',
           module, _new_count[0], cb_n, window_ts,
       )
   else:
       logger.info(
           '[circuit_breaker] %s: consecutive_losses=%d (window=%s)',
           module, _new_count[0], window_ts,
       )
   ```
   - Module name explicitly logged at WARNING level on threshold crossing
   - Threshold value included for observability
   - Non-trip path still logs at INFO
   - `_new_count` uses a mutable cell `[0]` to pass count out of `_mutate()` closure — clean pattern

2. **Per-asset CB key in ws_feed.py** — ✅ CONFIRMED  
   `_WS_MODULE_MAP` maps `(asset, strike_type)` tuples to per-asset keys:
   ```python
   _WS_MODULE_MAP = {
       ('BTC', 'between'): 'crypto_band_daily_btc',
       ('ETH', 'between'): 'crypto_band_daily_eth',
       ...
   }
   _ws_module = _WS_MODULE_MAP.get((asset, strike_type), f'crypto_band_daily_{asset.lower()}')
   ```
   CB check at line ~469 uses `_ws_module` — per-asset, not generic.

**All ISSUE-047 checks pass.**

---

## ISSUE-044 — Timezone Fix (`date.today()` → `_today_pdt()`)

**Verdict: PASS**

### Checks

1. **`_today_pdt()` added to `ws_feed.py`** — ✅ CONFIRMED  
   ```python
   def _today_pdt() -> str:
       """Return today's date string in PDT/PST (America/Los_Angeles), formatted YYYY-MM-DD."""
       return datetime.now(pytz.timezone('America/Los_Angeles')).strftime('%Y-%m-%d')
   ```

2. **`_today_pdt()` added to `position_tracker.py`** — ✅ CONFIRMED  
   Identical helper defined near top of file, same implementation.

3. **`str(date.today())` replaced in trade record `date` fields** — ✅ CONFIRMED  
   - `ws_feed.py` `evaluate_crypto_entry()`: `opp['date'] = _today_pdt()` ✅
   - `position_tracker.py` `execute_exit()` — settle_loss path: `'date': _today_pdt()` ✅
   - `position_tracker.py` `execute_exit()` — normal exit path: `'date': _today_pdt()` ✅
   - `position_tracker.py` `execute_exit()` — abandonment record: `'date': _today_pdt()` ✅
   - `position_tracker.py` `check_expired_positions()` — settle_opp: `'date': _today_pdt()` ✅

4. **Cosmetic timestamps left alone** — ✅ CONFIRMED  
   - `ts()` in ws_feed.py: `datetime.now().strftime(...)` — untouched (cosmetic)
   - `_write_heartbeat()` heartbeat file: `datetime.now().isoformat()` — untouched (cosmetic)
   - `_settle_record_exists()` in position_tracker.py: `date.today()` — left as-is (file-name lookup, not a trade record date field)

**All ISSUE-044 checks pass.**

---

## ISSUE-043 — EXIT_GAIN_PCT Hardened

**Verdict: PASS**

### Checks

1. **Explicit `None` check replacing silent 0.70 fallback** — ✅ CONFIRMED  
   ```python
   EXIT_GAIN_PCT      = getattr(config, 'EXIT_GAIN_PCT', None)
   if EXIT_GAIN_PCT is None:
       raise ImportError('[position_tracker] EXIT_GAIN_PCT not found in config — check config.py')
   ```
   Fails loudly at import time. Config has `EXIT_GAIN_PCT = 0.90` — no runtime behavior change.

**All ISSUE-043 checks pass.**

---

## ISSUE-042 Part A — NO-Side Flip Removal

**Verdict: FAIL**

### Checks

1. **NO-side flip removed from `add_position()`** — ✅ CONFIRMED  
   The `if side == 'no' and entry_price < 50: entry_price = 100 - entry_price` block is absent from the code.

2. **size_dollars pre-flip block gone** — ✅ CONFIRMED  
   `size_dollars` computation is now simply:
   ```python
   if size_dollars is None:
       size_dollars = round(entry_price * quantity / 100, 2)
   ```
   No pre/post distinction.

3. **Legacy migration block removed from `_load()`** — ✅ CONFIRMED  
   The NO-side flip migration (`if value.get('side') == 'no' and entry_price < 50...`) is absent. The remaining "legacy" key-format handling (`if '::' in key_str` else ticker-only) is a different, still-valid legacy path — correct to leave.

4. **`side = key[1]` introduced in `check_exits()` loop** — ❌ FAIL  
   **This is the blocker.** The spec requires `side = key[1]` to be introduced near the top of the `for key in matching_keys:` loop. Instead, Dev used `key[1] == 'yes'` directly in the Design D guard:
   ```python
   if pos.get('module', '').startswith('crypto_dir_15m_') and pos.get('added_at') and key[1] == 'yes':
   ```
   This guard itself functions correctly — but **`side` is never defined in the loop body**.

   The problem: the daily stop-loss block that runs further down **also uses `side`**:
   ```python
   _wo_key = (ticker, side, int(_mins_left))
   ```
   Since `side` is never assigned in the loop, this line will raise `NameError: name 'side' is not defined` the first time a `crypto_band_daily_*` or `crypto_threshold_daily_*` position hits the write-off path (yes_bid ≤ 1 with < 20 min remaining).

   **This is a live crash bug.** Any daily contract nearing settlement at a penny would NameError and kill the ws_feed async loop context for that position tick.

   **Required fix:** Add `side = key[1]` at the top of the for loop (immediately after `pos = _tracked.get(key)`) and update the Design D guard to use `side == 'yes'`:
   ```python
   pos = _tracked.get(key)
   if not pos:
       continue
   side = key[1]   # ← ADD THIS
   ...
   if pos.get('module', '').startswith('crypto_dir_15m_') and pos.get('added_at') and side == 'yes':
   ```

5. **Design D block guard includes `and side == 'yes'`** — ⚠️ PARTIAL  
   The guard uses `key[1] == 'yes'` which is functionally equivalent for the guard condition itself. But because `side` was never defined, the `_wo_key` line below crashes. If `side = key[1]` is added at the loop top (see above), the guard should be updated to use `side == 'yes'` to be consistent.

6. **Stale "entry_price is unreliable" comments removed from `execute_exit()`** — ✅ CONFIRMED  
   `execute_exit()` NO-side comments now accurately describe the correct convention:
   ```python
   # NO position: entry_price and exit_price are both in NO-side cents.
   # entry_price is stored as NO price (e.g. 70c if bought when YES=30c).
   ```

7. **Stale comments removed from `check_expired_positions()`** — ✅ CONFIRMED  
   ```python
   # NO side: entry_price is the correct NO price (e.g. 3c for a contract
   # bought at 3c NO = 97c YES). P&L formula matches YES convention.
   ```
   Clean. No flip references.

8. **`normalize_entry_price()` in `logger.py` untouched** — ✅ CONFIRMED (by omission)  
   `logger.py` is not in the changed files list. Dev notes confirm it was intentionally left alone. No changes to verify.

### CONCERN: Stale docstring in `add_position()`

The `add_position()` docstring still references the old flip behavior:
```
size_dollars: actual dollar cost paid for this leg. If not provided,
              computed as entry_price * quantity / 100 BEFORE any NO-side
              price flip (so the value reflects true cost even when the
              flip transforms entry_price).
```
The phrase "BEFORE any NO-side price flip" is now incorrect — the flip no longer exists. This docstring should be updated to remove the flip reference. Non-blocking (cosmetic) but should be cleaned in the same commit.

---

## Summary

| Issue | Verdict | Notes |
|-------|---------|-------|
| ISSUE-076 | ✅ PASS | File lock correctly implemented; cold start handled; read path unlocked |
| ISSUE-047 | ✅ PASS | Trip log names module + threshold; per-asset CB key confirmed in ws_feed.py |
| ISSUE-044 | ✅ PASS | `_today_pdt()` added to both files; trade record dates replaced; cosmetics untouched |
| ISSUE-043 | ✅ PASS | Explicit `ImportError` on missing config key; no silent 0.70 fallback |
| ISSUE-042 | ❌ FAIL | `side` variable never defined in `check_exits()` loop — NameError crash on daily write-off path |

---

## Overall Verdict: **HOLD**

**Do not commit ISSUE-042 in its current state.**

### Required Fix Before Commit

In `position_tracker.py`, `check_exits()`, immediately after `pos = _tracked.get(key)` and the `if not pos: continue` guard, add:

```python
side = key[1]
```

Then update the Design D guard from `key[1] == 'yes'` to `side == 'yes'` for consistency:

```python
if pos.get('module', '').startswith('crypto_dir_15m_') and pos.get('added_at') and side == 'yes':
```

Also update the `add_position()` docstring to remove the stale "BEFORE any NO-side price flip" clause (non-blocking but should be in same commit).

### Commit Plan (Once Fixed)

After Dev applies the fix above and QA re-verifies:

```
fix: ISSUE-076 ISSUE-047 CB file lock + trip logging
fix: ISSUE-044 ISSUE-043 ISSUE-042 timezone PDT + EXIT_GAIN_PCT + NO-side flip removal
```

These can be two commits (batch 1 and batches 2+3) or one combined commit. Recommend two commits to keep CB lockfix isolated from the flip removal.

ISSUE-076 + ISSUE-047 are clean and can be committed immediately if Dev prefers to separate them from the ISSUE-042 hold.

---

*QA report written: 2026-04-03*

---

## Sprint 5 Re-Review — ISSUE-042 Part A Blocker Fix

**Re-check date:** 2026-04-03  
**Reviewed by:** Ruppert QA (subagent QA-Sprint5-Recheck)  
**Scope:** Blocker fix verification only — ISSUE-076/047 already committed, not re-checked.

---

### Check 1 — ISSUE-042 Part A: `check_exits()` fix in `position_tracker.py`

**Verdict: ✅ PASS**

1. **`side = key[1]` assigned after `if not pos: continue`** — ✅ CONFIRMED  
   Lines 398–402 show:
   ```python
   pos = _tracked.get(key)
   if not pos:
       continue

   side = key[1]
   ```
   Correct order. `side` is in scope for all code below in the loop body.

2. **Design D guard uses `side == 'yes'` (not `key[1] == 'yes'`)** — ✅ CONFIRMED  
   Line 432:
   ```python
   if pos.get('module', '').startswith('crypto_dir_15m_') and pos.get('added_at') and side == 'yes':
   ```
   Uses `side` variable, consistent with surrounding code.

3. **Daily stop block `_wo_key = (ticker, side, int(_mins_left))` has `side` in scope** — ✅ CONFIRMED  
   Line 552 uses `side` which is now properly defined at line 402. No NameError possible.

**The blocker is resolved.**

---

### Check 2 — Docstring cleanup: `add_position()`

**Verdict: ✅ PASS**

The `add_position()` docstring (lines 223–233) reads:
```
size_dollars: actual dollar cost paid for this leg. If not provided,
              computed as entry_price * quantity / 100.
```
The phrase "BEFORE any NO-side price flip" is gone. Docstring is clean and accurate.

---

### Check 3 — Batch 2 sanity check (ISSUE-044 + ISSUE-043)

**Verdict: ✅ PASS (not corrupted)**

- **`_today_pdt()`** — ✅ Present at line 48 in `position_tracker.py`, used in 5 trade record `date` fields as previously verified.
- **`EXIT_GAIN_PCT` ImportError** — ✅ Present at lines 43–45:
  ```python
  EXIT_GAIN_PCT = getattr(config, 'EXIT_GAIN_PCT', None)
  if EXIT_GAIN_PCT is None:
      raise ImportError('[position_tracker] EXIT_GAIN_PCT not found in config — check config.py')
  ```
  Batch 2 changes are intact and uncorrupted.

---

### Updated Summary Table

| Issue | Verdict | Notes |
|-------|---------|-------|
| ISSUE-076 | ✅ PASS | Already committed |
| ISSUE-047 | ✅ PASS | Already committed |
| ISSUE-044 | ✅ PASS | `_today_pdt()` intact — sanity confirmed |
| ISSUE-043 | ✅ PASS | `ImportError` guard intact — sanity confirmed |
| ISSUE-042 Part A | ✅ PASS | Blocker resolved: `side = key[1]` in scope, guard uses `side`, `_wo_key` safe |

---

## Overall Verdict: **APPROVED TO COMMIT**

All checks pass. Batch 2 and Batch 3 are clear for commit.

### Commit Messages

**Batch 2 (ISSUE-044 + ISSUE-043):**
```
fix: ISSUE-044 ISSUE-043 timezone PDT date fix and EXIT_GAIN_PCT hard guard
```

**Batch 3 (ISSUE-042 Part A):**
```
fix: ISSUE-042 NO-side flip removal and check_exits side variable fix
```

---

*Re-check written: 2026-04-03*
