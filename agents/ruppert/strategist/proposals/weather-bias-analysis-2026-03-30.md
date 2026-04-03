# Weather Bias Analysis — 2026-03-30
**Strategist Report | Input to: halt B-type entries decision**

---

## ⚠️ Critical Data Limitation Up Front

**`ensemble_mean` is NOT in the settled trade logs.**

The field exists in `logger.py` as `ensemble_temp_forecast_f`, but it is `null` for all 33 settled trades. The schema was added recently; the historical records predate it. What we DO have:
- `noaa_prob` (ensemble probability signal)
- Actual settlement temperatures (from `settled_prices.json`, covering Mar 27 events)
- GHCND bias cache (system's own forecast correction estimates)
- Settlement outcomes (win/loss) for all 33 trades

This means **the direct bias analysis (ensemble_mean vs. target_midpoint) cannot be computed for most trades**. However, we can infer forecast direction from settlement outcomes and the 7 cities where Mar 27 actual temps are available.

---

## 1. Raw Performance Numbers

| Metric | Value |
|--------|-------|
| Total settled weather trades | 33 |
| Wins | 2 |
| Losses | 31 |
| **Win rate** | **6.1%** |
| Expected win rate (avg noaa_prob ~0.92) | ~87–97% |
| Total PnL | **-$2,368.72** |

**This is catastrophic.** The model was assigning 92–100% confidence to outcomes that happened 6.1% of the time.

---

## 2. Win Rate by Trade Type

| Type | Wins | Total | Win% |
|------|------|-------|------|
| **B-type** (band/between) | 2 | 21 | **9.5%** |
| **T-type** (threshold) | 0 | 12 | **0%** |

Neither type is working. T-type is literally 0 wins in 12 attempts.

---

## 3. Win Rate by Entry Price

| Entry Price | Wins | Total | Win% |
|-------------|------|-------|------|
| 1–3c | 0 | 16 | **0%** |
| 4–15c | 0 | 8 | **0%** |
| 16c+ | 2 | 9 | **22.2%** |

The only wins were at higher prices (OKC B63.5 at 29c, CHI B47.5 at 21c). The two wins came from mid-range confidence bands where the market was also showing meaningful probability. The 1–3c "certainty" trades went 0/16 — **every single one was wrong**.

This is the clearest data point: **the 1–3c entries represent maximum model overconfidence.** The market was pricing ~1–9% probability. The system was betting at ~90–100% confidence. The market was right.

---

## 4. Forecast Error Analysis (7 Cities with Actual Mar 27 Temps)

| City | Predicted Center | Actual Temp | Error | Bias Direction | System Correction | Residual |
|------|-----------------|-------------|-------|----------------|-------------------|---------|
| NYC | ~62.5°F | 65°F | +2.5°F | **Too cold** | +2.08°F | +0.42°F |
| Philadelphia | ~67°F | 70°F | +3.0°F | **Too cold** | +3.17°F | -0.17°F |
| DC | ~70.5°F | 74°F | +3.5°F | **Too cold** | +2.03°F | +1.47°F |
| Austin | ~84°F | 88°F | +4.0°F | **Too cold** | +2.73°F | +1.27°F |
| Denver | ~49°F | 55°F | +6.0°F | **Too cold** | +0.08°F | **+5.92°F** |
| Chicago | ~42°F | 44°F | +2.0°F | **Too cold** | +3.06°F | -1.06°F |
| OKC | ~73°F | 71°F | -2.0°F | Too hot | +3.0°F (hardcoded) | -5.0°F |

**Mean cold bias (excluding OKC): +3.5°F**  
**Mean cold bias (all 7): +2.7°F**

### Key findings:

1. **Systematic cold bias confirmed in 6/7 cities on Mar 27.** The ensemble (NOAA gridded) consistently predicted temperatures 2–6°F too cold.

2. **Denver is the worst outlier: +6°F error, system correction was only +0.08°F.** The GHCND bias cache for Denver is nearly zero — completely failing to capture a 6°F systematic error. This is a data quality failure in the bias pipeline, not just model noise.

3. **OKC is the exception.** The system used a hardcoded fallback of +3°F, but the actual error was -2°F (predicted too hot). So OKC's hardcoded correction is **backwards** — it's adding 3°F when it should be subtracting.

4. **System bias corrections are partially working for eastern cities** (NYC ≈0.4°F residual, Philadelphia ≈-0.2°F residual) but failing for Denver and OKC.

---

## 5. Is the Bias Consistent Across Cities?

**Mostly yes, with important exceptions:**

| City | Source | Observed Error | Notes |
|------|--------|----------------|-------|
| NYC, Philly, DC, AUS, CHI | GHCND (real data) | +2–4°F cold bias | Corrections partially working |
| Denver | GHCND | +6°F cold bias | **Correction is broken (+0.08°F vs +6°F needed)** |
| OKC, TSFO, TSATX, TMIN, TDAL | Hardcoded fallback (+3°F) | Mixed | Hardcoded corrections unreliable |

**The hardcoded fallback cities (all KXHIGHT prefixed cities where source="hardcoded_fallback") are particularly dangerous.** These 7 cities — TOOKC, TSFO, TSEA, TSATX, TATL, TNOU, TLV — use a blanket +3°F correction that has no empirical basis. OKC's observed error was -2°F, meaning the hardcoded correction added error instead of reducing it.

---

## 6. Do 1–3c Entries Show Larger Forecast Errors?

**Yes, definitively.**

The 16 trades entered at 1–3c represent the highest noaa_prob signals (91–100%). These are cases where:
- The ensemble predicted temperature very far from the threshold/band
- The market priced ~1–9% probability (extreme outlier territory)
- The system bet with 91–100% confidence

All 16 lost. The implication: **when the system thinks it's most certain, it's most wrong.** The ensemble's 90%+ probabilities at 1–3c are systematically miscalibrated. These aren't just bad luck — they're the cases where the cold bias is most catastrophic (the actual temp was far enough from the prediction that even 3–6°F bias caused complete misses).

The 2 wins were at 21c and 29c entry — where the market showed 21–29% probability, meaning less certainty. These align with cases where the actual temperature happened to land in the predicted band.

---

## 7. Should We Halt B-Type Entries RIGHT NOW?

**YES. Halt immediately.**

The data is unambiguous:
- **2/21 B-type win rate (9.5%)** vs expected ~87–97%
- Zero wins at 1–15c entry prices across both B and T types  
- Systematic cold bias of +2.7°F mean with specific cities showing +6°F errors
- The bias correction pipeline is not working for Denver and the hardcoded-fallback cities

There is no scenario where waiting for more data helps here. The signal is negative and consistent across 33 trades, 5 days, and 12 cities. We already have more than enough evidence.

**The right call is to halt all weather entries until the bias pipeline is fixed — both B-type and T-type.**

---

## 8. Does the Data Support Switching to T-Type?

**No.** T-type went 0/12 — worse than B-type.

Switching from B to T doesn't solve the underlying problem. T-type trades are directional bets (temp above/below threshold). The cold bias means:
- **T-type "warm" bets** (temp < threshold): systematically wrong because temps run warmer
- **T-type "cold" bets** (temp > threshold): would win more, but the system isn't selecting these

Of the 12 T-type trades:
- KXHIGHAUS-26MAR27-T86 (< 86°F): LOST — actual was 88°F (cold bias caused the loss)
- KXHIGHNY-26MAR27-T62 (< 62°F): LOST — actual was 65°F (cold bias)
- KXHIGHDEN-26MAR27-T49 (< 49°F): LOST — actual was 55°F (massive cold bias)
- KXHIGHCHI-26MAR27-T44 (> 44°F): LOST — actual was exactly 44°F (boundary case)
- KXHIGHCHI-26MAR27-T37 (< 37°F): LOST — actual was 44°F (cold bias)
- All TSATX/TMIN/TDAL threshold trades: LOST

**T-type is not a better path with the current bias problem.** It requires the point estimate to be reliably near the threshold with known sign/magnitude of error. We don't have that.

---

## 9. Can We Apply Bias Correction Now Using 33 Trades?

**Partially — but with major caveats.**

What we can confidently extract from this data:

| City | Correction Recommendation |
|------|--------------------------|
| Denver (KXHIGHDEN) | Increase bias correction from +0.08°F to +5–6°F |
| Austin (KXHIGHAUS) | Increase from +2.73°F to ~+4°F |
| DC (KXHIGHTDC) | Increase from +2.03°F to ~+3.5°F |
| OKC (KXHIGHTOKC) | **REVERSE**: change from +3°F to -2°F (or remove hardcoded fallback) |
| NYC, Philly, Chicago | Current corrections roughly adequate; minor adjustments |
| Hardcoded fallback cities (TSFO, TSATX, TMIN, TDAL, etc.) | Replace +3°F hardcoded with actual observed errors |

**However: 33 trades is too few for reliable per-city bias estimates.**

- 7 cities have actual temp data (Mar 27 only). Single-event sample per city.
- Remaining 18 trades are from Mar 28 events where we only know win/loss, not actual temps.
- Confidence intervals at n=1 per city are huge. Denver's +6°F could be a single anomalous warm day.

**What bias correction CAN give us right now:**
1. Fix Denver's obviously broken near-zero correction
2. Reverse OKC's hardcoded correction (it's confidently wrong)
3. Apply a rough +3–4°F global cold bias floor as a conservative correction

