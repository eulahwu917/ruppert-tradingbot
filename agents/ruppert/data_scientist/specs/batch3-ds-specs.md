# Batch 3 — Data Scientist Specs
_Author: Data Scientist | Date: 2026-04-04 | Status: Revised after adversarial review_

---

## Revision Log

| Rev | Date | Author | Changes |
|-----|------|--------|---------|
| v1.0 | 2026-04-04 | Data Scientist | Initial spec |
| v1.1 | 2026-04-04 | Data Scientist | **B3-DS-3 BLOCKER** — rewrote call-site analysis: (1) corrected function name to `get_buying_power()`, (2) enumerated all direct callers of `logger.get_daily_exposure()` in trading paths, (3) specified required exception handling per caller, (4) noted that raising in `capital.py` alone is insufficient. **B3-DS-2** — changed fix from `getattr(config, 'DRY_RUN', True)` to `not _is_live_enabled()` to match `settlement_checker.py` pattern. |

---

## B3-DS-1 — `normalize_entry_price()` NO-side fallback returns YES price

### Problem

In `agents/ruppert/data_scientist/logger.py`, the `normalize_entry_price()` function (lines 468–485) has a logic gap in its fallback path. When `entry_price` is **missing** from a position record, it falls back to:

```python
entry_price = pos.get('market_prob', 0.5) * 100
```

This computes `market_prob * 100`, which is the **YES price in cents** (e.g., market_prob=0.65 → 65¢). That's correct for a YES-side position. However, for a **NO-side** position the correct entry price is `100 - (market_prob * 100)` — i.e., the cost to buy NO. The code does not apply this conversion when the fallback fires.

The existing NO-side branch only handles the case where `entry_price` is already present but formatted as a probability (0–1 range):

```python
if side == 'no':
    entry_price = entry_price if isinstance(entry_price, (int, float)) else 50
    if 0 < entry_price < 1:
        entry_price = round((1 - entry_price) * 100)
```

This `0 < x < 1` guard never triggers when the fallback produces a value like `65` (a cents value in range 1–99), so the wrong price silently passes through.

### Root Cause

The fallback `market_prob * 100` is not side-aware. It always produces the YES cents value regardless of `side`.

### Exact Fix

**File:** `agents/ruppert/data_scientist/logger.py`  
**Function:** `normalize_entry_price()`  
**Change:** Make the fallback expression side-aware.

Replace:

```python
entry_price = raw_ep if raw_ep is not None else pos.get('market_prob', 0.5) * 100
```

With:

```python
if raw_ep is not None:
    entry_price = raw_ep
else:
    market_prob = pos.get('market_prob', 0.5)
    if side == 'no':
        entry_price = (1 - market_prob) * 100
    else:
        entry_price = market_prob * 100
```

**What this does:** When `entry_price` is absent, YES-side positions use `market_prob * 100` as before; NO-side positions now correctly use `(1 - market_prob) * 100`.

The existing downstream `if 0 < entry_price < 1` normalization block remains in place to handle the separate edge case where `entry_price` is stored as a raw probability float (e.g., `0.65` instead of `65`). That block is still needed and should not be removed.

### No Other Changes Required

No other functions call `normalize_entry_price()` in a way that would be broken by this fix. The function returns a float representing cents — callers are unchanged.

### Reviewer Notes

- Confirm that `market_prob` is stored as a probability (0–1 range), not as cents. If any code path stores it as cents (0–100), this fix would double-invert and produce a wrong result. The docstring says "YES probability" — verify this matches actual logged records.
- The `side` default is `'no'` in `pos.get('side', 'no')`. Any record with a missing `side` field will be treated as NO. This seems intentional (conservative default) but the reviewer should confirm.

---

## B3-DS-2 — `post_trade_monitor.py` hardcodes `dry_run: True` in settle records

### Problem

In `agents/ruppert/trader/post_trade_monitor.py`, the `check_settlements()` function writes a settle record to the trade log. One field in that record is:

```python
"order_result": {"dry_run": True, "status": "settled"},
```

