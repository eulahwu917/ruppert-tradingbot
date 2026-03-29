# Opus Codebase Review — 2026-03-26

## Executive Summary

**Overall Assessment: ⚠️ NEEDS WORK — Do not go LIVE until P0 issues fixed**

### Top 3 Most Important Findings

1. **P0 CRITICAL: `ruppert_cycle.py` crypto sizing completely bypasses `strategy.py`** — Uses hardcoded `min(config.CRYPTO_MAX_POSITION_SIZE, 25)` (line 420) instead of calling `should_enter()` with Kelly-based sizing. The new capital-scaled caps (`MAX_POSITION_PCT * capital`) are NOT enforced for crypto trades. This means crypto trades will ALWAYS be $25 regardless of capital level.

2. **P0 CRITICAL: `risk.py` references legacy fixed-dollar constants that NO LONGER EXIST** — `risk.py` lines 42, 46, 49 reference `config.MAX_POSITION_SIZE` and `config.MAX_DAILY_EXPOSURE` which are **commented out** in `config.py` (lines 48-55). This will cause `AttributeError` if `risk.py` is ever called without `strategy_size` fallback.

3. **P1 HIGH: Fed trading also bypasses `strategy.py`** — `ruppert_cycle.py` lines 508-511 use `size = min(25.0, _fed_cap_ok)` instead of calling `should_enter()`. The 70% global exposure check and Kelly sizing are NOT enforced for Fed trades.

---

## Section 1: Strategy Bypass (ruppert_cycle.py)

### Finding: ❌ FAIL

**Weather Module:** ✅ PASS — Correctly routes through `main.py → run_weather_scan()` which calls `should_enter()` from `bot/strategy.py` (lines 304-320 of `main.py`). Capital-scaled sizing is enforced.

**Crypto Module:** ❌ FAIL — Completely bypasses `strategy.py`. 

Evidence from `ruppert_cycle.py` line 420:
```python
size = min(config.CRYPTO_MAX_POSITION_SIZE, 25)
contracts = max(1, int(size / best_price * 100))
actual_cost = round(contracts * best_price / 100, 2)
```

This hardcodes $25 max regardless of capital. It does NOT:
- Call `should_enter()` 
- Use `calculate_position_size()` with Kelly formula
- Apply confidence-tiered Kelly fraction
- Apply market impact ceiling
- Check 70% global open exposure cap via `check_open_exposure()`
- Use `MAX_POSITION_PCT * capital` formula

The only concession is the daily cap check (lines 436-445), but even that uses `check_daily_cap()` incorrectly — it checks aggregate daily cap, not module-specific `CRYPTO_DAILY_CAP_PCT`.

**Fed Module:** ❌ FAIL — Also bypasses `strategy.py`.

Evidence from `ruppert_cycle.py` lines 508-511:
```python
size = min(25.0, _fed_cap_ok)
contracts = max(1, int(size / bet_price * 100))
actual_cost = round(contracts * bet_price / 100, 2)
```

Same problem: hardcoded $25 max, no Kelly sizing, no `should_enter()` call.

**Geo Module:** Not found in `ruppert_cycle.py` — appears to be handled separately, which is correct per config (`GEO_AUTO_TRADE = True` for demo data accumulation).

**Econ Module:** Not found in `ruppert_cycle.py` — appears to only run via `main.py --econ`.

### Is `check_open_exposure()` called before trades?

- **Weather:** ✅ YES — Called in `main.py` line 303 via signal dict `signal['open_position_value'] = _open_exposure`
- **Crypto:** ❌ NO — Never called in `ruppert_cycle.py` crypto section
- **Fed:** ❌ NO — Never called in `ruppert_cycle.py` fed section

---

## Section 2: Config Consistency

### Finding: ⚠️ WARNING

**Legacy constants still present (but correctly commented out):**

`config.py` lines 48-55:
```python
# Legacy fixed-dollar caps (kept for reference — replaced by pct-based above)
# MAX_POSITION_SIZE = 25.00
# MAX_DAILY_EXPOSURE = 200.00
# CRYPTO_MAX_POSITION_SIZE = 25.00
# CRYPTO_MAX_DAILY_EXPOSURE = 200.00
...
```

