# Spec: Weather Trade Logging — 3 Missing Fields
**Date:** 2026-03-30
**Author:** Data Scientist (subagent)
**Status:** APPROVED FOR IMPLEMENTATION
**Triggered by:** Strategist audit — ensemble data computed but not persisted to trade logs

---

## Executive Summary

The weather module computes a rich multi-model ensemble signal (ECMWF + GFS/GEFS + ICON) and logs only the blended output probability as `noaa_prob`. The underlying point estimate temperature, model source flag, and per-component probabilities are computed inside `edge_detector.py → analyze_market()` and `openmeteo_client.py → get_full_weather_signal()` but are **discarded after opportunity construction** — they never reach `logger.py → build_trade_entry()`.

This blocks post-trade audit and calibration analysis: we cannot determine whether ensemble or NOAA-fallback drove a trade, what temperature the ensemble predicted, or whether high model divergence preceded a loss.

---

## Code Audit

### File 1: `agents/ruppert/strategist/edge_detector.py`

#### Where the signal is computed

`analyze_market()` (line ~260):
```python
signal = get_full_weather_signal(series, threshold_f, target_date)
ensemble_data = signal
```

`signal` (returned by `get_full_weather_signal`) is a rich dict containing:
- `signal["ensemble"]` — the blended ensemble result from `get_ensemble_probability()`
  - `["ensemble"]["models_used"]` — list of per-model dicts: `[{model, weight, prob, members, mean_f}, ...]`
    - ECMWF: model key = `"ecmwf_ifs025"`, `mean_f` = mean of ensemble members in °F
    - GFS: model key = `"gfs_seamless"`, `mean_f` = mean of ensemble members in °F
    - ICON: model key = `"icon_global"`, `mean_f` = mean of ensemble members in °F
  - `["ensemble"]["ensemble_mean"]` — primary model (ECMWF preferred) mean_f in °F → **source for `ensemble_temp_forecast_f`**
  - `["ensemble"]["model_details"]` — per-model prob: `{model: {prob, confidence, total_members, mean_f, error}}`
- `signal_src` — set to `"open_meteo_multi_model"` or `"noaa_fallback"` → **source for `model_source`**

#### Where the result dict is built

`analyze_market()` (line ~370–420):
```python
result = {
    'ticker':      ticker,
    ...
    'noaa_prob':   round(model_prob, 4),   # ← blended probability, misleadingly named
    ...
}
# Ensemble detail attach block (line ~425–438):
if ensemble_data:
    ens = ensemble_data.get("ensemble", {})
    result['ensemble_median'] = ens.get("ensemble_median")
    result['ensemble_mean']   = ens.get("ensemble_mean")   # ← already attached!
    result['models_used']     = ensemble_data.get("models_used", [])
    ...
```

**Key finding:** `ensemble_mean` (the primary-model weighted mean temp in °F) is already attached to the result dict. `signal_src` is a local variable but **not attached to result**. `models_used` (list of per-model dicts) is attached.

---

### File 2: `agents/ruppert/data_scientist/logger.py`

#### Where trade records are built

`build_trade_entry(opportunity, size, contracts, order_result)` returns a dict. The `opportunity` argument is the result dict from `analyze_market()` (passed through `trader.py → log_trade()`).

Currently logged weather-relevant fields:
```python
'noaa_prob':    opportunity.get('noaa_prob'),
'market_prob':  opportunity.get('market_prob'),
'edge':         opportunity.get('edge'),
'confidence':   opportunity.get('confidence'),
```

Currently **not logged** (but available in opportunity):
- `ensemble_mean` — already in opportunity dict (attached in edge_detector)
- `signal_src` — **NOT in opportunity** (local variable only in analyze_market)
- `models_used` — in opportunity dict, contains per-model probs needed for components

---

## Specification: 3 New Fields

### Field 1: `ensemble_temp_forecast_f`

