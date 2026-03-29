# QA REPORT — Kelly Tier + NWS Penalty (2026-03-12)
_Reviewer: SA-4 QA_
_Date: 2026-03-12_
_Commit reviewed: b970ea9_
_Files reviewed: `bot/strategy.py`, `edge_detector.py`_

---

## Status: FAIL

**Verdict: Needs rework before commit.**
One real bug found (NWS falsy check). Two warnings for dashboard reliability.
Fix is a one-liner — small rework, not a full rewrite.

---

## ✅ Checks Passed

### 1. kelly_fraction_for_confidence() — Tier Logic
All four tiers verified correct against spec:

| Confidence | Expected | Code returns | Status |
|------------|----------|--------------|--------|
| 80%+ | 0.25 | 0.25 (`if confidence >= 0.80`) | ✅ |
| 70–80% | 0.20 | 0.20 (`elif confidence >= 0.70`) | ✅ |
| 60–70% | 0.15 | 0.15 (`elif confidence >= 0.60`) | ✅ |
| 50–60% | 0.10 | 0.10 (fall-through) | ✅ |

**Edge cases verified (manual trace):**
- `confidence=0.60` → `>= 0.80`? No. `>= 0.70`? No. `>= 0.60`? **Yes → 0.15** ✅ (correctly in 60–70% tier)
- `confidence=0.80` → `>= 0.80`? **Yes → 0.25** ✅ (correctly in 80%+ tier)
- `confidence=1.0`  → `>= 0.80`? **Yes → 0.25** ✅
- `confidence=0.50` → falls through all three conditions → **0.10** ✅

### 2. Backward Compatibility
`calculate_position_size()` signature:
```python
def calculate_position_size(edge, win_prob, capital, vol_ratio=1.0, confidence=0.80):
```
Default `confidence=0.80` → `kelly_fraction_for_confidence(0.80)` → **0.25**, which matches the old flat `KELLY_FRACTION = 0.25` constant. All existing call sites that omit `confidence` are unaffected. ✅

### 3. Caps Unchanged
All three caps verified intact in `strategy.py`:
- `MAX_POSITION_CAP = 25.0` — $25 hard cap per entry ✅
- `should_add()` defaults `max_allocation=50.0` — $50 ticker max ✅
- `DAILY_CAP_RATIO = 0.70` — 70% daily cap ✅

No changes found to cap enforcement logic in `calculate_position_size()` or `check_daily_cap()`. ✅

### 5. NWS Penalty Floor
`confidence = max(confidence - 0.15, 0.50)` — floor of 0.50 equals `MIN_CONFIDENCE`. Correct: signals cannot be degraded below the entry threshold. ✅

### 7. Trading Thresholds Unchanged
All minimum thresholds verified identical to spec:

| Threshold | Expected | Actual | Status |
|-----------|----------|--------|--------|
| Min edge (weather) | 15% | `MIN_EDGE['weather'] = 0.15` | ✅ |
| Min edge (crypto) | 10% | `MIN_EDGE['crypto'] = 0.10` | ✅ |
| Min confidence | 50% | `MIN_CONFIDENCE = 0.50` | ✅ |

`edge_detector.py` `MIN_ENSEMBLE_CONFIDENCE = 0.5` also unchanged. ✅

### 8. Circular Imports / Hardcoded Keys
- `strategy.py` imports only `sys` — no module imports, no circular risk. ✅
- `edge_detector.py` imports `noaa_client`, `openmeteo_client`, `config` — no circular import back into `strategy.py`. ✅
- No hardcoded API keys, tokens, or passwords found in either file. ✅

---

## ❌ Issues (Must Fix Before Commit)

### Issue 1 — `edge_detector.py`: NWS falsy-check bug (0°F false positive)

**File:** `edge_detector.py`
**Approx. line:** inside `analyze_market()`, primary signal block

**Bug:**
```python
nws_data = signal.get("nws_current_f")
if not nws_data:   # ← BUG: falsy check, not None check
    confidence = max(confidence - 0.15, 0.50)
```