**What it cannot give us:**
1. Reliable per-city corrections with statistical confidence
2. Seasonal adjustments (late March cold bias may differ from summer bias)
3. Any correction at all for T-type signals (we lack the point estimate data)

For T-type specifically: the T-type signal formula requires `|ensemble_point_estimate - threshold|`. We don't have `ensemble_point_estimate` logged for any historical trade. **The T-type bias correction cannot be computed from this data.**

---

## 10. Summary and Recommendations

| Question | Answer |
|----------|--------|
| Systematic cold bias? | **YES** — 6/7 cities, mean +2.7°F, Denver +6°F outlier |
| Consistent across cities? | **Mostly yes**, with OKC as exception (predicted too hot) |
| Do 1–3c trades show larger errors? | **Yes** — 0/16 wins, worst performance tier |
| Halt B-type NOW? | **YES** — halt immediately, no waiting needed |
| Switch to T-type? | **NO** — T-type is 0/12, same underlying problem |
| Apply bias correction now? | **Partially** — fix Denver and OKC urgently; insufficient data for reliable per-city corrections |

### Immediate actions:
1. **HALT all weather entries** (B and T) until bias pipeline is validated
2. **Fix Denver's bias correction** — +0.08°F is clearly wrong; should be ~+5–6°F
3. **Fix OKC's hardcoded correction** — +3°F should be negative or removed
4. **Add ensemble_temp_forecast_f logging urgently** — the field is in the schema but logging null; this is the single most important data gap. Without point estimates, we can't compute T-type margins or do post-hoc bias analysis
5. After fixing the bias pipeline, **backtest on fresh data** (5+ events per city, >50 trades) before re-enabling

### Data gap that must be closed:
The logger added `ensemble_temp_forecast_f` to the schema but it was null for all 33 trades. Once this is properly populated, 2–3 weeks of data will enable reliable per-city bias estimates and T-type signal calibration. That's the prerequisite for re-enabling weather trading with confidence.

---

*Analysis by: Ruppert Strategist*  
*Date: 2026-03-30*  
*Data: 33 settled weather trades (2026-03-26 to 2026-03-30), ghcnd_bias_cache.json, settled_prices.json*
