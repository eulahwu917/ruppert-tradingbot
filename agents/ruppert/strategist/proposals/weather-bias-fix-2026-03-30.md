# Weather Bias Correction Fix — Denver & OKC
**Date:** 2026-03-30  
**Author:** Strategist (Ruppert)  
**Status:** APPROVED — Fix required before re-enabling weather trading  
**Scope:** Denver (+6°F broken), OKC (backwards correction), global floor consideration

---

## Problem Statement

From bias analysis of 7 settled cities on 2026-03-27:

| City | Actual Error | System Correction | Residual | Status |
|------|-------------|-------------------|---------|--------|
| NYC | +2.5°F | +2.08°F | +0.42°F | ✓ OK |
| Philadelphia | +3.0°F | +3.17°F | -0.17°F | ✓ OK |
| DC | +3.5°F | +2.03°F | +1.47°F | ⚠ Undercorrecting |
| Austin | +4.0°F | +2.73°F | +1.27°F | ⚠ Undercorrecting |
| Chicago | +2.0°F | +3.06°F | -1.06°F | ⚠ Slight overcorrect |
| **Denver** | **+6.0°F** | **+0.08°F** | **+5.92°F** | 🔴 **BROKEN** |
| **OKC** | **-2.0°F** | **+3.0°F (hardcoded)** | **-5.0°F** | 🔴 **BACKWARDS** |

Mean cold bias (all 7): **+2.7°F** (actual temps run warmer than model predicts)

---

## 1. Where Are Bias Corrections Applied?

### The two-layer bias system

**Layer 1 — Primary: `ghcnd_client.py` dynamic cache**
- Function: `get_bias(ticker: str) → float`
- Source: NOAA CDO API + ERA5 reanalysis, 30-day rolling average
- Storage: `logs/ghcnd_bias_cache.json` (refreshed daily)
- Consumed by: `openmeteo_client.get_full_weather_signal()` via `from agents.ruppert.data_analyst.ghcnd_client import get_bias`

**Layer 2 — Fallback: `HARDCODED_BIAS_F` dict in `ghcnd_client.py`**
- Used when: NOAA CDO token missing, API failure, or cache is stale
- Lines 73–93 in `ghcnd_client.py`:
  ```python
  HARDCODED_BIAS_F = {
      "KXHIGHNY":  2.0,
      "KXHIGHCHI": 4.0,
      ...
      "KXHIGHTOKC": 3.0,  # ← OKC hardcoded = +3°F (WRONG)
      ...
  }
  DEFAULT_HARDCODED_BIAS_F = 3.0
  ```

**How bias is applied:**
In `openmeteo_client.get_full_weather_signal()`, line ~780:
```python
effective_threshold = threshold_f - bias
```
The bias is applied by lowering the effective threshold. A +3°F bias → threshold is lowered by 3°F → P(high >= effective_threshold) is higher than P(high >= raw_threshold). This correctly increases the probability that actual temps exceed the threshold when the model runs cold.

**For Denver:** GHCND cache returned +0.08°F → effective_threshold barely changes → P(win) computed as if no systematic error exists. Six-degree cold bias goes completely uncompensated.

**For OKC:** GHCND fallback to hardcoded +3°F (no valid cache) → threshold lowered by 3°F → system bets MORE aggressively on above-threshold outcomes. But actual error was -2°F (model ran HOT), so system was betting in the wrong direction AND overcorrecting.

---

## 2. Corrected Values — Conservative Approach

### ⚠️ Data limitation warning

**n=1 per city.** These corrections are based on a single observed settlement. At n=1, a ±2–4°F "one-day anomaly" vs "true systematic bias" cannot be distinguished statistically. The corrections below are conservative for this reason.

### Denver (KXHIGHDEN)