| Attribute | Value |
|-----------|-------|
| **Type** | `float \| None` |
| **Units** | °F |
| **Semantics** | Weighted-mean high temperature predicted by the multi-model ensemble for the traded city at contract settlement date. This is the point estimate — not a probability. Enables post-trade comparison: predicted_temp vs actual_settled_temp. |
| **Null conditions** | `None` when `model_source == "noaa_fallback"` (NOAA does not return a temperature point estimate, only a probability) |

**Data source (trace):**
```
openmeteo_client.get_full_weather_signal()
  → get_ensemble_probability()
    → _fetch_model_ensemble() per model
      → returns ensemble_mean (°F) per model
  → returns ensemble["ensemble_mean"]  ← primary-model mean
                                          (ECMWF preferred, else first successful)
→ stored in signal["ensemble"]["ensemble_mean"]
→ attached to opportunity as opportunity["ensemble_mean"]  ← already there!
```

**In `build_trade_entry()`, source expression:**
```python
'ensemble_temp_forecast_f': opportunity.get('ensemble_mean'),
```

> ⚠️ **Note on bias:** `ensemble_mean` in the opportunity dict is the raw (un-bias-corrected) primary model mean. The ensemble fetches at `effective_threshold = threshold_f - bias`, but `ensemble_mean` reflects the actual ensemble distribution mean. This is correct for logging — we want the model's raw forecast for calibration, not the bias-shifted version.

---

### Field 2: `model_source`

| Attribute | Value |
|-----------|-------|
| **Type** | `string \| None` |
| **Allowed values** | `"ensemble"`, `"noaa_fallback"` |
| **Semantics** | Whether this trade was driven by the full multi-model ensemble (ECMWF + GFS + ICON) or fell back to NOAA single-model probability. Allows separation of ensemble vs fallback performance in audit queries. |
| **Null conditions** | `None` for non-weather modules (logged but ignored) |

**Data source (trace):**
```
edge_detector.analyze_market()
  → signal_src = "open_meteo_multi_model"  ← if ensemble succeeded
  → signal_src = "noaa_fallback"           ← if ensemble failed + NOAA available
  → currently stored in local var signal_src only — NOT attached to result dict
```

**Required change in `edge_detector.py` — `analyze_market()`, result dict construction:**
```python
# ADD to result dict (alongside 'noaa_prob', 'signal_src' etc.):
'model_source': 'ensemble' if signal_src == 'open_meteo_multi_model' else signal_src,
```

Mapping:
- `"open_meteo_multi_model"` → `"ensemble"`
- `"noaa_fallback"` → `"noaa_fallback"`
- Any other value → pass through as-is

Note: `signal_src` is already referenced in `result` as a debug field in some log lines but was never surfaced to the opportunity dict returned to the trader. This fix makes it permanent and consumer-facing.

**In `build_trade_entry()`, source expression:**
```python
'model_source': opportunity.get('model_source'),
```

---

### Field 3: `ensemble_components`

| Attribute | Value |
|-----------|-------|
| **Type** | `dict \| None` |
| **Schema** | `{"ecmwf_prob": float, "gfs_prob": float, "icon_prob": float, "divergence_f": float}` |
| **Semantics** | Per-model probabilities before blending, plus max inter-model temperature spread (divergence). High divergence = models disagree = lower real confidence even when blended probability looks strong. |
| **Null conditions** | `None` when `model_source == "noaa_fallback"` (no ensemble components exist) |

**Sub-field definitions:**

| Sub-field | Source expression | Notes |
|-----------|------------------|-------|
| `ecmwf_prob` | `models_used` entry where `model == "ecmwf_ifs025"`, key `prob` | 0–1 probability from ECMWF members |
| `gfs_prob` | `models_used` entry where `model == "gfs_seamless"`, key `prob` | 0–1 probability from GFS/GEFS members |
| `icon_prob` | `models_used` entry where `model == "icon_global"`, key `prob` | 0–1 probability from ICON members |
| `divergence_f` | `max(mean_f) - min(mean_f)` across models in `models_used` | Max spread of ensemble means in °F. `None` if <2 models available |

