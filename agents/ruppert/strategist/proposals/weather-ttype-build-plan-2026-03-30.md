# T-Type Weather Markets — DEMO Build Plan
**Date:** 2026-03-30  
**Author:** Strategist (Ruppert)  
**Status:** APPROVED — Build for DEMO data collection  
**Decision:** Run T-type IN PARALLEL with B-type (not replacing) to collect live data

---

## Overview

David has approved adding T-type threshold markets to the weather module in DEMO mode. Goal is to generate signal quality data alongside B-type so we can compare performance before making a replacement decision. Both paths run simultaneously; T-type is a new evaluation branch, not a replacement.

T-type markets: `KXHIGHNY-26MAR31-T77` ("will NYC high be >77°F?"), `KXHIGHNY-26MAR30-T62` ("will NYC high be <62°F?")  
Signal: `margin = |bias_corrected_ensemble_point_estimate - threshold|`

---

## 1. Changes to `edge_detector.py`

### 1a. T-type detection already works (partially)

The existing code already handles T-type in several places:
- `parse_threshold_from_ticker()` — parses `T77` format ✓
- `classify_market_type()` — returns `T_upper` / `T_lower` ✓
- P1-4 fix block — infers `T_upper` from ticker when title regex fails ✓
- `T_lower` probability flip (`model_prob = 1.0 - model_prob`) ✓
- Longshot prior for T-markets (soft confidence adjustment) ✓

**What's missing:** The existing code sends T-type markets through the same ensemble *probability* path as B-type. This path computes `P(high >= threshold)` from member counts. That works for T-type direction but doesn't use the `margin` signal that gives T-type its real edge.

### 1b. New: Margin-based confidence for T-type

Add a dedicated T-type confidence path inside `analyze_market()`, **after** the existing ensemble signal is retrieved:

```python
# ── T-type margin-based confidence override ──────────────────────────────────
if market_type in ("T_upper", "T_lower") and ensemble_data:
    ens = ensemble_data.get("ensemble", {})
    point_est = ens.get("ensemble_mean")  # bias-corrected via effective_threshold in openmeteo
    raw_threshold = threshold_f
    
    if point_est is not None:
        # Margin uses the RAW threshold (not effective_threshold) because
        # bias correction is already baked into point_est via effective_threshold shift
        # in get_full_weather_signal(). We reverse to get true margin:
        bias_applied = ensemble_data.get("bias_applied_f", 0.0)
        bias_corrected_point_est = point_est + bias_applied  # undo threshold shift to get true estimate
        
        margin = abs(bias_corrected_point_est - raw_threshold)
        t_confidence = _ttype_margin_to_confidence(margin)
        
        logger.info(
            f"[Edge] {ticker}: T-type margin={margin:.1f}°F "
            f"(est={bias_corrected_point_est:.1f}°F, threshold={raw_threshold}°F) "
            f"→ t_confidence={t_confidence:.2f} (was {confidence:.2f})"
        )
        
        if t_confidence == 0.0:
            logger.info(f"[Edge] {ticker}: T-type margin <2°F — no trade (margin too thin)")
            return None
        
        # Use the better of margin-based confidence and ensemble confidence
        # (ensemble confidence captures model agreement; margin captures signal strength)
        confidence = max(confidence, t_confidence)
        
        # Also store margin for logging/dashboard
        result_extra = {"ttype_margin_f": round(margin, 1), "ttype_point_est_f": round(bias_corrected_point_est, 1)}
```

Place this block **after** the ensemble signal fetch and **before** the confidence gate.

### 1c. New helper function: `_ttype_margin_to_confidence()`

Add this function near the top of `edge_detector.py` (below `apply_volume_tier`):

```python
def _ttype_margin_to_confidence(margin_f: float) -> float:
    """
    Convert T-type threshold margin to entry confidence.
    
    Margin is |bias_corrected_point_estimate - threshold_f|.
    Large margin = strong edge (we're far from the coin-flip zone).
    Small margin = weak edge (we're near the threshold, uncertain territory).
    
    Calibration (approximate, assuming ±3-5°F RMSE):
      ≥8°F  → 0.90 (z≈2.7, P(win)>99%)
      5-8°F → 0.75 (z≈1.7-2.7, P(win)~95-99%)
      2-5°F → 0.50 (z≈0.7-1.7, P(win)~75-95%)
      <2°F  → 0.00 (no trade — coin flip, don't play)
    
    Returns:
        float confidence in [0.0, 0.90], or 0.0 to signal "no trade".
    """
    if margin_f < config.TTYPE_MARGIN_NO_TRADE:  # default 2.0
        return 0.0
    elif margin_f < config.TTYPE_MARGIN_WEAK:     # default 5.0
        return config.TTYPE_CONF_WEAK             # default 0.50
    elif margin_f < config.TTYPE_MARGIN_STRONG:   # default 8.0
        return config.TTYPE_CONF_STANDARD         # default 0.75
    else:
        return config.TTYPE_CONF_STRONG           # default 0.90
```

### 1d. Attach margin data to result dict