This is hardcoded `True`. In LIVE mode, real market settlements are permanently tagged as dry-run. Any downstream analytics that filter on `order_result.dry_run` (e.g., dashboards, P&L validators, audit scripts) will misclassify live settlements as simulated trades. This is silent data corruption — it doesn't crash anything, it just makes live settlements invisible to production analytics.

### How Live Mode Is Determined Elsewhere

The rest of `post_trade_monitor.py` uses one of two patterns to determine live/dry-run status:

1. **Module-level config read at call time:**  
   ```python
   _dry_run = getattr(config, 'DRY_RUN', True)
   ```
   This is the pattern used in `run_monitor()` (line 507). It reads `config.DRY_RUN` at runtime (intentionally not captured at module load — see comment at line 39).

2. **`require_live_enabled()` guard** (line 615–616):  
   ```python
   from agents.ruppert.env_config import require_live_enabled
   require_live_enabled()
   ```
   This is a hard safety check that raises if live is not enabled. It's used before executing real exits.

The settle record's `dry_run` field should match the pattern used in `settlement_checker.py`, which uses `_is_live_enabled()` from `env_config` — the canonical, centralized live-mode check.

### Exact Fix

**File:** `agents/ruppert/trader/post_trade_monitor.py`  
**Location:** `check_settlements()` function, settle record construction (line ~290)

**Current code:**
```python
"order_result": {"dry_run": True, "status": "settled"},
```

**Fix:**
```python
"order_result": {"dry_run": not _is_live_enabled(), "status": "settled"},
```

**Required import** (add near top of file, alongside `from agents.ruppert.env_config import get_paths as _get_paths`):
```python
from agents.ruppert.env_config import is_live_enabled as _is_live_enabled
```

`is_live_enabled` is defined in `agents/ruppert/env_config.py` (line 49) and is already imported in sibling files (e.g., `settlement_checker.py` uses the same pattern). Adding it to `post_trade_monitor.py`'s existing `env_config` import is a one-line change.

**Why `not _is_live_enabled()` instead of `getattr(config, 'DRY_RUN', True)`:**  
`_is_live_enabled()` is the single canonical live-mode check used across the codebase (`settlement_checker.py`, `crypto_band_daily.py`). Using `getattr(config, 'DRY_RUN', True)` would be a second divergent pattern. Consistency matters here — two different live-mode checks that can disagree is worse than one.

### Implementation Notes

- `check_settlements()` is called from within `run_monitor()`. The `_is_live_enabled()` call is cheap (reads a config attribute) and safe to call inline.
- Do not use `require_live_enabled()` here — that function raises on failure. We want to tag the record accurately, not gate it.

### Reviewer Notes

- Confirm that `is_live_enabled` is importable in `post_trade_monitor.py` — it is defined in `env_config.py` and already imported in settlement_checker.py with the same pattern.
- Verify that no other analytics consumers depend on `order_result.dry_run == True` always being set in settle records (e.g., code that uses this as a sentinel to identify settlement vs. normal exit). If so, use a dedicated `settlement_source` field instead and leave `dry_run` accurate.

---

## B3-DS-3 — `capital.get_daily_exposure()` silently returns 0.0 on error — call sites must be fixed

### Problem

In `agents/ruppert/data_scientist/capital.py`, `get_daily_exposure()` catches all exceptions and returns `0.0`:

```python
def get_daily_exposure() -> float:
    try:
        from agents.ruppert.data_scientist.logger import get_daily_exposure as _get_daily_exposure
        return _get_daily_exposure()
    except Exception as e:
        logger.warning(f"[Capital] get_daily_exposure() failed: {e}")
        return 0.0
```

`get_daily_exposure()` is used in `get_buying_power()`:

```python
def get_buying_power(deployed: float = None) -> float:
    capital = get_capital()
    if deployed is None:
        deployed = get_daily_exposure()
    return round(max(0.0, capital - deployed), 2)
```

If `get_daily_exposure()` returns `0.0` due to an error, `get_buying_power()` reports the full capital balance as available. Any module that checks buying power before placing a trade will believe no capital is deployed, and risk limits will not fire. This is a risk management bypass — a read error becomes invisible over-allocation permission.

### Critical Finding: Raising in `capital.py` Alone Is Insufficient

**The spec as originally written was dangerously incomplete.** Most trading-path code does **not** call `capital.get_daily_exposure()` at all. Instead, it imports `logger.get_daily_exposure` directly:

```python
# Example — crypto_threshold_daily.py line 36
from agents.ruppert.data_scientist.logger import get_daily_exposure
```

This means fixing `capital.get_daily_exposure()` to raise would have zero effect on the majority of call sites. Each direct caller has its own exception handling — and in the most dangerous cases, they swallow the error and set `deployed = 0.0` themselves.

**Both layers must be fixed:** `capital.get_daily_exposure()` must raise, AND every direct caller of `logger.get_daily_exposure()` in a trading path must handle the exception correctly rather than swallowing it.

---

### Fix Part 1: `capital.get_daily_exposure()` — Raise Instead of Return 0.0

**File:** `agents/ruppert/data_scientist/capital.py`  
**Function:** `get_daily_exposure()`

```python
def get_daily_exposure() -> float:
    try:
        from agents.ruppert.data_scientist.logger import get_daily_exposure as _get_daily_exposure
        return _get_daily_exposure()
    except Exception as e:
        logger.error(f"[Capital] get_daily_exposure() FAILED — cannot determine deployed capital: {e}")
        raise RuntimeError(f"get_daily_exposure() failed: {e}") from e
```

Change `logger.warning` → `logger.error` (correct severity for a risk-path failure), then raise immediately. No new imports needed.

---

### Fix Part 2: Direct Callers of `logger.get_daily_exposure()` in Trading Paths

The following files import and call `logger.get_daily_exposure()` directly. Each is analyzed below with the required fix.

#### 2a. `agents/ruppert/trader/crypto_threshold_daily.py` — **BLOCKER: two swallowed call sites**

This file imports at module level (line 36):
```python
from agents.ruppert.data_scientist.logger import get_daily_exposure
```

**Call site 1 — lines 1027–1035: per-asset cap check**
```python
try:
    asset_daily_deployed = get_daily_exposure(module=_asset_module, asset=asset)
except TypeError:
    try:
        asset_daily_deployed = get_daily_exposure(module=_asset_module)
    except Exception:
        asset_daily_deployed = 0.0   # ← SWALLOWS ERROR
except Exception:
    asset_daily_deployed = 0.0       # ← SWALLOWS ERROR
```

**Call site 2 — line 1042–1044: total daily cap check**
```python
try:
    total_1d_deployed = sum(get_daily_exposure(module=m) for m in _ALL_CRYPTO_1D_MODULES)
except Exception:
    total_1d_deployed = 0.0          # ← SWALLOWS ERROR
```

**Required fix for both call sites:** Replace `except Exception: return/set 0.0` with log + alert + skip. Both are pre-trade entry guards — if we can't read exposure, we must not enter. Example pattern:

```python
try:
    asset_daily_deployed = get_daily_exposure(module=_asset_module)
except Exception as _e:
    logger.error('[crypto_threshold_daily] get_daily_exposure() failed — skipping entry: %s', _e)
    return _skip(asset, window, 'exposure_read_error')
```

Apply the same pattern to the `total_1d_deployed` call: on exception, return `_skip(asset, window, 'exposure_read_error')` rather than setting `0.0`.

The `TypeError` inner fallback (trying module-only when module+asset raises) is acceptable — that handles an API shape mismatch, not a data integrity failure. Only the bare `except Exception: ... = 0.0` blocks must change.

---

#### 2b. `agents/ruppert/trader/crypto_band_daily.py` — **two call sites, both swallowing**

**Call site 1 — lines 135–144: pre-lock cap check (inside `_execute_capped_entries()`)**
```python
try:
    _crypto_deployed_this_cycle = sum(
        _get_daily_exp(module=m) for m in (...)
    )
except Exception:
    _crypto_deployed_this_cycle = 0.0   # ← SWALLOWS ERROR
```

**Call site 2 — lines 528–541: post-lock cap check (main entry loop)**
```python
try:
    _total_capital  = get_capital()
    _deployed_today = get_daily_exposure()
    _cap_remaining  = check_daily_cap(_total_capital, _deployed_today)
    ...
except Exception as e:
    print(f"  [CapCheck] Cap check error: {e} - proceeding with caution")
    _total_capital  = 10000.0
    _deployed_today = 0.0             # ← PROCEEDS WITH WRONG DATA
```