However, **SOME legacy constants are still ACTIVE**:

`config.py` lines 74-79:
```python
ECON_MAX_POSITION     = 25.00  # Max $ per single econ trade (legacy...)
ECON_MAX_DAILY_EXPOSURE = 100.00  # Legacy fixed cap...
GEO_MAX_POSITION_SIZE    = 25.00   # Legacy fixed cap...
GEO_MAX_DAILY_EXPOSURE   = 100.00  # Legacy fixed cap...
```

And critically, `CRYPTO_MAX_POSITION_SIZE` is still referenced as an ACTIVE constant in `ruppert_cycle.py`:
- Line 420: `size = min(config.CRYPTO_MAX_POSITION_SIZE, 25)`

But `CRYPTO_MAX_POSITION_SIZE` is **commented out** in `config.py`! This will fail with `AttributeError`.

Wait — let me re-check. Looking at `config.py` more carefully:
- Lines 48-55: Commented out (correct)
- Lines 74-79: Active but with "legacy" comments

Actually, the search shows `CRYPTO_MAX_POSITION_SIZE` IS commented out (line 50), but `ruppert_cycle.py` references it. This is a **latent bug** that will crash if executed.

**Actually wait** — Looking at the grep results again:
```
ruppert-tradingbot-demo\config.py:50:# CRYPTO_MAX_POSITION_SIZE = 25.00
ruppert-tradingbot-demo\ruppert_cycle.py:420:            size = min(config.CRYPTO_MAX_POSITION_SIZE, 25)
```

This IS a bug. `config.CRYPTO_MAX_POSITION_SIZE` is commented out but `ruppert_cycle.py` uses it.

Let me double-check the actual config.py I read... Looking at lines 50 and 78:
- Line 50: `# CRYPTO_MAX_POSITION_SIZE = 25.00` — commented
- Line 78: `GEO_MAX_POSITION_SIZE = 25.00` — active

I don't see `CRYPTO_MAX_POSITION_SIZE` as an active constant. This is a runtime crash waiting to happen.

**CONFIRMED**: `config.py` line 50 shows `# CRYPTO_MAX_POSITION_SIZE = 25.00` (commented out). `ruppert_cycle.py` line 420 references `config.CRYPTO_MAX_POSITION_SIZE`. This WILL cause `AttributeError: module 'config' has no attribute 'CRYPTO_MAX_POSITION_SIZE'` when crypto scan runs.

### `risk.py` references deleted constants

`risk.py` lines 42, 46, 49:
```python
size = min(ideal_size, config.MAX_POSITION_SIZE)
...
remaining_daily = config.MAX_DAILY_EXPOSURE - daily_used
...
print(f"[Risk] Daily exposure limit reached (${config.MAX_DAILY_EXPOSURE})...")
```

These constants (`MAX_POSITION_SIZE`, `MAX_DAILY_EXPOSURE`) are **commented out** in `config.py`. If `trader.py` ever falls back to `risk.py` (when `strategy_size` is not set), this will crash.

---

## Section 3: Trade Log Schema

### Finding: ✅ PASS (with notes)

`logger.py` `build_trade_entry()` (lines 34-64) includes all required fields:
- ✅ `trade_id` — UUID generated
- ✅ `timestamp` — from opportunity or `datetime.now()`
- ✅ `date` — from opportunity or `date.today()`
- ✅ `ticker` — from opportunity
- ✅ `side` — from opportunity
- ✅ `edge` — from opportunity
- ✅ `confidence` — **FIXED**: line 57 handles None fallback: `opportunity.get('confidence') if opportunity.get('confidence') is not None else abs(opportunity.get('edge') or 0)`
- ✅ `size_dollars` — passed as parameter
- ✅ `contracts` — passed as parameter
- ✅ `module` — inferred from source/ticker
- ✅ `source` — from opportunity

### Are modules passing `confidence`?

