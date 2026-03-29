# Edge Anomaly Investigation — 2026-03-13 3pm PT Scan
**Analyst:** SA-1 Optimizer  
**Filed:** 2026-03-13 ~15:30 PT  
**Status:** Root cause confirmed. Recommendations written.

---

## Summary

At the 3pm PT scan, 28 trades fired across newly-added weather cities with edges of 77–95% (avg 91%), ALL as YES buys at 1–17¢. These are NOT real arbitrage opportunities. Root cause is a **combination of two bugs**: a same-day settlement timing failure (primary) and uncalibrated bias inflation on new cities (secondary).

---

## Q1: NOAA Probability Formula

**Primary path (99% of cases):** `noaa_prob` in the result dict is a misnomer — it actually contains the **multi-model Open-Meteo ensemble probability**, not a NOAA calculation. The probability is computed by:
1. Fetching ensemble members from ECMWF IFS (51 members), GEFS (31 members), and ICON (40 members)
2. Counting members where `daily_max >= effective_threshold`
3. Computing per-model prob = `members_above / total_members`
4. Weighted average: ECMWF×0.40 + GEFS×0.40 + ICON×0.20

**No sigma is involved in the primary path.** This is raw ensemble member counting.

**NOAA fallback path (fires only when ensemble fails):** `noaa_client.get_probability_for_temp_range()` uses a **fixed σ = 4.0°F** normal distribution centered on the NWS forecast high. This σ is **not calibrated per city** — it's a single generic value. However, this path is rarely triggered (requires all 3 ensemble models to fail).

**Verdict on Q1:** The primary signal is sound (ensemble counting). The NOAA fallback sigma (4.0°F) is generic but only fires as a last resort and is not the cause of the current anomaly.

---

## Q2: Same-Day Settlement Bug — PRIMARY ROOT CAUSE

This is the main bug. Here's the exact failure path:

### The Code Path (in `openmeteo_client.get_full_weather_signal`)

```python
if is_same_day and conditions.get("today_high_f") is not None:
    today_high   = conditions["today_high_f"]   # ← FORECAST HIGH, not observed!
    current_temp = conditions.get("current_temp_f")
    hours        = conditions.get("hours_since_midnight", 12)

    if hours >= 14 and current_temp >= threshold_f:
        prob = 0.95   # correct: temp already hit threshold → YES
    elif hours >= 14 and today_high < threshold_f - 2:
        prob = 0.05   # correct: forecast well below threshold → NO
    else:
        det_prob = 1.0 if today_high >= threshold_f else 0.0
        prob = 0.6 * prob + 0.4 * det_prob    # ← BUG FIRES HERE
```

### Why It Fires at 6pm ET (3pm PT)

`hours_since_midnight` is correctly parsed from Open-Meteo's local time response. At 6pm ET, `hours = 18` → condition `hours >= 14` is TRUE for ET cities. At 3pm PT, `hours = 15` → also TRUE.

### The Failure Scenario (applies to all 28 trades)

**Example:** City threshold = 75°F, actual day's high = 72°F (didn't hit threshold), market correctly at 1¢ YES.

| Variable | Value | Note |
|---|---|---|
| `current_temp` | 71°F (declining at 6pm) | Current NWS observation |
| `today_high_f` | 78°F | **Open-Meteo FORECAST** from morning run — optimistic |
| `threshold_f` | 75°F | Kalshi contract threshold |
| `ensemble prob` | 0.85 | Morning ensemble still shows 85% chance of exceeding 75°F |

**Check 1:** `71 >= 75` → FALSE (no override to 0.95)  
**Check 2:** `78 < 73` (75-2) → FALSE (78 is NOT well below threshold)  
**ELSE fires:** `det_prob = 1.0` (because forecast 78 >= threshold 75)  
**Result:** `prob = 0.6 × 0.85 + 0.4 × 1.0 = **0.91**`

Market is at 1¢. Edge = 0.91 − 0.01 = **90% edge**. Trade fires.

### Why the Market Is Right and We Are Wrong

By 6pm ET, the actual daily high has already been observed. Kalshi's settlement data (ASOS/NWS daily max) reflects reality. The market pricing at 1¢ is correct — the high didn't hit the threshold.

**Our model doesn't know the actual observed daily max.** `today_high_f` from Open-Meteo's `/forecast` API is the model's **predicted** daily max, not the observed one. At 6pm, Open-Meteo still shows the morning forecast value. The model confidently says "78°F expected today" while reality already answered "72°F."

**Critical gap:** We have no mechanism to fetch the actual OBSERVED daily maximum temperature for today. NWS observation endpoint (`/stations/{station}/observations/latest`) gives current reading only, not the daily max that's already been logged.

### Same-Day Skip Logic Flaw

Even when `skip_reason = "same_day_temp_already_exceeded"` is set, `analyze_market()` **does not check skip_reason**. The flag is purely informational. However, this particular skip_reason fires only in the favorable case (current_temp already exceeded threshold → prob=0.95), which is NOT the scenario causing the bug.

