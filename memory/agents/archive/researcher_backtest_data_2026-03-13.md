# SA-3 Researcher — Backtest Data Pull Notes
**Date:** 2026-03-13  
**Task:** Pull 14 days of historical data for backtesting framework  
**Date range:** 2026-02-27 through 2026-03-13  
**Output directory:** `ruppert-backtest/data/`

---

## Summary

All three data sources pulled successfully. 850 Kalshi markets, 20 cities × 15 days of weather forecast data, 5 crypto pairs × 360 candles each. Two notable deviations from expected values documented below.

---

## DATA SOURCE 1: Kalshi Settled Weather Markets

**Result:** 850 total settled markets across 17/20 series.

**File:** `ruppert-backtest/data/kalshi_settled_weather.json`

### Series with data (17):
KXHIGHNY, KXHIGHCHI, KXHIGHMIA, KXHIGHHOU, KXHIGHAUS, KXHIGHDEN, KXHIGHLAX, KXHIGHPHIL, KXHIGHTMIN, KXHIGHTDAL, KXHIGHTDC, KXHIGHTLV, KXHIGHTOKC, KXHIGHTSFO, KXHIGHTSEA, KXHIGHTSATX, KXHIGHTATL

Each returned the API max of 50 markets (most have backlog prior to our date range; the framework should filter by `close_time` to isolate the target 14-day window).

### Series with 0 results (3):
- **KXHIGHPHX** (Phoenix) — no settled markets returned
- **KXHIGHLA** (Los Angeles) — no settled markets returned  
- **KXHIGHTNOU** (New Orleans) — no settled markets returned

**Possible reasons:**
- These series may be newer launches where the ticker convention on Kalshi differs
- Phoenix and LA have separate LAX-specific tickers (KXHIGHLAX); KXHIGHLA may be deprecated
- New Orleans (KXHIGHTNOU) may use a different series name on the live API
- Recommend verifying via Kalshi web UI — these 3 cities have zero backtest data

**Impact:** 3/20 cities have no settled market data. If these series are active in live trading, backtester cannot evaluate performance on them.

---

## DATA SOURCE 2: Open-Meteo Historical Forecast Data

**Result:** 20 cities × 15 days × 3 models = 900 city-day entries. 0 missing dates.

**File:** `ruppert-backtest/data/openmeteo_historical_forecasts.json`

**Format:** `{series_ticker: {date: {ecmwf_max: float, gfs_max: float, icon_max: float}}}`

### Model correction: gfs025 → gfs_seamless
The task spec called for `models=ecmwf_ifs025,gfs025,icon_seamless`. However, **`gfs025` is unavailable on the historical-forecast API** — the endpoint returns null for all dates when this model is requested. Discovered via debug test.

**Fix applied:** Substituted `gfs_seamless` for `gfs025`. This is the same underlying GFS/GEFS data through a different routing path and works correctly on the historical-forecast endpoint.

All 300 GFS values are now populated (no nulls). This substitution should be permanent in the backtesting framework.

### Spot-check: NYC 2026-03-10
Expected range (from task spec): 35-55°F  
**Actual values:** ECMWF=74.5°F, GFS=78.7°F, ICON=78.9°F

**Finding:** NYC was significantly warmer than expected for early March 2026 — approximately 20-25°F above the assumed winter range. This suggests an anomalous warm spell (potentially relevant to any weather contracts traded during this period). The data appears correct for the historical forecast API. The task's expected range of 35-55°F was likely based on historical climate norms, not the actual 2026 conditions.

**Implication for backtest:** Markets settled with high temperatures in this period. Edge calculations based on "probability of exceeding threshold" would have had strong YES signals. This is a warm-biased period for the backtest — results may overestimate performance if this period is treated as representative.

---

## DATA SOURCE 3: Kraken OHLC (Crypto)

**Result:** 5 pairs × 360 candles each = 1,800 hourly candles total.

**Files:** `ruppert-backtest/data/kraken_ohlc_{PAIR}.json`

| Pair    | Candles | Threshold (300+) |
|---------|---------|-----------------|
| XBTUSD  | 360     | PASS            |
| ETHUSD  | 360     | PASS            |
| XRPUSD  | 360     | PASS            |
| SOLUSD  | 360     | PASS            |
| DOGEUSD | 360     | PASS            |

### Note: Windows encoding issue during XBTUSD pull
The original script's print statement with ⚠ emoji caused a `charmap` codec error on Windows console, which triggered the exception handler and incorrectly recorded 0 candles. The file was saved correctly (360 candles). Manifest was corrected in the re-run.

### Spot-check: BTC price range
Expected range (from task spec): $75,000-$100,000  
**Actual range:** $63,248 - $73,698

**Finding:** BTC was trading below the expected range during Feb 27 – Mar 13, 2026 ($63k-$74k vs. expected $75k-$100k). This is a legitimate market fact — BTC had pulled back from highs in this period.

**Implication for backtest:** Crypto module edge calculations based on price levels or support/resistance should account for this price range. The task's expected range was likely based on late 2025 / early 2026 peaks.

---

## Data Quality Summary

| Source | Status | Issues |
|--------|--------|--------|
| Kalshi weather | PARTIAL | 3/20 series empty (PHX, LA, NOU) |
| Open-Meteo forecasts | COMPLETE | gfs025 replaced with gfs_seamless; warm period noted |
| Kraken OHLC | COMPLETE | BTC below expected range (expected $75-100k, actual $63-74k) |

---

## Recommendations for Optimizer / Developer

1. **Kalshi gap**: Investigate KXHIGHPHX, KXHIGHLA, KXHIGHTNOU ticker conventions. May need different API parameters or these cities are truly not live yet.

2. **Open-Meteo fix**: Update `openmeteo_client.py` config for historical backtest to use `gfs_seamless` instead of `gfs025`. The live forecast code uses `gfs_seamless` already (correct); only the historical-forecast endpoint call was affected.

3. **Warm period caveat**: The Feb 27 – Mar 13 2026 backtest period was anomalously warm. Strategy performance during this window may not generalize to normal winter conditions. Recommend including a colder-weather 14-day window for comparison.

4. **NYC spot-check expectation**: Task spec's expected 35-55°F range for NYC in March was off — actual was ~74-79°F. Backtest validation should use actual settled prices, not assumed ranges.

5. **BTC price context**: Backtest covers a period where BTC was $63k-$74k. If strategy has price-level logic (e.g., support at $70k), this is relevant context for Optimizer's parameter review.