**Problem:** `nws_current_f` is a temperature in °F (float). `not nws_data` evaluates to `True` when:
- `None` — NWS data genuinely unavailable ✅ (intended)
- `0` or `0.0` — temperature is exactly 0°F ❌ (incorrectly applies penalty!)
- `0.0` is a valid real temperature for Chicago, NYC in deep winter

A temperature reading of 0°F is falsy in Python, so `if not nws_data:` incorrectly treats valid NWS data as "NWS unavailable" and degrades confidence by 15pp. This would incorrectly penalise Chicago and NYC markets in winter conditions.

**Required fix:**
```python
if nws_data is None:   # ← correct: distinguishes "no data" from "0°F reading"
```

**Same falsy-check issue in `nws_degraded` flag assignment (line further down):**
```python
result['nws_degraded'] = not bool(ensemble_data.get("nws_current_f"))
```
This also evaluates 0°F as degraded. Must be:
```python
result['nws_degraded'] = ensemble_data.get("nws_current_f") is None
```

---

## ⚠️ Warnings (Discretionary — CEO Decides)

### Warning 1 — `nws_degraded` flag absent on NOAA-fallback signals

**File:** `edge_detector.py`

`nws_degraded` is only set inside the `if ensemble_data:` block. If `ensemble_data` is `None` (series not in `TICKER_TO_SERIES` or `threshold_f` is None) — which means the NOAA fallback path was used — `nws_degraded` will be absent from the result dict entirely.

Dashboard code that reads `result["nws_degraded"]` will raise `KeyError`. Dashboard code that uses `.get("nws_degraded")` will get `None` (not `False`), which may render inconsistently.

**Recommendation:** Either always set `nws_degraded = False` as a default before the `if ensemble_data:` block, or ensure dashboard uses `.get("nws_degraded", False)`.

### Warning 2 — Minor `nws_degraded` inconsistency on ensemble-fail + NOAA-fallback path

**File:** `edge_detector.py`

If `series in TICKER_TO_SERIES` and `threshold_f is not None` (so `ensemble_data` is set), but `final_prob is None` (ensemble call failed), the code falls to NOAA fallback. In this case, no NWS penalty is applied (the NWS check is inside `if signal.get("final_prob") is not None`). However, `nws_degraded` is still set in the result dict based on `ensemble_data.get("nws_current_f")`, so it could read `True` even though no confidence penalty was applied.

**Impact:** Low — dashboard would show NWS-degraded indicator for a NOAA-fallback signal that didn't actually receive the NWS penalty. Potentially misleading but not a trading logic error.

**Recommendation:** Document this case or add a comment; the NWS penalty and the `nws_degraded` flag should ideally share the same code path.

### Warning 3 — Developer NOTE (from SA-3 summary, not a code bug)

SA-3 flagged that `ruppert_cycle.py` was also staged in the commit. QA has not reviewed that file (out of scope). CEO should verify its inclusion in commit `b970ea9` was intentional.

---

## Summary

| Item | Result |
|------|--------|
| 1. Kelly tiers correct | ✅ Verified |
| 2. Backward compatibility (default conf=0.80) | ✅ Verified |
| 3. Caps unchanged ($25/$50/70%) | ✅ Verified |
| 4. NWS penalty field check | ❌ Bug — `if not nws_data` should be `if nws_data is None` |
| 5. NWS penalty floor (0.50) | ✅ Verified |
| 6. nws_degraded flag reliability | ⚠️ Warning — absent on NOAA-fallback signals |
| 7. Thresholds unchanged (edges, min confidence) | ✅ Verified |
| 8. No circular imports, no hardcoded keys | ✅ Verified |

**Required fixes before merge:**
1. `edge_detector.py`: Change `if not nws_data:` → `if nws_data is None:`
2. `edge_detector.py`: Change `not bool(ensemble_data.get("nws_current_f"))` → `ensemble_data.get("nws_current_f") is None`

---
**QA RE-REVIEW (SA-4, 2026-03-12):** PASS — NWS falsy-check fix verified: if nws_data is None: correct; esult['nws_degraded'] = ensemble_data.get("nws_current_f") is None correct; 
ws_degraded = False default present before if ensemble_data: block; git diff confirms only edge_detector.py modified, strategy.py untouched. Safe to commit.
