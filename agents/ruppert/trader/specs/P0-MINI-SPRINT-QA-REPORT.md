# P0 Mini-Sprint — QA Report
**Date:** 2026-04-03  
**QA Agent:** Trader QA  
**Sprint:** P0 Mini-Sprint (5 issues, 4 batches)  
**Status: APPROVED WITH MINOR NOTE**

---

## Summary

All 5 issues verified against spec. All core behaviors implemented correctly. One stale hardcoded string found in ISSUE-040 (cosmetic, non-blocking). Recommend fix before commit or as a follow-up note.

| Batch | Issues | Files | Result |
|---|---|---|---|
| 1 | ISSUE-034, ISSUE-117 | `position_monitor.py`, `strategy.py` | ✅ PASS |
| 2 | ISSUE-007 | `logger.py`, `capital.py` | ✅ PASS |
| 3 | ISSUE-006 | `prediction_scorer.py` | ✅ PASS |
| 4 | ISSUE-040 | `optimizer.py` | ✅ PASS (minor note) |

---

## Batch 1 — ISSUE-034 + ISSUE-117

### ISSUE-034: `position_monitor.py` — WS_ENABLED set to False

**Spec requirement:** `WS_ENABLED = False`. The WS code path cannot be reached.

**Verified:**
- Line 62: `WS_ENABLED = False  # WS mode retired 2026-03-31 — polling only` ✅
- The `if WS_ENABLED:` block in `main()` is now dead. `ws_available` stays `False`, and `run_polling_mode(client)` is guaranteed to execute. ✅
- Settlement source stamp: `"source": "ws_settlement" if WS_ENABLED else "poll_settlement"` — will always write `"poll_settlement"` now. ✅
- Comment updated to reflect retired status. ✅
- WS stub functions (`run_ws_mode`, `run_persistent_ws_mode`) still present and still raise `RuntimeError` — correct, they are unreachable dead code. ✅

**Result: PASS**

---

### ISSUE-117: `strategy.py` — vol_ratio <= 0 guard

**Spec requirement:** `vol_ratio <= 0` returns `0.0` before Kelly. Shrinkage applied unconditionally after. No full-Kelly on missing data.

**Verified (lines ~240–248 of `calculate_position_size()`):**

```python
# Vol adjustment: high vol → smaller position
# Guard: vol_ratio=0 means missing vol data — skip the trade entirely
if vol_ratio <= 0:
    return 0.0  # missing vol data — do not trade
kelly_size *= (1.0 / vol_ratio)
```

- Early return `0.0` on `vol_ratio <= 0` ✅
- Old `if vol_ratio > 0:` conditional removed ✅
- Shrinkage `kelly_size *= (1.0 / vol_ratio)` is now unconditional (after guard) — vol_ratio is guaranteed positive at this point ✅
- `vol_ratio=0` → returns `0.0` before Kelly math executes ✅
- Normal `vol_ratio=1.0` → shrinkage is `* 1.0` (no change) ✅
- `vol_ratio=2.0` → shrinkage applied, position halved ✅

**Result: PASS**

---

## Batch 2 — ISSUE-007

### `logger.py` — `compute_closed_pnl_from_logs()`

**Spec requirement:** Raises `RuntimeError` (not returns `0.0`) on failure. Cache is invalidated (`_pnl_mtime_cache['mtime'] = None`, `_pnl_mtime_cache['value'] = None`).

**Verified (lines 758–765):**

```python
except Exception as e:
    # Invalidate mtime cache so the next call retries from scratch instead of
    # short-circuiting on the stale (possibly None or wrong) cached mtime.
    _pnl_mtime_cache['mtime'] = None
    _pnl_mtime_cache['value'] = None
    raise RuntimeError(
        f'[Logger] compute_closed_pnl_from_logs() failed - cannot compute capital: {e}'
    ) from e
```

- `_pnl_mtime_cache['mtime'] = None` ✅
- `_pnl_mtime_cache['value'] = None` ✅
- `raise RuntimeError(...) from e` ✅
- No silent `return 0.0` ✅

**Result: PASS**

---

### `capital.py` — `get_capital()` and `get_pnl()`

**Spec requirement:** `get_capital()` does NOT silently swallow RuntimeError — propagates it. `get_pnl()` does NOT silently swallow RuntimeError — propagates it. `get_buying_power()` is untouched.

**Verified `get_capital()` (lines 75–84):**

```python
try:
    closed_pnl = compute_closed_pnl_from_logs()
except RuntimeError:
    raise  # do NOT swallow - capital is unknown; let callers handle it
return round(total + closed_pnl, 2)

except Exception as e:
    if isinstance(e, RuntimeError):
        raise  # from compute_closed_pnl_from_logs() - capital unknown, do not swallow
    logger.warning(...)
    ...
    return _DEFAULT_CAPITAL
```