**Required fix — Call site 1:** On exception, log error and skip the entry batch entirely (return empty list `[]`). This is inside a locked section; it's safer to bail than proceed with `0.0`.

**Required fix — Call site 2:** On exception, log error + send Telegram alert + return `[]` (halt the cycle). "Proceed with caution" using a hardcoded fallback is not acceptable in a risk path. The message `_deployed_today = 0.0` + `_total_capital = 10000.0` could allow uncapped entries if the real capital is different.

---

#### 2c. `agents/ruppert/trader/crypto_15m.py` — **bare call, no exception handling**

Lines 1140–1141:
```python
from agents.ruppert.data_scientist.logger import get_daily_exposure as _get_exp, ...
_deployed_today = _get_exp()
```

This call is completely unguarded — no try/except anywhere in the enclosing function. If `get_daily_exposure()` raises, the exception propagates up to the caller.

**Required fix:** Wrap in try/except. On exception, log error and return early from the evaluation function (skip the entry), rather than letting the exception propagate silently to an outer handler that may swallow it:

```python
try:
    _deployed_today = _get_exp()
except Exception as _e:
    logger.error('[crypto_15m] get_daily_exposure() failed — skipping entry: %s', _e)
    return
```

---

#### 2d. `agents/ruppert/trader/crypto_long_horizon.py` — **two bare calls in entry path**

**Call site 1 — line 354: pre-scan daily cap check**
```python
existing_exposure = get_daily_exposure()
if existing_exposure >= daily_cap:
    ...
    return []
```
No exception handling. If this raises, exception propagates to the caller.

**Call site 2 — lines 389–390: per-opportunity strategy gate**
```python
_deployed_today = get_daily_exposure()
_crypto_long_deployed = get_daily_exposure('crypto_long_horizon')
```
Also unguarded.

**Required fix — Both call sites:** Wrap in try/except; on exception log error and skip (return `[]` from the scan function, or `continue` from the opportunity loop). The capital data is required for correct sizing — proceeding without it is not safe:

```python
try:
    existing_exposure = get_daily_exposure()
except Exception as _e:
    logger.error('[crypto_long_horizon] get_daily_exposure() failed — skipping scan: %s', _e)
    return []
```

---

#### 2e. `agents/ruppert/trader/position_monitor.py` — **two bare calls in entry path**

**Call site 1 — line 322: daily cap check**
```python
current_exposure = get_daily_exposure()
```
No try/except; exception propagates up.

**Call site 2 — lines 388–389: strategy gate**
```python
deployed_today = get_daily_exposure()
_module_deployed = get_daily_exposure('crypto')
```
Also unguarded.

**Required fix:** Same as `crypto_long_horizon.py` — wrap each in try/except; on exception log error and return from the function (skip entry), since these are both pre-trade guards:

```python
try:
    current_exposure = get_daily_exposure()
except Exception as _e:
    logger.error('[position_monitor] get_daily_exposure() failed — skipping entry: %s', _e)
    return
```

---

#### 2f. `agents/ruppert/trader/main.py` — **call inside try/except, but swallows to 0.0**

Lines 119–131:
```python
try:
    _capital = get_capital()
    _1d_deployed = sum(get_daily_exposure(module=m) for m in (...))
    _1d_cap = _capital * config.CRYPTO_1D_DAILY_CAP_PCT
except Exception as _ce:
    log_activity(f"[Crypto1D] Capital check error: {_ce} - using fallback")
    _capital = getattr(config, 'CAPITAL_FALLBACK', 10000.0)
    _1d_deployed = 0.0    # ← SWALLOWS ERROR
    _1d_cap = _capital * getattr(config, 'CRYPTO_1D_DAILY_CAP_PCT', 0.15)
```

**Required fix:** On exception, skip the entire cycle rather than using `_1d_deployed = 0.0`. The existing log_activity call is good — add a Telegram alert and return `[]`:

```python
except Exception as _ce:
    log_activity(f"[Crypto1D] get_daily_exposure() failed — skipping cycle: {_ce}")
    # Do not use 0.0 fallback — cap check would be invalid
    return []
```