**Data source (trace):**
```
edge_detector.analyze_market()
  → ensemble_data = signal  (= get_full_weather_signal return)
  → result['models_used'] = ensemble_data.get("models_used", [])
     each entry: {model, weight, prob, members, mean_f}

models_used example:
  [
    {"model": "ecmwf_ifs025", "weight": 0.4, "prob": 0.72, "members": 51, "mean_f": 87.3},
    {"model": "gfs_seamless",  "weight": 0.4, "prob": 0.68, "members": 31, "mean_f": 85.1},
    {"model": "icon_global",   "weight": 0.2, "prob": 0.81, "members": 40, "mean_f": 89.4},
  ]

divergence_f = max(87.3, 85.1, 89.4) - min(87.3, 85.1, 89.4) = 89.4 - 85.1 = 4.3°F
```

**Helper function to add in `logger.py` (or inline in `build_trade_entry`):**
```python
def _build_ensemble_components(opportunity: dict) -> dict | None:
    """Extract per-model probabilities and divergence from opportunity dict."""
    models_used = opportunity.get('models_used')
    if not models_used:
        return None
    model_map = {m['model']: m for m in models_used}
    ecmwf = model_map.get('ecmwf_ifs025', {})
    gfs   = model_map.get('gfs_seamless', {})
    icon  = model_map.get('icon_global', {})
    means = [m.get('mean_f') for m in models_used if m.get('mean_f') is not None]
    divergence_f = round(max(means) - min(means), 1) if len(means) >= 2 else None
    return {
        'ecmwf_prob':    ecmwf.get('prob'),
        'gfs_prob':      gfs.get('prob'),
        'icon_prob':     icon.get('prob'),
        'divergence_f':  divergence_f,
    }
```

**In `build_trade_entry()`, source expression:**
```python
'ensemble_components': _build_ensemble_components(opportunity),
```

---

## BEFORE / AFTER Spec

### BEFORE — `build_trade_entry()` weather-relevant fields
```python
return {
    ...
    'noaa_prob':    opportunity.get('noaa_prob'),    # blended model prob (poorly named)
    'market_prob':  opportunity.get('market_prob'),
    'edge':         opportunity.get('edge'),
    'confidence':   opportunity.get('confidence'),
    # No: ensemble_temp_forecast_f
    # No: model_source
    # No: ensemble_components
    ...
}
```

### AFTER — `build_trade_entry()` weather-relevant fields
```python
return {
    ...
    'noaa_prob':    opportunity.get('noaa_prob'),    # kept for dashboard compat
    'market_prob':  opportunity.get('market_prob'),
    'edge':         opportunity.get('edge'),
    'confidence':   opportunity.get('confidence'),
    # ── NEW: Weather ensemble audit fields ──────────────────────────────────
    'ensemble_temp_forecast_f': opportunity.get('ensemble_mean'),
    'model_source':             opportunity.get('model_source'),
    'ensemble_components':      _build_ensemble_components(opportunity),
    ...
}
```

### BEFORE — `analyze_market()` result dict (weather opportunity)
```python
result = {
    ...
    'noaa_prob':   round(model_prob, 4),
    'signal_src':  signal_src,              # not in result dict — local var only
    'ensemble_mean': ens.get("ensemble_mean"),  # attached in ensemble_data block
    'models_used': ensemble_data.get("models_used", []),
    ...
}
```

### AFTER — `analyze_market()` result dict
```python
result = {
    ...
    'noaa_prob':    round(model_prob, 4),
    'model_source': 'ensemble' if signal_src == 'open_meteo_multi_model' else signal_src,  # NEW
    'ensemble_mean': ens.get("ensemble_mean"),  # already present — consumed by logger
    'models_used':  ensemble_data.get("models_used", []),  # already present
    ...
}
```