- Inner `except RuntimeError: raise` — re-raises immediately before reaching outer handler ✅
- Outer `except Exception` has `if isinstance(e, RuntimeError): raise` as a safety net ✅
- Non-RuntimeError exceptions (deposits file, Kalshi API) still fall back to `_DEFAULT_CAPITAL` ✅
- RuntimeError from P&L compute path is NOT swallowed ✅

**Verified `get_pnl()` (lines 141–146):**

```python
try:
    result['closed'] = compute_closed_pnl_from_logs()
    result['total'] = result['closed'] + result['open']
except RuntimeError:
    logger.error('[Capital] get_pnl() - P&L compute failed, propagating')
    raise  # caller must handle - do not return zeroed dict silently
return result
```

- `except RuntimeError: raise` ✅
- No silent return of zeroed dict on failure ✅

**Verified `get_buying_power()` (lines 106–117):**

- Calls `get_capital()` with no try/except around it ✅
- No changes made to `get_buying_power()` — spec said "untouched" ✅
- After the fix, RuntimeError from `get_capital()` will propagate through `get_buying_power()` to its callers — correct per spec ✅

**Result: PASS**

---

## Batch 3 — ISSUE-006

### `prediction_scorer.py` — NO-side outcome and predicted_prob flip

**Spec requirement:** For NO-side trades: `outcome` is flipped (`1 - outcome`) AND `predicted_prob` is flipped (`1.0 - predicted_prob`). `edge` is NOT flipped. `predicted_prob=None` case handled without crashing.

**Verified (lines 158–167):**

```python
# For NO-side trades: flip outcome and predicted_prob into the bettor's frame.
# outcome=1 must mean "bettor won" regardless of side.
# predicted_prob must represent the bettor's win probability for Brier to be meaningful.
# NOTE: If predicted_prob is None, only _outcome is flipped. Brier stays None (correct).
# NOTE: edge is NOT flipped - it is already signed from the bettor's perspective.
side = rec.get('side') or buy_rec.get('side', 'yes')
if side == 'no' and _outcome is not None:
    _outcome = 1 - _outcome
    if predicted_prob is not None:
        predicted_prob = round(1.0 - float(predicted_prob), 4)
```

- `_outcome = 1 - _outcome` for NO-side ✅
- `predicted_prob = round(1.0 - float(predicted_prob), 4)` for NO-side, only when not None ✅
- `if predicted_prob is not None:` guard — None case handled, no crash ✅
- `edge` field: written as `buy_rec.get('edge', 0)` with no flip applied ✅
- Flip block is BEFORE Brier calculation ✅
- YES-side trades: guard `if side == 'no'` means no changes applied ✅

**Spec verification table check:**

| Scenario | Expected after fix | Code produces |
|---|---|---|
| NO buyer wins (settled NO), prob=0.03 | outcome=1, prob=0.97, brier=0.0009 | ✅ `_outcome = 1-0 = 1`, `prob = 1.0-0.03 = 0.97`, brier=`(1-0.97)²=0.0009` |
| NO buyer loses (settled YES), prob=0.03 | outcome=0, prob=0.97, brier=0.9409 | ✅ `_outcome = 1-1 = 0`, `prob = 0.97`, brier=`(0-0.97)²=0.9409` |
| NO buyer wins, prob=None | outcome=1, prob=None, brier=None | ✅ `_outcome` flipped, prob skip (None guard), brier=None |
| YES buyer wins (settled YES), prob=0.70 | outcome=1, prob=0.70, brier=0.09 | ✅ No change — side != 'no' |

**Result: PASS**

---

## Batch 4 — ISSUE-040

### `optimizer.py` — DOMAIN_THRESHOLD, `get_domain_trade_counts()`, `enrich_trades()`

**Spec requirement:** `DOMAIN_THRESHOLD` lowered to 10. `get_domain_trade_counts()` reads `domain` field first, falls back to `detect_module`. `enrich_trades()` uses `classify_module()` not `detect_module()`.

**Verified `DOMAIN_THRESHOLD` (line 43):**

```python
DOMAIN_THRESHOLD           = 10  # Fine-grained domains (e.g. crypto_dir_15m_btc) - lowered from 30
```
- Set to `10` ✅
- Comment explains rationale ✅
- Console output label updated: `f"threshold={DOMAIN_THRESHOLD}"` (line 615) ✅
- `get_eligible_domains()` and `get_eligible_domains()` calls also use the constant, not hardcoded 30 ✅

