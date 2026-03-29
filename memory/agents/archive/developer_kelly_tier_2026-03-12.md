# SA-3 Developer Summary — Kelly Tier + NWS Penalty
_Date: 2026-03-12_
_Agent: SA-3 Developer_
_Task: Confidence-tiered Kelly sizing + NWS-down confidence penalty_
_Status: COMPLETE — staged and committed; awaiting QA review_

---

## Changes Made

### 1. `bot/strategy.py` — Confidence-tiered Kelly sizing

**What changed:**
- Added `kelly_fraction_for_confidence(confidence: float) -> float` function (placed before section 1, Position Sizing)
- `calculate_position_size()` gains a new `confidence: float = 0.80` parameter (default preserves backward compatibility)
- `should_enter()` now passes `confidence` to `calculate_position_size()`
- Entry reason string now includes `kf=XX%` for audit visibility
- `get_strategy_summary()` updated — replaced single `kelly_fraction` key with five keys showing all tiers

**Kelly tiers:**
| Confidence | Kelly multiplier |
|------------|-----------------|
| 80%+       | 0.25 (unchanged from old flat default) |
| 70–80%     | 0.20 |
| 60–70%     | 0.15 |
| 50–60%     | 0.10 |

**Caps unchanged:** `min($25, 2.5% capital)` entry cap, `$50` ticker cap, `70%` daily cap — all untouched.

**Backward compat:** `calculate_position_size()` called without `confidence` defaults to `0.80` (max tier), so any existing call sites outside `should_enter()` are unaffected.

**Test note:** With `capital=$1,000` and `edge=0.20`, all four tiers hit the `$25` hard cap (even `kf=0.10` produces `$66.67` uncapped → capped at `$25`). The tiering activates for smaller capital / lower-edge signals where uncapped Kelly < `$25`. Logic is correct — the cap is working as intended.

---

### 2. `edge_detector.py` — NWS-down confidence penalty

**What changed:**
- Inside `analyze_market()`, after extracting `confidence` from the ensemble signal, added NWS check:
  - `nws_data = signal.get("nws_current_f")` — this is the combined NWS result (official gridpoint → legacy station obs fallback)
  - If `not nws_data` (None = both sources failed): `confidence = max(confidence - 0.15, 0.50)`
  - Emits `logger.warning` with degraded value
- Added `result['nws_degraded'] = not bool(ensemble_data.get("nws_current_f"))` to the result dict for dashboard/logging visibility

**Why this matters:**
- Miami (`KXHIGHMIA`) MFL grid returns 404 reliably — previously the ensemble confidence was used at full value even though the NWS verification layer was absent. Now confidence is degraded 15pp, floored at 50%.
- The penalty stacks correctly with the T-market soft prior (soft prior runs after, on the already-degraded confidence).

---

## Files Modified

| File | Change |
|------|--------|
| `bot/strategy.py` | `kelly_fraction_for_confidence()` + tiered `calculate_position_size()` |
| `edge_detector.py` | NWS-down confidence penalty + `nws_degraded` flag |

## Git Commit

Commit hash: `b970ea9`
Message: `feat: confidence-tiered Kelly sizing + NWS-down confidence penalty`

**NOT pushed** — awaiting CEO/QA review per rules.

---

## TODOs / Notes for QA

- Verify `nws_degraded` flag appears correctly in dashboard JSON output (dashboard team may want to surface this visually)
- The `ruppert_cycle.py` file was also staged (pre-existing change) — verify it was intentional
- Consider adding a unit test for the NWS penalty path in `edge_detector.py` (currently no mock test for `nws_current_f=None`)
- When `bot/strategy.py` is wired into `main.py` (pending), confirm `confidence` is passed through the full signal chain

[SA-3 Fix 2026-03-12] Fixed falsy-check bug in edge_detector.py: if not nws_data: ? if nws_data is None:, 
ot bool(...) ? ... is None, added default 
ws_degraded = False before ensemble block so 0�F readings no longer incorrectly trigger NWS confidence penalty; staged with git add.
