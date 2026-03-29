# SA-2 Developer — Fed Ensemble Implementation Summary
_Date: 2026-03-13 | Author: SA-2 Developer_
_Tasks: Fed ensemble (fed_client.py) + Spread proxy + MIN_EDGE fix (strategy.py)_

---

## 1. CME Endpoint Discovery

**Result: NOT FOUND.**

All three candidate endpoints tested:
- `https://www.cmegroup.com/CmeWS/mvc/MktData/getFedWatch.json` → **404**
- `https://www.cmegroup.com/CmeWS/mvc/FedWatch/probabilities` → **404**
- `https://www.cmegroup.com/CmeWS/mvc/FutureContracts/FED/getFedWatchData` → **404**

HTML page (`cme-fedwatch-tool.html`) fetched and inspected — it is a JavaScript SPA. The readability-extracted text contains no AJAX endpoint URLs.

**Action taken:** `get_cme_fedwatch_probabilities()` implemented as a stub that returns `None` immediately with comment: "CME AJAX endpoint not identified — stub until official API approved."

**To activate CME:** Use Chrome DevTools → Network → XHR/Fetch on the FedWatch page to identify the live endpoint. Update the stub function body.

---

## 2. Changes to `ruppert-tradingbot-demo/fed_client.py`

### Step 0 — CME stub
Added `get_cme_fedwatch_probabilities(meeting_date: date) -> dict | None` immediately before the Polymarket section. Returns `None` (stub). Full docstring explains why and how to activate.

### Step 1 — FRED series switch
- **Before:** `https://fred.stlouisfed.org/graph/fredgraph.csv?id=FEDFUNDS` (monthly, lagged)
- **After:** `https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFEDTARU` (daily target upper bound)
- Updated log message and self-test print from `FEDFUNDS` → `DFEDTARU`.

### Step 2 — New functions added
Three new functions added between FRED and Polymarket sections:

1. **`get_cme_fedwatch_probabilities(meeting_date)`** — stub, returns None immediately.

2. **`_fred_sanity_check(fed_rate, outcome, ensemble_p) -> bool`**
   - Implements Optimizer spec Section 3a exactly
   - Floor check: `fed_rate <= 0.25%` AND cut outcome with `ensemble_p > 30%` → False
   - Ceiling check: `fed_rate >= 5.5%` AND hike outcome with `ensemble_p > 30%` → False
   - All other cases → True

3. **`compute_ensemble_confidence(cme_p, poly_p, ensemble_p, fred_sanity_ok) -> float`**
   - Implements Optimizer spec Section 4 exactly
   - Step 1: Base confidence from probability extremity → range [0.50, 1.00]
   - Step 2: Agreement factor by divergence bands (≤5pp: 1.05, 5-10pp: 1.00, 10-20pp: 0.90, >20pp: 0.80); single-source: CME-only = 1.00, Polymarket-only = 0.85 (−15% multiplier)
   - Step 3: FRED factor (0.90 if not fred_sanity_ok, else 1.00)
   - Step 4: Capped at 0.99

### Step 3 — `get_fed_signal()` refactored

**Source fetching:** Now calls `get_cme_fedwatch_probabilities()` + `get_polymarket_fomc_probabilities()` in parallel (sequential calls, both always attempted).

**Fallback logic (Optimizer spec Section 2):**
| Scenario | Action |
|----------|--------|
| Both ✅ | `prob_source = 'cme+polymarket'`, full ensemble |
| CME ✅ only | `prob_source = 'cme'`, no penalty |
| Polymarket ✅ only | `prob_source = 'polymarket'`, −15% via `compute_ensemble_confidence` |
| Both ❌ | `skip_reason = 'all_prob_sources_unavailable'`, return no_signal |

**Ensemble probability:** `0.65 * cme_p + 0.35 * poly_p` when both available; single-source used at 100% weight when only one available.

**New fields added to signal dict:**
- `cme_probs` — raw CME probabilities dict (or None)
- `poly_probs` — raw Polymarket probabilities dict (or None)
- `ensemble_probs` — weighted ensemble across all known outcomes
- `source_divergence` — `abs(cme_p - poly_p)` for the best outcome (or None if single-source)
- `prob_source` — `'cme+polymarket'` | `'cme'` | `'polymarket'`
- `polymarket_probs` — kept for backward compatibility (alias of `poly_probs`)

**New skip_reason:** `all_prob_sources_unavailable` (when both CME and Polymarket down).

**slug_unknown handling:** If Polymarket returns slug_unknown but CME is available, continues with CME-only. Previously this was a hard exit.

**Confidence:** All signals now use `compute_ensemble_confidence()` instead of the old extremity-only formula.

All new fields saved to `fed_scan_latest.json` via unchanged `_save_scan_result()`.

---

## 3. Changes to `ruppert-tradingbot-demo/bot/strategy.py`

### Spread Proxy — `apply_market_impact_ceiling()`

New function added at section 1a (between constants and `kelly_fraction_for_confidence`):

```
def apply_market_impact_ceiling(base_size, yes_ask, yes_bid, open_interest=None)
    → tuple[float, str]
```

Logic matches Optimizer spec exactly:
- spread ≤ 3¢ → liquid, full size
- spread 4–7¢ → 50% of base size
- spread > 7¢ → min(base_size, $25.0) hard floor
- OI cap (Phase 2): if `open_interest` provided, cap at 5% of OI (additive to spread tier)
- Returns `(adjusted_size, reason_string)`

### Wired into `should_enter()`

Wiring location: **after** `calculate_position_size()` (Kelly), **before** final `min(impact_size, room)` cap.

```python
raw_size = calculate_position_size(...)  # Kelly

# Market impact ceiling
impact_size, market_impact_reason = apply_market_impact_ceiling(
    raw_size, yes_ask, yes_bid, open_interest)

# Final daily-room cap
size = round(min(impact_size, room), 2)
```

Graceful skip: if `yes_ask` or `yes_bid` absent from signal dict, `market_impact_reason = "skipped_no_spread_data"` and `impact_size = raw_size` (no adjustment).

`market_impact_reason` added to all return dicts from `should_enter()` (enter=True, kelly_size_zero, below_min_viable).

`signal_window` field in `open_interest` is read from `signal.get('open_interest')` — modules that provide it activate Phase 2 automatically.

### MIN_EDGE['crypto'] fix

`MIN_EDGE['crypto']` was already `0.12` in the file (matches `config.py`). Confirmed correct.

Updated stale test print comments that still referenced `min=0.10` → corrected to `min=0.12`.

---

## 4. Blockers / Notes

1. **CME endpoint is the main outstanding item.** Until identified, `prob_source` will be `'polymarket'` (single-source with −15% confidence penalty) or `'all_prob_sources_unavailable'` if Polymarket also down. This is already a major improvement over the prior all-or-nothing Polymarket dependency.

2. **`open_interest` field.** The spread proxy's OI cap (Phase 2) is passive — it only activates when `signal.get('open_interest')` is non-None. No modules currently set this field. Phase 2 will become active automatically when modules start populating it.

3. **`fed_client.py` lives at `ruppert-tradingbot-demo/fed_client.py`** (not `bot/fed_client.py`). Confirmed actual location before editing.

4. Both files pass `ast.parse()` syntax check cleanly.

---

_Ready for QA (SA-4) review._