- **Weather (main.py):** ✅ YES — `edge_detector.find_opportunities()` returns `confidence` field
- **Crypto (ruppert_cycle.py):** ❌ NO — The `opp` dict (lines 446-457) does NOT include `confidence` key. Falls back to `abs(edge)` in `build_trade_entry()`.
- **Fed (ruppert_cycle.py):** ✅ YES — Line 523: `"confidence": fed_signal.get("confidence")`
- **Geo:** Not in ruppert_cycle.py
- **Econ:** Not in ruppert_cycle.py

---

## Section 4: DRY_RUN Consistency

### Finding: ✅ PASS

**All files correctly source DRY_RUN from `config.DRY_RUN`:**

- `config.py` lines 12-18: Correctly reads from `mode.json`
- `ruppert_cycle.py` line 21: `DRY_RUN = config.DRY_RUN`
- `post_trade_monitor.py` line 17: `DRY_RUN = getattr(config, 'DRY_RUN', True)`
- `main.py`: Uses `dry_run` parameter passed from command line, with `--live` flag
- `trader.py`: Uses `dry_run` parameter from constructor

**Files in `trash/` still have hardcoded `DRY_RUN = True`:**
- `trash/execute_cpi.py` line 15
- `trash/execute_trades.py` line 15
- `trash/ruppert_cycle_backup.py` line 26

These are in `trash/` so acceptable, but should be deleted eventually.

---

## Section 5: Dead Code / Stale References

### Finding: ⚠️ WARNING

**Active files referencing commented-out config constants:**

1. **`risk.py`** — References `config.MAX_POSITION_SIZE` and `config.MAX_DAILY_EXPOSURE` (both commented out). Latent crash.

2. **`ruppert_cycle.py` line 420** — References `config.CRYPTO_MAX_POSITION_SIZE` (commented out). **RUNTIME CRASH**.

**Trash files with stale code:**
- `trash/execute_cpi.py` — Hardcoded DRY_RUN, fixed $25 sizes
- `trash/execute_trades.py` — Hardcoded DRY_RUN, fixed $25 sizes
- `trash/debug_crash.py` — References `run_weather_scan(dry_run=True)` directly

**Dev prompt files:**
- `dev_batch1_prompt.md`, `dev_batch1_task.md` — Searched for `--mode now` pattern, none found. ✅ PASS

**team_context.md:**
- Phase statuses are current and accurate as of 2026-03-26 ✅ PASS

---

## Section 6: Risk Logic Correctness

### Finding: ⚠️ WARNING

**`bot/strategy.py` `should_enter()` 70% global exposure check:**

Line 141-144:
```python
# --- Global open exposure cap (real-time 70% check) ---
open_position_value = signal.get('open_position_value', 0.0)
if not check_open_exposure(capital, open_position_value):
    return {'enter': False, 'size': 0.0,
            'reason': 'global_exposure_cap_reached (70% of capital)'}
```

This is correct IF `open_position_value` is passed. But:
- **Weather:** ✅ Passes it (main.py line 303)
- **Crypto:** ❌ Never calls `should_enter()`, so no check
- **Fed:** ❌ Never calls `should_enter()`, so no check

**OI cap (5% of open interest):**

`apply_market_impact_ceiling()` lines 43-65 correctly implements OI cap:
```python
# Phase 2: OI cap (when open_interest available)
if open_interest is not None and open_interest > 0:
    oi_cap = open_interest * 0.05
    if size > oi_cap:
        size = oi_cap
```

But this is only called from `should_enter()`, which crypto/fed bypass.

**Kelly formula correctness:**

`calculate_position_size()` lines 85-110:
```python
kf = kelly_fraction_for_confidence(confidence)
f = edge / (1.0 - win_prob)
kelly_size = kf * f * capital
```

Formula analysis:
- Standard Kelly is `(bp - q) / b` where b = odds, p = win prob, q = 1-p
- This implementation uses `edge / (1 - win_prob)` as the Kelly fraction
- With `edge = win_prob - implied_prob`, this is a simplified Kelly variant
- The fractional Kelly (`kf`) is applied correctly