In `analyze_market()`, attach T-type margin fields to the result:

```python
# After building the result dict, add T-type fields if computed
if 'result_extra' in locals() and result_extra:
    result.update(result_extra)
```

### 1e. No changes needed to `find_opportunities()` or scan loop

T-type and B-type markets go through the same `find_opportunities()` → `analyze_market()` path. The evaluation branches inside `analyze_market()` based on `market_type`. Same scan, separate evaluation path within the same function. ✓

---

## 2. Signal: Entry Confidence from Margin

### The formula

```
bias_corrected_point_estimate = ensemble_mean + bias_applied_f
margin = |bias_corrected_point_estimate - threshold_f|
```

**Why this works:**  
`get_full_weather_signal()` applies bias by lowering the effective threshold (`effective_threshold = threshold_f - bias`). This means `ensemble_mean` is returned relative to the *lowered* threshold. To get the true temperature estimate, we add `bias_applied_f` back.

### Confidence tiers

| Margin | Confidence | Trade? | Rationale |
|--------|-----------|--------|-----------|
| <2°F | 0.0 | **No** | Within ±1 RMSE — coin flip |
| 2–5°F | 0.50 | Small/skip | Some edge, but risky |
| 5–8°F | 0.75 | Standard | Real edge, bet it |
| ≥8°F | 0.90 | Strong | Near-certain directional call |

### Confidence gate interaction

The existing `MIN_CONFIDENCE['weather'] = 0.25` gate still applies. T-type margin confidence (0.50+ for 2–5°F) will clear this. The T-type longshot prior (existing soft prior for `|edge| <= 0.30`) also still applies on top.

**Key behavior:** If `margin < 2°F`, the function returns `None` before building a result — no opportunity generated, regardless of ensemble probability.

---

## 3. Sizing

**T-type sizing for DEMO data collection phase:**

- **Per trade:** $50 (fixed, no scaling in data collection phase)
- **Daily max:** $500 across all T-type weather trades
- **Daily B-type + T-type combined:** shared from `WEATHER_DAILY_CAP_PCT = 0.07` (7% of capital)
- **Per-city limit:** No more than $100/day per city across both T-type markets (upper + lower)

### Config constants needed (see Section 5):

```
TTYPE_PER_TRADE_SIZE = 50.0       # $50 per T-type trade
TTYPE_MAX_DAILY = 500.0           # $500/day hard cap for T-type
TTYPE_PER_CITY_DAILY_MAX = 100.0  # $100/city/day across both threshold directions
```

### Sizing logic in `strategy.py`

The existing `MAX_POSITION_PCT` (1% of capital) already caps per-trade size. At current ~$8,300 capital, 1% = $83, so $50 is already within that constraint. No `strategy.py` changes needed for Phase 1; the fixed $50 is below the dynamic cap.

For the daily cap, the existing `WEATHER_DAILY_CAP_PCT` should naturally limit combined B+T exposure. We add `TTYPE_MAX_DAILY` as a T-type-specific hard stop to prevent T-type from consuming the entire weather budget.

---

## 4. T-Type Alongside B-Type in the Weather Scan

### Architecture decision: Same scan, branching evaluation

**T-type uses the same scan path as B-type.** No separate scan loop, no separate API call. The flow is:

```
find_opportunities(markets)
  └── for each market:
        analyze_market(market)
          ├── classify_market_type() → T_upper / T_lower / B_band
          ├── [existing B-band path: ensemble prob → edge → threshold]
          └── [NEW T-type path: margin calculation → confidence override → edge]
```

**How Kalshi returns T-type markets:** T-type tickers appear in the same KXHIGH series. The scanner already fetches all KXHIGH markets from Kalshi — T-type tickers (`KXHIGHNY-26MAR31-T77`) will appear alongside B-type tickers (`KXHIGHMIA-26MAR10-B84.5`) in the same market list. No additional API calls needed.

**Separation concerns:** In DEMO data collection mode, we want to log B-type and T-type performance separately. Both produce `market_type` in the result dict (`"T_upper"`, `"T_lower"`, `"B_band"`), so the logger can split them automatically. No code changes needed for separation — it's already tracked.

### Key difference: T-type markets seen in Kalshi right now

Looking at the known tickers: `KXHIGHNY-26MAR31-T77` and `KXHIGHNY-26MAR30-T62`. These will be classified as `T_upper` and `T_lower` respectively by `classify_market_type()`. The existing code already handles these — the new addition is the **margin confidence path** that gives T-type signals more appropriate confidence scores than the B-type ensemble probability path.

---

## 5. New Config Constants Needed

Add to `environments/demo/config.py`:

```python
# ── T-Type Weather Markets ────────────────────────────────────────────────────
# Margin-based signal thresholds (°F from threshold)
TTYPE_MARGIN_NO_TRADE = 2.0    # Below this margin: skip (coin flip territory)
TTYPE_MARGIN_WEAK     = 5.0    # Below this: weak confidence
TTYPE_MARGIN_STRONG   = 8.0    # Above this: strong confidence

# Confidence levels per margin tier
TTYPE_CONF_WEAK       = 0.50   # 2–5°F margin → 50% confidence
TTYPE_CONF_STANDARD   = 0.75   # 5–8°F margin → 75% confidence
TTYPE_CONF_STRONG     = 0.90   # ≥8°F margin → 90% confidence

# Sizing — DEMO data collection phase
TTYPE_PER_TRADE_SIZE      = 50.0    # $50 per T-type trade
TTYPE_MAX_DAILY           = 500.0   # $500/day hard cap across all T-type trades
TTYPE_PER_CITY_DAILY_MAX  = 100.0   # $100/city/day (across upper + lower threshold)

# Enable T-type in DEMO (set False to disable without code changes)
TTYPE_ENABLED = True
```

### `getattr` safety pattern for new constants

In `edge_detector.py`, use `getattr(config, 'TTYPE_MARGIN_NO_TRADE', 2.0)` for all new constants. This prevents import errors if the constant is missing in older configs or production environments.

---

## 6. Logging Requirements

T-type data collection is only useful if we capture the right fields. Ensure `logger.py` records these fields for T-type trades:

| Field | Already logged? | Action |
|-------|----------------|--------|
| `market_type` | ✓ Yes | No change |
| `threshold_f` | ✓ Yes | No change |
| `ttype_margin_f` | ✗ No | Add to result dict (Section 1d) |
| `ttype_point_est_f` | ✗ No | Add to result dict (Section 1d) |
| `ensemble_mean` | Partial (null historically) | Fix ensemble_mean logging — this is the P0 for T-type |
| `bias_applied_f` | ✓ Yes | No change |
| `side` (yes/no) | ✓ Yes | No change |
| `win_prob` | ✓ Yes | No change |

**Critical:** `ensemble_mean` must be non-null for T-type margin to compute. The existing `data_scientist/logger.py` schema has `ensemble_temp_forecast_f` but it was null for all 33 prior trades. This logging gap **must be fixed in the same Dev sprint as the T-type build.** Without it, post-trade analysis is impossible.

---

## 7. Build Sequence

### Phase 1: Config (30 min)
1. Add `TTYPE_*` constants to `environments/demo/config.py`
2. No changes to live/prod config yet

### Phase 2: `edge_detector.py` (2-3 hours)
3. Add `_ttype_margin_to_confidence()` helper function
4. Add T-type margin calculation block inside `analyze_market()`
5. Add margin fields to result dict
6. Add `TTYPE_ENABLED` gate at top of T-type evaluation path

### Phase 3: Logger fix (1 hour)
7. Fix `ensemble_temp_forecast_f` null logging bug in `data_scientist/logger.py`
8. Verify the field populates correctly on test run

### Phase 4: Sizing gate (1 hour)
9. Add T-type daily cap check to `strategy.py` or `trader.py` using `TTYPE_MAX_DAILY`
10. Add per-city T-type daily cap check using `TTYPE_PER_CITY_DAILY_MAX`

### Phase 5: Test
11. Run `edge_detector.py __main__` with mock T-type markets at various margins
12. Verify: margin <2°F returns None, margin 5°F returns standard confidence, margin 8°F returns strong confidence
13. Verify: T_lower markets still flip probability correctly with margin path
14. Run full DEMO scan cycle; confirm T-type and B-type both appear in output with distinct `market_type` labels

---

## 8. Risk Notes

- **Bias correction dependency:** T-type margin accuracy depends on good bias corrections. Denver's +0.08°F correction is broken (see bias fix plan). Fix Denver before trusting Denver T-type signals.
- **OKC backwards correction:** OKC hardcoded +3°F is backwards (-2°F actual error). OKC T-type signals will be wrong until fixed.
- **n=1 data limitation:** We have one settlement per city. Margin thresholds (2/5/8°F) are theoretically derived from ±3-5°F RMSE, not empirically calibrated yet. After 20+ T-type settled trades, the Optimizer should review actual win rates by margin tier and retune these constants.
- **Correlation:** NYC and Chicago T-type markets may fire simultaneously in cold fronts. $100/city/day cap limits correlated loss.

---

## Key Decisions Summary

| Decision | Choice | Rationale |
|----------|--------|-----------|
| T-type vs B-type architecture | **Same scan, branching evaluation** | Minimal code delta; both types already flow through `analyze_market()` |
| Replace or parallel? | **Parallel (DEMO data collection)** | Need T-type performance data before committing to full replacement |
| Signal formula | **`margin = \|bias_corrected_estimate - threshold\|`** | Captures directional confidence better than ensemble prob alone |
| No-trade threshold | **<2°F margin** | Within ±1 typical RMSE — not enough signal |
| Strong signal threshold | **≥8°F margin** | ≥2 standard deviations from threshold at ±3-4°F RMSE |
| Sizing | **$50/trade, $500/day max** | Conservative for data collection; matches Strategist recommendation |
| Ensemble_mean null fix | **Must fix in same sprint** | T-type signal is blind without it |

---

*Strategist — 2026-03-30*
