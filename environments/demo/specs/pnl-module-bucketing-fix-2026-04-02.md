# Spec: Fix Per-Module P&L Bucketing in dashboard/api.py

**Date:** 2026-04-02
**Author:** DS (Ruppert)
**Priority:** P1
**File:** `environments/demo/dashboard/api.py`

---

## Problem

Both `/api/pnl` (`get_pnl_history()`) and `/api/state` (`_build_state()`) have `module_stats` / `module_closed` / `module_open` dicts with keys:
```
['crypto', 'crypto_dir_15m', 'crypto_threshold_daily', 'crypto_band_daily', 'other']
```

The aggregation code uses `get_parent_module()` to map classify_module output (e.g. `crypto_dir_15m_btc`) to a bucket key. But `get_parent_module()` maps ALL crypto sub-modules to `'crypto'`. Result: all P&L lands in the `'crypto'` bucket; `crypto_dir_15m`, `crypto_threshold_daily`, `crypto_band_daily` show zero.

**Total P&L is correct. Only the per-module card breakdown is wrong.**

---

## Current State of Working Tree

Someone already partially applied a fix: replaced `get_parent_module()` calls with `_stat_bucket()` in both `get_pnl_history()` and `_build_state()`. **But the fix has two bugs that must be corrected:**

### Bug 1: `_stat_bucket()` scoping — will crash `_build_state()`

`_stat_bucket()` is defined as a **nested function inside `get_pnl_history()`** (line ~958). `_build_state()` is a **separate top-level function** (line ~1277) that also calls `_stat_bucket()`. This will raise `NameError: name '_stat_bucket' is not defined` at runtime when `/api/state` is called.

**Fix:** Move `_stat_bucket()` to **module level** (e.g. after the `_parse_crypto_band_title` function, before the route handlers). Remove the nested definition from inside `get_pnl_history()`.

### Bug 2: Win-rate rollup in `_build_state()` only counts parent modules

Lines ~1628-1631:
```python
_parent_mods = ['crypto', 'other']
total_bot_trades = sum(module_closed[m]['trade_count'] for m in _parent_mods if m in module_closed)
total_bot_wins   = sum(module_closed[m]['wins'] for m in _parent_mods if m in module_closed)
```

Now that trades bucket into `crypto_dir_15m` / `crypto_threshold_daily` / `crypto_band_daily` instead of `crypto`, the rollup misses them. `total_bot_trades` will be near zero and win_rate will be `None`.

**Fix:** Change `_parent_mods` to include all module keys:
```python
_all_mods = ['crypto', 'crypto_dir_15m', 'crypto_threshold_daily', 'crypto_band_daily', 'other']
total_bot_trades = sum(module_closed[m]['trade_count'] for m in _all_mods if m in module_closed)
total_bot_wins   = sum(module_closed[m]['wins'] for m in _all_mods if m in module_closed)
```

---

## Implementation Steps

1. **Move `_stat_bucket()` to module level** — cut lines ~958-968 from inside `get_pnl_history()`, paste at module level (after `_parse_crypto_band_title` around line ~297). No signature change needed.

2. **Fix win-rate rollup** — in `_build_state()`, change the `_parent_mods` list at line ~1628 to include all 5 module keys (see above).

3. **Verify no other `get_parent_module()` calls remain in module_stats/module_closed/module_open aggregation** — the working tree diff already replaced them all. Confirm with: `grep -n 'get_parent_module' dashboard/api.py` (should only appear on the import line and in per-trade `parent_module` field assignment, NOT in any `module_stats`/`module_closed`/`module_open` accumulation).

---

## Do NOT Change

- `get_parent_module()` itself in `logger.py` — used correctly for trade display `parent_module` field
- The `module_stats` / `module_closed` / `module_open` key lists — already correct
- `classify_module()` — working correctly
- The per-trade `t['parent_module'] = get_parent_module(_mod)` assignments — those are display fields, not aggregation buckets

---

## Verification

After fix, restart the dashboard and confirm:

1. `/api/state` does not crash (scoping fix)
2. `/api/state` → `modules.crypto_dir_15m.closed_pnl` is non-zero
3. `/api/state` → `account.win_rate` is non-null (rollup fix)
4. `/api/pnl` → `modules.crypto_dir_15m.closed_pnl` is non-zero
5. `/api/pnl` → `modules.crypto.closed_pnl` should be near zero (no generic crypto trades)
6. Total `closed_pnl` unchanged — only the breakdown shifts

---

## Notes

- This is purely a display aggregation bug — no trade logic, no data, no risk affected
- The working tree already has the `get_parent_module` → `_stat_bucket` replacement done; Dev only needs to fix the two bugs above (scoping + rollup)