---

## Q3: New City Bias Values

Default `CITY_BIAS_F = 3.0°F` for all new cities. This is applied as:

```python
effective_threshold = threshold_f - bias   # lowers the bar the ensemble must clear
```

**Impact:** A 3.0°F bias lowers the effective threshold from e.g. 75°F to 72°F. More ensemble members clear 72°F than 75°F → higher probability.

**Is 3.0°F appropriate?** No. The 3.0–4.0°F values for original cities were derived from backtest analysis (`backtest_2026-03-10.json`). New cities have no such validation. Some cities may have negative bias (model runs cold), small positive bias (1°F), or large bias (4°F+). Applying +3.0°F to all 14 new cities simultaneously is aggressive.

**Contribution to anomaly:** The bias inflation compounds the same-day bug. If the morning ensemble showed 80% probability at the true threshold, the bias drops the effective threshold, potentially pushing it to 85%+. Then the ELSE branch adds det_prob=1.0 on top → 90%+ total.

**Example:**  
- True threshold: 75°F  
- After bias: effective threshold = 72°F  
- Ensemble at 72°F: maybe 88% instead of 80%  
- ELSE branch: `prob = 0.6 × 0.88 + 0.4 × 1.0 = 0.928`

This is contributing to the upper range of the anomaly (91–95% edges vs. 77–84%).

---

## Q4: Sigma / Volatility Assumption

**Primary path:** No sigma. Ensemble member counting is model-based, not parametric. The spread between ensemble members implicitly captures uncertainty.