---

#### 2g. `environments/demo/ruppert_cycle.py` — **monitoring-only, mixed patterns**

This file has several `get_daily_exposure()` call sites, but most are in monitoring/reporting functions rather than entry gates.

**Line 144 — `run_post_cycle_exposure_check()`:** Already wrapped in try/except at line 143; on error logs via `log_activity`. This is monitoring-only (no trades blocked or allowed). The existing `except` swallows silently (`log_activity` only). **Acceptable** — this function is not in the trading path; it just logs exposure warnings. Keep the existing pattern, optionally add Telegram alert for the error itself.

**Lines 303, 425, 557, 819 — status/reporting calls:** These appear in scan summary messages, reconciliation logs, and status reports — not in trade entry gates. All are wrapped in `try/except Exception: _cap_line = 'N/A'` or equivalent. **Acceptable** — degraded display is fine for reporting; these do not gate any trade decisions.

**No changes required in `ruppert_cycle.py`** beyond the existing patterns, since none of these call sites influence whether a trade is placed.

---

### Recommendation — Be Opinionated

**In LIVE mode: raise, do not swallow, in any trading path.**  
A read error in `get_daily_exposure()` during live trading is not a recoverable condition. If we can't determine how much capital is deployed, we have no business placing new trades. Returning `0.0` is categorically wrong — it makes a dangerous situation look safe.

**In DEMO mode: same behavior.**  
DEMO should mirror LIVE behavior for all risk-path code. Silently returning `0.0` in DEMO trains the system (and its operators) to expect that errors are safe to ignore. They're not.

**For monitoring/reporting paths (e.g., `ruppert_cycle.py` status messages):** Swallowing is acceptable. These do not gate trade execution. Degrade gracefully to `'N/A'` or log the error, but don't crash the reporting loop.

---

### Summary Table: Required Changes

| File | Line(s) | Current Behavior | Required Behavior |
|------|---------|-----------------|-------------------|
| `capital.py` | 125–132 | `return 0.0` | `raise RuntimeError` |
| `crypto_threshold_daily.py` | 1027–1035 | `= 0.0` (swallow) | log error + `return _skip(...)` |
| `crypto_threshold_daily.py` | 1042–1044 | `= 0.0` (swallow) | log error + `return _skip(...)` |
| `crypto_band_daily.py` | 135–144 | `= 0.0` (swallow) | log error + return `[]` |
| `crypto_band_daily.py` | 528–541 | fallback to 0.0 + proceed | log error + alert + return `[]` |
| `crypto_15m.py` | 1141 | unguarded (propagates) | wrap + log error + `return` |
| `crypto_long_horizon.py` | 354 | unguarded (propagates) | wrap + log error + `return []` |
| `crypto_long_horizon.py` | 389–390 | unguarded (propagates) | wrap + log error + `continue` |
| `position_monitor.py` | 322 | unguarded (propagates) | wrap + log error + `return` |
| `position_monitor.py` | 388–389 | unguarded (propagates) | wrap + log error + `return` |
| `main.py` (trader) | 119–131 | fallback to 0.0 + continue | log error + alert + `return []` |
| `ruppert_cycle.py` (demo) | 144, 303, 425, 557, 819 | monitoring/reporting only | **No change required** |

### Additional Note — Circuit Breaker Interaction

Per MEMORY.md (standing rule from 2026-04-02): the global circuit breaker reads trade logs live and does NOT rely on cached state for its trip decision. However, `get_daily_exposure()` feeds `get_buying_power()`, which is the pre-trade capital check — a separate guard from the circuit breaker. Both must be reliable. A failure in `get_daily_exposure()` does not trigger the CB; it bypasses the capital check entirely. This is why raising is the correct response in trading paths.

### Reviewer Notes

- Confirm that every file in the summary table has been updated before closing this spec. A fix to `capital.py` alone provides no protection — the direct `logger` importers are the dominant code path.
- `logger` (Python stdlib logging) is already in scope in all affected files. No new imports needed for error logging.
- Consider adding a Telegram alert send in `capital.py` when the error fires (matching the existing pattern in `get_capital()`), so the operator is notified in real time, not just in file logs.

---

_End of Batch 3 DS Specs_
