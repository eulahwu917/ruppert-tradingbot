# Developer Summary — Capital Warning Fixes (2026-03-12)
_SA-3 Developer | Completed: 2026-03-12_

**Task**: Fix 4 QA warnings from the capital fix review (qa_capital_fix_2026-03-12.md)
**Status**: ✅ All 4 fixes implemented, syntax-validated, staged, and committed.
**Commit**: `50d32e4` — `fix(capital): harden get_computed_capital + dashboard balance (W1-W4)`

---

## Fixes Applied

### W1 — logger.py: `get_computed_capital()` zero-capital floor ✅
**File**: `logger.py`
**Change**: After summing deposits, if `total_deposits == 0.0` (file missing, empty, or unreadable),
print a warning to stderr and set `total_deposits = 400.0`.
This prevents `check_daily_cap()` from computing a `$0.00` max and blocking all trades.

### W2 — logger.py: file opens wrapped in try/except ✅
**File**: `logger.py`
**Change**: Wrapped the deposits file `open()` and each trade log `open()` in individual
`try/except Exception` blocks. On error, logs a warning to stderr and continues. Per-line
`json.loads` exceptions were already protected; now file-open errors are too.

### W3 — main.py: try/except around `get_computed_capital()` call ✅
**File**: `main.py` — `run_weather_scan()`
**Change**: Wrapped `total_capital = get_computed_capital()` in a try/except.
On exception, logs warning to stderr and falls back to `total_capital = 400.0`.
Now consistent with the same pattern in `ruppert_cycle.py`.

### W4 — dashboard/api.py: balance display now uses computed capital ✅
**File**: `dashboard/api.py` — `get_account()` demo branch
**Change**: The demo-mode `STARTING_CAPITAL` calculation previously only summed
`demo_deposits.jsonl` (~$400). Replaced with inline computed capital logic:
  1. Sum all `demo_deposits.jsonl` records → base deposits
  2. Fallback to $400 if file missing/empty
  3. Iterate all `logs/trades_*.jsonl` files; add `realized_pnl` from `action == "exit"` records
  4. `round()` the result

This matches `get_computed_capital()` in logger.py but is inlined to avoid circular imports.
Dashboard will now display the true capital (~$510) instead of the stale Kalshi API balance (~$172).

---

## Files Modified

| File | Lines changed |
|------|--------------|
| `logger.py` | +34 / -13 (W1 + W2) |
| `main.py` | +10 / -1 (W3) |
| `dashboard/api.py` | +28 / -7 (W4) |

---

## Validation

- All 3 files pass `ast.parse()` syntax check ✅
- `git add logger.py main.py dashboard/api.py` — staged ✅
- Committed as `50d32e4` ✅
- No `git push` (per rules) ✅
- No trading thresholds modified ✅
- No secrets/ files touched ✅
- All file opens use `encoding='utf-8'` ✅

---

## Notes / TODOs

- None outstanding from this task.
- `ruppert_cycle.py` already had W3-equivalent protection — no change needed there.
- W4 comment in `get_account()` updated to explain the inline approach and reference the old `get_balance()` issue.