**Verdict:** Formula is a reasonable simplified Kelly. ✅ Acceptable.

---

## Section 7: Post-Trade Monitor

### Finding: ✅ PASS

**DRY_RUN sourcing:**
Line 17: `DRY_RUN = getattr(config, 'DRY_RUN', True)` — Correct with safe default.

**95¢ / 70% gain rules:**

`check_weather_position()` lines 105-119:
```python
# 95c rule: guaranteed profit lock
if side == 'no' and no_ask >= 95:
    return 'auto_exit', f'95c rule: no_ask={no_ask}c P&L=${pnl:+.2f}', ...

# 70% gain rule
if entry_price and entry_price < 100:
    gain_pct = (cur_price - entry_price) / (100 - entry_price) ...
    if gain_pct >= 0.70:
        return 'auto_exit', f'70% gain: {gain_pct:.0%} gain P&L=${pnl:+.2f}', ...
```

`check_crypto_position()` lines 140-162: Same logic. ✅ Correct.

**Hardcoded values:** None found in exit logic — thresholds (95, 0.70) are inline but consistent with strategy.py.

---

## Section 8: Optimizer

### Finding: ✅ PASS

**DAILY_CAP computation from PCT constants:**

Lines 21-27:
```python
_capital = _get_capital()
DAILY_CAP = _capital * (
    getattr(_config, 'WEATHER_DAILY_CAP_PCT', 0.07) +
    getattr(_config, 'CRYPTO_DAILY_CAP_PCT', 0.07) +
    getattr(_config, 'GEO_DAILY_CAP_PCT', 0.04) +
    getattr(_config, 'ECON_DAILY_CAP_PCT', 0.04)
)
```

✅ Correctly computes daily cap from PCT constants times capital.

**Win-rate proposals when no outcome data:**

Lines 193-195, 208-209, 346-347:
```python
if not has_outcome_data:
    lines.append("_Skipped: no outcome data available yet._")
```

✅ Correctly skips win-rate analysis when no scored outcomes exist.

**Hardcoded thresholds:**
- `MIN_TRADES = 30` — reasonable
- `LOW_WIN_RATE_THRESHOLD = 0.60` — should ideally be in config, but acceptable
- `BRIER_FLAG_THRESHOLD = 0.25` — should ideally be in config
- `MAX_MODULE_AVG_SIZE = 40.0` — should ideally be in config

⚠️ Minor: These could be config-driven for easier tuning, but not critical.

---

## Section 9: Dashboard

### Finding: ✅ PASS

**Account value and buying power computation:**

`dashboard/api.py` `get_account()` lines 150-185:
```python
try:
    STARTING_CAPITAL = get_capital()  # from capital.py
except Exception:
    STARTING_CAPITAL = 10000.0  # Fresh start 2026-03-26

buying_power = max(STARTING_CAPITAL - total_deployed, 0)
```

✅ Uses `capital.py` as single source of truth, with $10,000 fallback (correct for 2026-03-26 reset).

**No hardcoded $400 references found.** The old $400 fallback was replaced with $10,000.

**Potential issue:** `get_pnl_history()` is 400+ lines of complex P&L calculation. Given the complexity, there may be edge cases, but the structure appears sound.

---

## Priority Fix List

### P0 — Critical (fix before any live trading)

1. **`ruppert_cycle.py` line 420: `config.CRYPTO_MAX_POSITION_SIZE` references commented-out constant**
   - File: `ruppert_cycle.py:420`
   - Issue: `config.CRYPTO_MAX_POSITION_SIZE` is commented out in `config.py`, will crash at runtime
   - Fix: Either (a) uncomment `CRYPTO_MAX_POSITION_SIZE = 25.00` in config.py, OR (b) rewrite crypto sizing to use `should_enter()` from `bot/strategy.py`
   - **Recommended:** Option (b) — route crypto through strategy.py for consistent risk management