---

## Implementation Checklist

### `agents/ruppert/strategist/edge_detector.py`
- [ ] In `analyze_market()`, add `'model_source'` to `result` dict when building the result (before the ensemble_data attach block)
  - Value: `'ensemble'` when `signal_src == 'open_meteo_multi_model'`, else `signal_src`
  - Must be set even when `ensemble_data` is None (e.g. NOAA fallback path)

### `agents/ruppert/data_scientist/logger.py`
- [ ] Add `_build_ensemble_components(opportunity)` helper function (above `build_trade_entry`)
- [ ] Add 3 new fields to `build_trade_entry()` return dict:
  - `'ensemble_temp_forecast_f': opportunity.get('ensemble_mean')`
  - `'model_source':             opportunity.get('model_source')`
  - `'ensemble_components':      _build_ensemble_components(opportunity)`
- [ ] Place new fields after `'confidence'` and before `'entry_price'` for logical grouping

### No changes required
- `openmeteo_client.py` — already returns `ensemble_mean` and `models_used`; no API contract changes
- `trader.py` — passes opportunity dict unchanged to `log_trade()`; no changes needed
- Dashboard / `data_agent.py` — new fields are additive; existing queries unaffected

---

## Validation Criteria (for QA)

After implementation, a weather trade log entry should contain:

```json
{
  "trade_id": "...",
  "ticker": "KXHIGHMIA-26MAR31-B84.5",
  "noaa_prob": 0.72,
  "ensemble_temp_forecast_f": 87.3,
  "model_source": "ensemble",
  "ensemble_components": {
    "ecmwf_prob": 0.72,
    "gfs_prob": 0.68,
    "icon_prob": 0.81,
    "divergence_f": 4.3
  }
}
```

NOAA fallback trade should log:
```json
{
  "noaa_prob": 0.65,
  "ensemble_temp_forecast_f": null,
  "model_source": "noaa_fallback",
  "ensemble_components": null
}
```

Non-weather trade (crypto, fed, etc.) should log:
```json
{
  "noaa_prob": null,
  "ensemble_temp_forecast_f": null,
  "model_source": null,
  "ensemble_components": null
}
```

---

## Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| JSONL log file size increase | Low | `ensemble_components` adds ~100 bytes/entry. At 10 trades/day, negligible. |
| `models_used` missing for NOAA fallback | Low | Helper returns `None` safely when `models_used` is empty/absent |
| `ensemble_mean` is primary-model mean, not blended mean | Low-Med | Document clearly in field name. Consider renaming to `primary_model_mean_f` in v2 if confusion arises. |
| Dashboard breakage | None | Fields are additive; existing dashboard queries use `noaa_prob`, `edge`, `confidence` — unaffected |
| Backward compat in audit queries | None | Old records simply have `null` for new fields — `WHERE ensemble_temp_forecast_f IS NOT NULL` filters cleanly |

---

## Notes for Developer

1. **`ensemble_mean` naming:** The field `opportunity.get('ensemble_mean')` is the mean temperature from the primary model (ECMWF when available, else first successful). It is NOT the weighted-average temperature across all three models. The spec logs this as `ensemble_temp_forecast_f` — the name is accurate because it represents the ensemble's point forecast. A future v2 could compute a weighted-mean temperature across all model means for greater accuracy.

2. **`model_source` must be set in the NOAA fallback path too:** In `analyze_market()`, the NOAA fallback block sets `signal_src = "noaa_fallback"` but currently does not attach it to `result`. Both the ensemble path and the NOAA path reach the same `result = {...}` construction — so adding `model_source` there covers both cases cleanly.

3. **`divergence_f` uses mean_f, not raw member values:** The `mean_f` per model is already computed inside `_fetch_model_ensemble()`. Using spread of means (rather than min/max across all 122 combined members) is intentional — it measures inter-model disagreement, not intra-model spread.
