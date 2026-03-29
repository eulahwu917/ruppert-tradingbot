# QA REPORT — Capital Fix (2026-03-12)
_SA-4 QA | Reviewed: 2026-03-12_

**Status: PASS WITH WARNINGS**
**Verdict: Safe to commit — warnings are non-critical for current demo setup**

---

## ✅ Checks Passed

1. **`get_computed_capital()` logic is correct**
   - Correctly sums `amount` field from all lines in `logs/demo_deposits.jsonl`
   - Correctly sums `realized_pnl` from all `action == "exit"` records across all `logs/trades_*.jsonl` files
   - Returns `round(total_deposits + total_realized_pnl, 2)` — correct precision handling

2. **All file opens use `encoding='utf-8'`**
   - `open(deposits_path, 'r', encoding='utf-8')` ✅
   - `open(log_path, 'r', encoding='utf-8')` ✅ (trade logs loop)

3. **No circular imports**
   - `logger.py` imports only: `json`, `os`, `datetime`, `date`, and `glob` (deferred import inside function)
   - No imports from `main.py` or `ruppert_cycle.py` ✅

4. **Call sites are correct**
   - `main.py` line 251: `total_capital = get_computed_capital()` — called with no args, result used correctly ✅
   - `ruppert_cycle.py` line 412: `_total_capital = get_computed_capital()` — called with no args, result used correctly ✅
   - Import lines updated in both files ✅

5. **No trading thresholds changed**
   - `MIN_EDGE_THRESHOLD`, `MIN_CONFIDENCE`, `check_daily_cap`, `should_enter`, entry sizing — all unchanged ✅
   - Developer summary confirmed; code review confirms no threshold parameters were touched

6. **`client.get_balance()` at main.py line 229 is in `test_connection()` only**
   - Not a capital sizing call — used for diagnostic output in test mode only ✅

7. **Known acceptable gap acknowledged**
   - Capital reads ~$510 vs ~$480 due to unsubtracted naturally-settled losses (no exit record)
   - Accepted limitation per QA brief — not flagged ✅

---

## ⚠️ Warnings (Discretionary — Safe to Commit)

### W1 — `logger.py`: Missing deposits file returns `0.0`, not a safe non-zero fallback
- If `logs/demo_deposits.jsonl` is missing, `total_deposits` stays at `0.0`
- If no trade logs exist either, `get_computed_capital()` returns `0.0`
- A capital of `$0.00` causes `check_daily_cap` to compute `max = $0.00`, blocking all trades
- This is functionally *safe* (conservative: no trades without capital) but not the intent
- **Recommendation**: Add a hardcoded floor or log a warning if deposits file is missing
- **Risk for current demo**: LOW — `demo_deposits.jsonl` is known to exist with $400 in two records

### W2 — `logger.py`: Trade log `open()` is not wrapped in try/except
- The deposits file open has a `os.path.exists()` guard but no exception handling
- The trade log file opens inside `for log_path in sorted(glob.glob(...)):` have no per-file try/except
- Individual line parsing is protected (`except Exception: pass`), but file-open errors are not
- A permissions error or locked file would propagate as an unhandled exception
- **Risk**: If `get_computed_capital()` throws, ruppert_cycle.py handles it gracefully (has try/except at line ~408); **main.py does NOT** — a crash in `get_computed_capital()` would abort `run_weather_scan()` entirely
- **Risk for current demo**: LOW — files are written by the bot and should be readable

### W3 — `main.py`: No try/except around `get_computed_capital()` call
- `ruppert_cycle.py` wraps the capital check block in try/except with fallback (`proceeding with caution`)
- `main.py` does NOT — an exception in `get_computed_capital()` would unwind `run_weather_scan()`
- The two call sites have inconsistent error handling patterns
- **Recommendation**: Wrap main.py's capital block in try/except for consistency
- **Risk for current demo**: LOW given W2 is low risk

### W4 — `dashboard/api.py` still shows stale `get_balance()` (Developer-flagged follow-up)
- Dashboard balance display does not reflect computed capital
- Out of scope for this fix, but creates a confusing discrepancy ($172 shown vs $510 actual)
- Developer already flagged this — noting for CEO to prioritize as a follow-up ticket

---

## Summary

The core fix is correct and well-implemented. The logic, imports, encoding, and call sites all pass. The three warnings (W1–W3) are edge-case failure modes that pose low risk in the current demo environment where deposits files always exist and file permissions are not an issue. W4 is a pre-existing known gap flagged by Developer.

**Recommendation**: Commit as-is. Address W1–W3 in a follow-up hardening pass (can be batched with the dashboard fix in W4).