2. **`ruppert_cycle.py` crypto section bypasses `strategy.py` entirely**
   - File: `ruppert_cycle.py:350-475`
   - Issue: No Kelly sizing, no `check_open_exposure()`, no market impact ceiling, hardcoded $25 cap
   - Fix: Refactor to build signal dict and call `should_enter()` like weather does in `main.py`
   - Code pattern to follow: `main.py` lines 280-325

3. **`risk.py` references deleted config constants**
   - File: `risk.py:42, 46, 49`
   - Issue: `config.MAX_POSITION_SIZE` and `config.MAX_DAILY_EXPOSURE` are commented out
   - Fix: Either (a) delete `risk.py` entirely (redundant with `strategy.py`), OR (b) uncomment the constants in `config.py`, OR (c) update `risk.py` to use `MAX_POSITION_PCT * capital`
   - **Recommended:** Option (a) — `risk.py` is legacy; `trader.py` already prefers `strategy_size`

### P1 — High (fix this week)

4. **`ruppert_cycle.py` Fed section bypasses `strategy.py`**
   - File: `ruppert_cycle.py:508-511`
   - Issue: Hardcoded `min(25.0, _fed_cap_ok)` sizing instead of Kelly
   - Fix: Refactor to call `should_enter()` with Fed signal dict

5. **Crypto trades missing `confidence` field in opportunity dict**
   - File: `ruppert_cycle.py:446-457`
   - Issue: `opp` dict doesn't include `confidence`, falls back to `abs(edge)` in logger
   - Fix: Add `'confidence': <computed_value>` to the crypto opportunity dict

6. **No per-module daily cap enforcement for crypto/fed**
   - File: `ruppert_cycle.py`
   - Issue: Uses aggregate `check_daily_cap()` but not `CRYPTO_DAILY_CAP_PCT * capital` limit
   - Fix: Add module-specific budget tracking like `main.py` does for weather (lines 293-298)

### P2 — Medium (fix this month)

7. **Delete or archive `risk.py`**
   - File: `risk.py`
   - Issue: Redundant with `strategy.py`, references dead constants
   - Fix: Move to `trash/` or delete after ensuring no active imports

8. **Delete `trash/` folder contents**
   - Files: `trash/execute_cpi.py`, `trash/execute_trades.py`, `trash/ruppert_cycle_backup.py`, etc.
   - Issue: Dead code with hardcoded values, confusing for future maintenance
   - Fix: Delete or archive outside repo

9. **Optimizer thresholds should be config-driven**
   - File: `optimizer.py`
   - Issue: `MIN_TRADES`, `LOW_WIN_RATE_THRESHOLD`, etc. are hardcoded
   - Fix: Move to `config.py` for easier tuning

### P3 — Low / Nice to have

10. **Add `confidence` computation to crypto model**
    - File: `ruppert_cycle.py` crypto section
    - Issue: Crypto has no true confidence score, uses edge as proxy
    - Fix: Implement a confidence metric (e.g., based on spread width, volume, time to expiry)

11. **Unify all trading through `main.py` entry points**
    - Files: `main.py`, `ruppert_cycle.py`
    - Issue: Weather goes through `main.py`, crypto/fed go through `ruppert_cycle.py` directly
    - Fix: Create `run_crypto_scan()` and `run_fed_scan()` in `main.py` that route through strategy.py

---

## Verdict

**The codebase is NOT ready for live trading.** The critical issue is that `ruppert_cycle.py`'s crypto trading section will crash due to referencing a commented-out config constant (`CRYPTO_MAX_POSITION_SIZE`). Even if this is fixed with a quick uncomment, the deeper architectural problem remains: crypto and Fed trades bypass the entire `strategy.py` risk management layer, meaning:

- No Kelly-based position sizing
- No confidence-tiered fractions
- No 70% global exposure check
- No market impact ceiling
- Hardcoded $25 positions regardless of capital growth

Weather trading through `main.py` is properly architected and enforces all the new capital-scaled rules. The same pattern should be applied to crypto and Fed before going live.

**Estimated effort to fix P0 issues:** 2-4 hours of focused dev work, plus QA verification.

**Recommendation:** Hold all live trading discussions until P0 and P1 issues are resolved and verified by QA.