**Observed:** +6.0°F actual error. GHCND cache returned +0.08°F (essentially zero — likely a data quality failure in the NOAA CDO fetch for Denver's station USW00003017).

**What to fix:**
- The GHCND dynamic correction for Denver is not working. Likely cause: Denver Int'l station (USW00003017) may have sparse or delayed data in the NOAA CDO API, causing `compute_station_bias()` to return `None` and fall back to hardcoded +3°F... but the cache shows +0.08°F, suggesting the GHCND fetch returned data but computed near-zero bias. This may be an ERA5 baseline issue for high-altitude Denver (5,280 ft) — ERA5 may already run warm for Denver due to elevation adjustment, masking the actual cold bias.

**Conservative fix:**
```python
# In HARDCODED_BIAS_F dict — update Denver's fallback
"KXHIGHDEN": 4.0,   # was 3.0 — conservative step toward observed +6°F
```

**Why not +6°F:** n=1 data point. The +6°F was Mar 27 — a specific weather pattern. +4°F is roughly halfway between the broken +0.08°F GHCND value and the observed +6°F. This reduces the worst-case error without overcorrecting.

**Also required:** Investigate why GHCND returns near-zero for Denver. High-altitude stations may need a separate ERA5 elevation correction. Flag for Data Scientist to investigate the GHCND pipeline for USW00003017.

### OKC (KXHIGHTOKC)

**Observed:** -2.0°F actual error (model ran HOT for OKC). System applied +3°F (hardcoded fallback since GHCND has no valid cache for OKC).

**What to fix:**
```python
# In HARDCODED_BIAS_F dict — OKC reversal
"KXHIGHTOKC": 0.0,  # was 3.0 — reset to neutral (don't apply a correction we know is wrong)
```

**Why not -2°F:** Again n=1. Applying -2°F as a correction based on one data point risks overcorrecting in the other direction if Mar 27 was anomalous. Zero is the safest value when the sign of the correction is uncertain. If OKC is in `EXPANDED_CITIES_SKIP` (it is, per config.py), this correction won't affect live trading until OKC is re-enabled anyway.

**Note on hardcoded-fallback cities (TSFO, TSATX, TMIN, TDAL, TNOU, TLV, TSEA, TATL):** All currently use `DEFAULT_HARDCODED_BIAS_F = 3.0`. These cities are all in `EXPANDED_CITIES_SKIP` and not currently trading. The +3°F default was set arbitrarily. Before re-enabling any of these cities, each needs an observed actual temperature vs. GHCND correction audit. Do not adjust these in bulk — audit individually.

---

## 3. Should We Apply a Global +2.7°F Floor?

### Recommendation: **NO — do not apply a global floor**

**Arguments for a global floor:**
- Mean error of +2.7°F across 7 cities is a real signal
- Applying it globally is simple and reduces systematic cold bias immediately
- Better than doing nothing

**Arguments against (why we recommend NO):**

1. **OKC is the counter-example.** OKC's error was -2.0°F (model ran warm). Applying +2.7°F would move OKC's correction from wrong (+3.0°F) to more wrong (+5.7°F). At least one city has the opposite sign of bias.

2. **Chicago is partially over-corrected already.** System applied +3.06°F; actual error was +2.0°F. Adding a global floor on top would push Chicago's effective correction to +5.76°F — overcorrecting by nearly 4°F.

3. **NYC and Philadelphia are already well-corrected.** NYC residual is +0.42°F. A global floor would add noise to a signal that's working.

4. **n=7 cities is not enough to establish a universal floor.** The set of 7 is not a random sample — it's biased toward eastern cities with working GHCND data. The true global mean may be different.

5. **The GHCND dynamic system is the right mechanism.** When it works (eastern cities), it's doing the right thing. The fix is to make GHCND work for Denver and OKC, not to override the whole system with a blunt correction.

**What to do instead of a global floor:**

Apply the targeted per-city fixes (Denver: +4.0°F, OKC: 0.0°F) and leave the GHCND dynamic system to handle the rest. The dynamic system already produces good corrections for NYC, Philadelphia, and DC.

---

## 4. Risk of Overcorrecting

### Overcorrection is the main risk — here's why it's dangerous

For T-type markets specifically, overcorrection is more damaging than undercorrection:

**Undercorrection scenario:** Model predicts 68°F, actual is 74°F, threshold is 77°F. With no correction, system says P(high < 77) = 85% → bets YES (will be <77°F) → actual high is 74°F → WIN. Undercorrection missed that it was even further from threshold, but the directional call was still right.

**Overcorrection scenario:** Model predicts 68°F, actual is 74°F, threshold is 72°F. With +5°F overcorrection, system says "effective temp estimate is 73°F" → margin = 73-72 = 1°F → no trade (too close). But actual was 74°F, well above 72°F → we missed a strong edge signal by overcorrecting.

Worse: if overcorrection flips the direction, system bets the wrong side with high confidence.

### Specific overcorrection risks for proposed changes

| City | Old bias | New bias | Risk |
|------|---------|---------|------|
| Denver | +0.08°F (GHCND) | +4.0°F (hardcoded fallback) | If GHCND later recovers and Denver's true bias is +1-2°F, hardcoded +4°F would overcorrect. Mitigated: GHCND takes precedence over hardcoded. |
| OKC | +3.0°F | 0.0°F | If OKC's true bias is positive (and Mar 27 was an anomaly), 0.0°F undercorrects. That's safer than the wrong-direction overcorrection we currently have. |

### Safeguard: GHCND always overrides hardcoded

The lookup order in `get_bias()` is:
1. Fresh daily cache (GHCND)
2. Refresh from NOAA API
3. Hardcoded fallback

The hardcoded value only matters when GHCND is unavailable. If GHCND starts returning valid data for Denver, it will override the +4.0°F hardcoded value automatically. The fix is a safety net, not a permanent override.

---

## 5. Implementation — Exact Changes

### Change 1: `ghcnd_client.py` — Update `HARDCODED_BIAS_F`

File: `agents/ruppert/data_analyst/ghcnd_client.py`  
Lines: ~73–93 (`HARDCODED_BIAS_F` dict)

```python
# BEFORE:
"KXHIGHDEN": 3.0,
"KXHIGHTOKC": 3.0,

# AFTER:
"KXHIGHDEN": 4.0,   # was 3.0 — conservative step toward observed +6°F (n=1 data)
"KXHIGHTOKC": 0.0,  # was 3.0 — REVERSED: observed error was -2°F; 0.0 is neutral pending more data
```

### Change 2: Investigate Denver GHCND cache

After updating the hardcoded value, run `ghcnd_client.py` standalone to check Denver's live GHCND result:

```bash
python agents/ruppert/data_analyst/ghcnd_client.py
```

Look for: `KXHIGHDEN: bias=+X.XX°F source=ghcnd` or `source=hardcoded_fallback`.

If source is still `ghcnd` and bias is near zero, the GHCND pipeline is computing near-zero for Denver's station. Likely cause: ERA5 elevation adjustment for Denver (5,280 ft MSL). Flag for Data Scientist.

### Change 3: Verify bias cache is invalidated after update

The bias cache (`logs/ghcnd_bias_cache.json`) has a `updated_date` field. If it was updated today before the code change, it will not refresh until tomorrow. Force a refresh:

```python
# Quick one-liner to clear the cache and force GHCND refresh:
from pathlib import Path
Path("logs/ghcnd_bias_cache.json").unlink(missing_ok=True)
```

Or simply wait for midnight UTC when the cache auto-refreshes.

---

## 6. What to Track Going Forward

### Data needed to make bias corrections reliable

Current state: n=1 observed settlement per city. After 5+ settlements per city, we can compute city-specific bias corrections with statistical confidence (±2°F at n=5, ±1°F at n=30).

| When | Action |
|------|--------|
| After 5 T-type or B-type settled trades per city | Run bias recalculation: compare `ttype_point_est_f` (from new T-type logging) vs actual settlement temp |
| After 20 T-type trades | Optimizer reviews margin tier win rates; retune `TTYPE_MARGIN_*` thresholds |
| After 30+ trades (any weather) | Full bias audit per city; promote empirical corrections to `HARDCODED_BIAS_F` as permanent replacements |

### Fields required in logger for bias analysis

- `ttype_point_est_f` (new, from T-type build) — the bias-corrected point estimate
- `ensemble_temp_forecast_f` — **currently null for all historical trades; must fix in next sprint**
- `bias_applied_f` — already logged ✓
- Settlement actual temperature — not currently in trade logs; may need post-settlement enrichment from NWS actuals

---

## 7. Summary of Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Denver hardcoded bias | **+4.0°F** (was +3.0°F) | Conservative step toward observed +6°F; GHCND override will self-correct when pipeline fixed |
| OKC hardcoded bias | **0.0°F** (was +3.0°F) | Observed error was -2°F; +3°F was backwards; neutral is safer than wrong direction |
| Global +2.7°F floor | **NO** | OKC and Chicago would be overcorrected; GHCND system handles eastern cities correctly already |
| GHCND Denver investigation | **YES — flag for Data Scientist** | Near-zero GHCND bias for high-altitude Denver is suspicious; likely ERA5 elevation issue |
| Expand corrections to other hardcoded cities | **NO — wait for data** | Only two cities have observed error data; don't guess for the rest |
| When to re-enable Denver trading | **After fixing hardcoded bias AND verifying GHCND result** | Both changes should be in place; Denver is currently in EXPANDED_CITIES_SKIP |
| When to re-enable OKC trading | **After 3+ more settlements confirm sign of bias** | n=1 with backwards sign is not enough; OKC stays in EXPANDED_CITIES_SKIP |

---

## 8. File Locations

| File | Change |
|------|--------|
| `agents/ruppert/data_analyst/ghcnd_client.py` | Update `HARDCODED_BIAS_F`: Denver +4.0, OKC 0.0 |
| `logs/ghcnd_bias_cache.json` | Delete to force refresh after code change |
| `agents/ruppert/data_scientist/logger.py` | Fix `ensemble_temp_forecast_f` null bug (separate ticket) |

---

*Strategist — 2026-03-30*