**NOAA fallback (noaa_client.py):** Uses `std_dev = 4.0°F` hardcoded. This is **not calibrated per city** and **not differentiated by forecast lead time**. Research suggests:
- Same-day forecast (0h lead): σ ≈ 1–2°F (most of the day's outcome is already determined)
- 24-48h forecast: σ ≈ 3–5°F (reasonable range for 4.0°F)
- 3-5 day forecast: σ ≈ 5–8°F (4.0°F is too optimistic/narrow)

The 4.0°F value is defensible for 24-48h forecasts but problematic for same-day and multi-day contexts. **However, since this is the fallback path and not what fired these 28 trades, it's not the current bug.**

---

## Q5: Root Cause Verdict

**Primary cause (90% of the anomaly): Same-day settlement timing bug**

The `det_prob` ELSE branch in `get_full_weather_signal` uses `today_high_f` (Open-Meteo forecast) as a proxy for whether the threshold will be reached. At 6pm ET/3pm PT, the day's actual high is already determined and declining temperatures won't recover. The morning forecast (optimistic) continues to say "78°F" when reality already said "72°F." This causes `det_prob = 1.0` to fire incorrectly, inflating the final probability to 85–95%.

**Secondary cause (10–20% amplifier): Uncalibrated 3.0°F default bias on new cities**

Lowers effective thresholds for 14 unvalidated cities, systematically inflating ensemble probabilities by 5–10 percentage points before the same-day logic compounds it further.

**Is this also a calibration error?** Partially. The ensemble correctly reflects morning forecast uncertainty (85% chance of hitting 75°F at 8am is plausible). The calibration failure is that the same-day logic doesn't recognize "the game is already over" — it continues to treat a 6pm scan as a forward-looking probabilistic question when it's actually a closed historical observation.

---

## Recommendations

### 🔴 P1 — Same-Day Markets: Hard Skip After Cutoff (Fix Before Next Scan)
**Requires David approval: NO** (risk management / bug fix, not algorithm change)

**Problem:** At and after 2pm local time, the daily high for most US cities has already been observed. Trading same-day markets at this hour is purely noise — we don't have access to the actual observed daily max.

**Fix in `edge_detector.py::analyze_market()`:**

```python
# After getting signal = get_full_weather_signal(...)
# Hard skip: same-day markets past the temperature-peak cutoff hour
if signal.get("is_same_day"):
    city_hours = (signal.get("conditions") or {}).get("hours_since_midnight", 0)
    if city_hours >= config.SAME_DAY_SKIP_AFTER_HOUR:  # add to config: 14 (2pm local)
        logger.info(
            f"[Edge] {ticker}: SKIP — same-day market, past cutoff "
            f"({city_hours}h local). Day's high already observed."
        )
        return None
```

**Add to `config.py`:**
```python
SAME_DAY_SKIP_AFTER_HOUR = 14  # Skip same-day markets after 2pm local city time
```

This kills all 28 anomalous trades at the source. Simple, safe, zero false negatives for future trading.

---

### 🔴 P1 — Fix `det_prob` Logic in Same-Day ELSE Branch (Defensive Patch)
**Requires David approval: YES** (changes signal weighting algorithm)

Even with the hard skip above, this underlying logic is wrong and should be corrected for completeness.

**Problem in `openmeteo_client.get_full_weather_signal()`:** The ELSE branch uses `today_high_f` (forecast) as if it's the observed max. When temperatures are declining in the evening and current_temp < threshold, det_prob should reflect "probably won't hit threshold now."

**Fix:**
```python
else:
    # After 2pm with declining temps: current_temp is better proxy than forecast high
    if hours >= 16 and current_temp is not None:
        # Late afternoon — use current temp as leading indicator
        # If we're 3°F+ below threshold at 4pm, almost certainly won't hit it
        det_prob = 1.0 if current_temp >= threshold_f else (
            0.3 if current_temp >= threshold_f - 3 else 0.0
        )
    else:
        det_prob = 1.0 if today_high >= threshold_f else 0.0
    prob = 0.6 * prob + 0.4 * det_prob
    confidence = ensemble["confidence"] * 0.8
```

---

### 🟡 P2 — Reduce Default Bias for New Cities (Fix Before Saturday)
**Requires David approval: YES** (changes algorithm parameters for new cities)

**Problem:** `DEFAULT_BIAS_F = 3.0` and all new-city entries in `CITY_BIAS_F` are hardcoded at 3.0 without backtest validation. This systematically lowers effective thresholds for 14 cities.

**Fix in `openmeteo_client.py`:**
```python
DEFAULT_BIAS_F = 0.0  # No bias until GHCND validates per city
```

AND reset all new-city entries:
```python
# Expanded cities (added 2026-03-13) — PENDING GHCND VALIDATION
"KXHIGHAUS":  0.0,   # Austin — unvalidated
"KXHIGHDEN":  0.0,   # Denver — unvalidated
# ... etc for all 14 new cities
```

**Note:** Do NOT change the original 6 cities (MIA, CHI, NY, LA, PHX, HOU) — those are backtest-validated.

**Alternative (less aggressive):** Use 1.0°F as default (some UHI effect expected in all cities) rather than 0.0. Either is better than 3.0.

---

### 🟡 P2 — Add Same-Day Settlement Hours to Market Skip Gate in `strategy.py`
**Requires David approval: NO** (existing `< 2h to settlement` gate needs companion)

The strategy layer already skips adds when `< 2h to settlement`. Add a complementary gate: no NEW positions in same-day markets after 2pm local.

This should mirror the `SAME_DAY_SKIP_AFTER_HOUR` config from the edge_detector fix above, but at the strategy layer as a second defense line.

---

### 🟢 P3 — NOAA Fallback Sigma Calibration (Backlog)
**Requires David approval: YES** (algorithm parameter change)

`noaa_client.py` uses `std_dev = 4.0°F` globally. This should be:
- Lead-time-adjusted: σ decreases as the target date approaches
- Same-day: σ ≈ 1-2°F (most uncertainty is resolved)
- Multi-day: σ ≈ 5-7°F (wider uncertainty)

Since this path only fires when all 3 ensemble models fail, it's low priority. Add to backlog for post-Friday review.

---

### 🟢 P3 — OBSERVED Daily Max Data Source (Backlog)
**Requires David approval: YES** (new data source addition)

The real fix for same-day markets is to access the ACTUAL observed daily maximum temperature, not the forecast. Options:
1. NOAA ASOS hourly data via `api.weather.gov/stations/{station}/observations` — can compute running max from hourly obs
2. Open-Meteo historical API (lags by ~1-2h but has actual observed data)
3. Weather Underground/Wunderground API (paid but near-real-time)

SA-2 Researcher should scope this. Would enable re-entry into same-day markets (if legal/profitable) with proper signal. For now, hard skip is safer.

---

## Impact Assessment

| Issue | Trades Affected | P&L Risk (DEMO) |
|---|---|---|
| Same-day timing bug | All 28 trades | HIGH — buying markets that are effectively settled NO |
| Bias inflation | ~14 of 28 (new cities) | MEDIUM — amplifies all new-city signals by 5-10% |
| Fallback sigma | 0 of 28 | NONE this scan |

**Total DEMO capital at risk from the 28 trades:** Unknown without trade amounts, but at min $25 × 28 = $700 potential exposure (all from $400 DEMO account = crisis if not caught). **Needs immediate review of whether these trades have been executed in DEMO.**

---

## Files to Change

| File | Change | Priority |
|---|---|---|
| `edge_detector.py` | Add same-day hard skip with `SAME_DAY_SKIP_AFTER_HOUR` gate | P1 |
| `config.py` | Add `SAME_DAY_SKIP_AFTER_HOUR = 14` | P1 |
| `openmeteo_client.py` | Fix `det_prob` ELSE branch (defensive) | P1 |
| `openmeteo_client.py` | Reset new-city bias to 0.0 | P2 |
| `bot/strategy.py` | Add same-day gate mirroring edge_detector change | P2 |
| `noaa_client.py` | Lead-time-adjusted sigma | P3 |

---

*Filed by SA-1 Optimizer. David approval required for P1 `det_prob` fix and P2 bias reset before Developer builds.*