**Verified `get_domain_trade_counts()` (lines 141–148):**

```python
domain = rec.get("domain") or detect_module(ticker)
if domain:
    counts[domain] += 1
```
- Reads `domain` field first ✅
- Falls back to `detect_module(ticker)` for legacy records ✅

**Verified `enrich_trades()` (lines 173–180):**

```python
from agents.ruppert.data_scientist.logger import classify_module as _classify_module
...
if "module" not in rec or not rec["module"]:
    rec["module"] = _classify_module(rec.get("source", ""), rec.get("ticker", ""))
```
- Uses `classify_module()` (imported from logger.py) not `detect_module()` ✅
- Only applied when `module` field is absent or empty ✅

---

### ⚠️ Minor Issue Found — Stale Hardcoded String (Non-Blocking)

**Location:** `optimizer.py`, line 725:

```python
print("No domains eligible for experiments yet (need 30 scored trades each).")
```

**Issue:** `DOMAIN_THRESHOLD` was lowered to `10`, but this print statement still says `"need 30 scored trades each"`. This string is stale and will print incorrect information when `run_domain_experiments()` receives an empty eligible list.

**Severity:** Cosmetic / misleading output. Non-blocking — does not affect any behavior or data. Trading is unaffected (optimizer is analysis-only).

**Fix (trivial one-liner):**
```python
print(f"No domains eligible for experiments yet (need {DOMAIN_THRESHOLD} scored trades each).")
```

**Recommendation:** Fix before commit. The change is a one-liner and makes the output accurate.

**Result: PASS (with minor note)**

---

## Overall Assessment

**APPROVED.** All 5 issues implemented correctly per spec. The stale hardcoded string on optimizer.py line 725 should be fixed before committing Batch 4 — it is a trivial one-liner that takes 30 seconds to correct and avoids confusing David when he runs the optimizer.

---

## Commit Messages (If Approved)

### Batch 1: ISSUE-034 + ISSUE-117

```
fix: disable WS mode in position_monitor.py; add vol_ratio guard to strategy.py

ISSUE-034: Set WS_ENABLED=False — WS mode was retired 2026-03-31 but the flag
was still True, causing run_ws_mode() to raise RuntimeError and crash the
monitor before run_polling_mode() could execute. Flip the constant; polling
is now guaranteed.

ISSUE-117: Add explicit vol_ratio<=0 guard in calculate_position_size() — when
vol_ratio=0 (missing vol data upstream), the old if vol_ratio>0 conditional
silently skipped shrinkage and returned full-Kelly. Now returns 0.0 cleanly,
blocking the trade via the kelly_size_zero path in should_enter().
```

### Batch 2: ISSUE-007

```
fix: compute_closed_pnl_from_logs() raises RuntimeError on failure; capital.py propagates it

ISSUE-007: Replace silent return 0.0 in compute_closed_pnl_from_logs() with
RuntimeError raise + mtime cache invalidation. Prevents stale-cache short-
circuit on repeated failures. Fix get_capital() and get_pnl() in capital.py
to re-raise RuntimeError instead of swallowing it — the logger.py fix was
otherwise neutralized by callers. get_buying_power() untouched (RuntimeError
now propagates through it to its callers, which is correct behavior).
```

### Batch 3: ISSUE-006

```
fix: flip outcome and predicted_prob for NO-side trades in prediction_scorer.py

ISSUE-006: outcome must represent "bettor won" (1=win, 0=loss), not "market
settled YES". For NO-side trades, these are inverted. Flip _outcome and
predicted_prob into the bettor's frame before Brier calculation. predicted_prob
flip is skipped if None (win-rate fix still applies). edge is not flipped —
it is already signed correctly. Delete scored_predictions.jsonl and re-score
cleanly after deploying.
```

### Batch 4: ISSUE-040

```
fix: optimizer reads fine-grained domain field; enrich_trades uses classify_module; DOMAIN_THRESHOLD=10

ISSUE-040: get_domain_trade_counts() now reads the stored domain field
(fine-grained classify_module name) with detect_module fallback for legacy
records. enrich_trades() uses classify_module() instead of detect_module() so
analyze_win_rate_by_module() buckets by fine-grained names (crypto_dir_15m_btc,
not crypto). DOMAIN_THRESHOLD lowered 30→10 for fine-grained regime — most
active subcategories will hit 10 within 5-10 days at current trading rate.
Console label updated to use DOMAIN_THRESHOLD constant. Hard prerequisite:
ISSUE-006 deployed and scored_predictions.jsonl deleted first.
```

---

_QA sign-off: all core behaviors verified against spec. Approved pending the trivial stale-string fix on optimizer.py line 725._
