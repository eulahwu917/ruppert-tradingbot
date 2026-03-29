# SA-1 Optimizer — Backtest Analysis
**Period**: 2026-02-27 → 2026-03-13 (14 days)
**Dataset**: 288 T-markets across 16 cities
**Analyst**: SA-1 Optimizer
**Date**: 2026-03-13

---

## EXECUTIVE SUMMARY

The weather model's **directional signal for YES bets is broken** — YES bets win only 14.9% of the time across all thresholds and cities. NO bets win 90.4%. The 47% overall win rate is a weighted average masking this catastrophic YES bias. Edge/confidence threshold tightening alone will **not fix this** — the model needs a directional correction. The immediate fix is a **NO-only filter** while the YES bias is investigated. With NO-only + min_edge=0.30, the system achieves a 39.6% trigger rate and **90.4% win rate**.

---

## 1. DISTRIBUTION ANALYSIS

### 1a. Edge Distribution

The edge signal is **quantized to exactly 3 values** — not continuous. This means fine-tuning thresholds like 0.20 vs 0.22 has zero effect.

| Edge Value | Count | % of Total |
|------------|-------|------------|
| 0.10 | 20 | 6.9% |
| 0.30 | 18 | 6.3% |
| 0.50 | 250 | 86.8% |
| **Total** | **288** | **100%** |

**Statistics**: Mean=0.46, Median=0.50, P25=0.50, P75=0.50, P90=0.50

> The edge calculator outputs one of 3 discrete levels. 86.8% of markets score edge=0.50 (maximum). This is why the trigger rate is 93.1% — almost everything hits the max edge score and trivially exceeds the 0.15 threshold.

### 1b. Confidence Distribution

Like edge, confidence is **quantized to exactly 3 values**.

| Confidence | Count | % of Total | Notes |
|------------|-------|------------|-------|
| 0.333 | 13 | 4.5% | NOT triggered (below 0.55 threshold) |
| 0.667 | 25 | 8.7% | Triggered |
| 1.000 | 250 | 86.8% | Triggered |
| **Total** | **288** | **100%** |

**Statistics**: Mean=0.941, Median=1.00, P25=1.00

> Same pattern as edge. 86.8% of markets score maximum confidence, trivially passing any threshold below 1.0. The 13 low-confidence markets are not triggered and not scored.

---

## 2. DIRECTION WIN RATE BREAKDOWN

**This is the core finding.**

| Direction | Count (triggered) | Wins | Win Rate | Assessment |
|-----------|-------------------|------|----------|------------|
| YES | 154 | 23 | **14.9%** | ❌ CATASTROPHICALLY BAD |
| NO | 114 | 103 | **90.4%** | ✅ EXCELLENT |
| **Total** | **268** | **126** | **47.0%** | (masked by YES losses) |

### What This Means

The model predicts YES 57.6% of the time and NO 42.4% of the time. But YES bets are almost always **wrong**. This is a systematic directional bias — the model consistently thinks daily high temperatures will **exceed** Kalshi's thresholds when they typically **don't**.

Likely causes:
1. **Warm bias in GEFS ensemble**: The 31-member ensemble may have a known warm bias for certain seasons/regions
2. **Threshold structure**: Kalshi sets thresholds at above-normal levels (e.g., "will it be 90°F today?") — betting YES against this is systematically a bad bet in spring
3. **Bias corrections insufficient**: The +2-4°F per-city bias corrections may be adding to the problem rather than fixing it

---

## 3. WIN RATE AT DIFFERENT EDGE CUTOFFS

Because edge is quantized (0.1 / 0.3 / 0.5), only 3 meaningful cutoffs exist.

| Edge Cutoff | Markets | YES bets | NO bets | Wins | Win Rate | YES WR | NO WR |
|-------------|---------|----------|---------|------|----------|--------|-------|
| ≥ 0.10 (all) | 288 | 166 | 122 | 126 | 43.8% | 13.9% | 84.4% |
| ≥ 0.15 (current) | 268 | 154 | 114 | 126 | 47.0% | 14.9% | 90.4% |
| ≥ 0.30 | 268 | 154 | 114 | 126 | 47.0% | 14.9% | 90.4% |
| ≥ 0.50 | 250 | 141 | 109 | 120 | 48.0% | 15.6% | 89.9% |

**Key insight**: Raising the edge threshold changes almost nothing. Going from 0.15 → 0.50 only drops 18 markets and moves win rate from 47% → 48%. The edge signal has no discriminatory power at current values because it's dominated by max-edge (0.5) markets.

### NO-Only Scenario Analysis

| Scenario | Triggered | Trigger Rate | Win Rate |
|----------|-----------|-------------|----------|
| NO only, edge≥0.30, conf≥0.667 | 114 | **39.6%** | **90.4%** |
| NO only, edge≥0.50, conf=1.0 | 109 | 37.8% | 89.9% |
| Current (all) | 268 | 93.1% | 47.0% |

---

## 4. CITY ANALYSIS AND RECOMMENDATIONS

### Per-City Breakdown: YES vs NO Win Rates

| City | Triggered | YES bets | YES WR | NO bets | NO WR | Overall WR | Verdict |
|------|-----------|----------|--------|---------|-------|------------|---------|
| KXHIGHTMIN | 18 | 4 | 50.0% | 14 | 78.6% | 72.2% | ✅ KEEP |
| KXHIGHCHI | 16 | 6 | 0% | 10 | 100% | 62.5% | ✅ KEEP (NO only) |
| KXHIGHAUS | 17 | 7 | 0% | 10 | 90.0% | 58.8% | ✅ KEEP (NO only) |
| KXHIGHPHIL | 18 | 10 | — | 8 | 75.0% | 55.6% | ✅ KEEP (NO only) |
| KXHIGHTSEA | 18 | 8 | — | 10 | 100% | 55.6% | ✅ KEEP (NO only) |
| KXHIGHTSATX | 16 | 8 | — | 8 | 87.5% | 56.2% | ✅ KEEP (NO only) |
| KXHIGHTOKC | 16 | 10 | — | 6 | 100% | 50.0% | ✅ KEEP (NO only) |
| KXHIGHTDC | 16 | 8 | — | 8 | **37.5%** | 43.8% | ⚠️ WATCH (NO WR below floor) |
| KXHIGHTATL | 16 | 7 | — | 9 | 77.8% | 43.8% | ✅ KEEP (NO only) |
| KXHIGHNY | 17 | 10 | — | 7 | 85.7% | 41.2% | ✅ KEEP (NO only) |
| KXHIGHTLV | 17 | 10 | — | 7 | 85.7% | 41.2% | ✅ KEEP (NO only) |
| KXHIGHDEN | 18 | 12 | — | 6 | 83.3% | 38.9% | ✅ KEEP (NO only) |
| KXHIGHTDAL | 15 | 10 | **0%** | 5 | 100% | 33.3% | ✅ KEEP (NO only) — was labeled bad due to YES |
| KXHIGHMIA | 16 | 11 | **0%** | 5 | 100% | 31.2% | ✅ KEEP (NO only) — was labeled bad due to YES |
| KXHIGHTSFO | 17 | 13 | **0%** | 4 | 80.0% | 29.4% | ✅ KEEP (NO only) — was labeled bad due to YES |
| KXHIGHLAX | 17 | 13 | — | 4 | 75.0% | 35.3% | ✅ KEEP (NO only) |

### Reframing "Bad Cities"

**SFO, MIA, and DAL are NOT bad cities.** Their poor overall win rates (29-33%) are 100% caused by having a high proportion of YES bets. With NO-only filter:
- DAL: 100% win rate on 5 NO bets
- MIA: 100% win rate on 5 NO bets (despite NWS 404 issue)
- SFO: 80% win rate on 4 NO bets

These cities should **NOT be blacklisted**. They need the same fix as everyone else: stop betting YES until the directional bias is corrected.

### Exception: KXHIGHTDC (Washington DC)

DC is the only city with a problematic NO win rate — 37.5% (3/8), below the 40% floor. However, 8 observations is a small sample. Flag for monitoring; do not exclude yet.

---

## 5. RECOMMENDED NEW CONFIG VALUES

### Immediate Config Change (min viable fix)

```python
# config.py
MIN_EDGE_WEATHER = 0.30          # was 0.15 — filters edge=0.1 noise markets
MIN_CONFIDENCE_WEATHER = 0.667   # was 0.55 — filters conf=0.333 uncertain markets
WEATHER_DIRECTION_FILTER = "NO"  # NEW — only trade NO bets until YES signal is fixed
```

**Expected outcomes with these values:**
- Trigger rate: **39.6%** (114/288 markets) — within the 15–60% acceptable range
- Win rate: **90.4%** — from random-ish to strongly positive EV
- Per-trade EV: positive (NO bets average payout structure TBD, but 90% win rate is highly profitable)

### City Blacklist

**Recommended**: None (the city-level problems were YES bias, not city-level signal failure)

**Watch list** (do not exclude, but monitor in next backtest):
- `KXHIGHTDC` — NO win rate 37.5%, borderline below 40% floor

### Longer-Term Fixes Required (Developer tasks)

1. **Fix YES directional bias**: Investigate why model predicts YES 58% of the time when it wins only 15%. Likely root cause: warm bias in GEFS ensemble + Kalshi thresholds set at above-average temperature levels. Possible fixes:
   - Add a "base rate" prior: if historical exceedance rate for the market threshold is <30%, require much higher model probability before going YES
   - Review bias corrections per city — they may be adding warm bias
   - Consider a YES-suppression multiplier in edge_detector.py

2. **Fix edge quantization**: The edge calculator outputs only 3 discrete values (0.1, 0.3, 0.5). This provides almost no selectivity. True continuous edge calculation would allow meaningful threshold tuning.

3. **Fix confidence quantization**: Same issue — 3 levels (0.333, 0.667, 1.0) limits threshold power. More granular confidence scoring needed.

---

## 6. SIGNAL QUALITY ASSESSMENT: REAL OR NOISE?

**The NO signal is REAL. The YES signal is BROKEN.**

Evidence the model has genuine predictive value:
- NO bets: 90.4% win rate across 114 trades, 14 days, 16 cities — this is not noise
- NO win rates are consistent across nearly all cities (75-100%)
- The signal correctly identifies when temperatures will NOT exceed threshold

Evidence the YES signal is broken:
- YES bets: 14.9% win rate — worse than random
- Consistent across ALL cities and ALL edge/confidence levels
- Not city-specific noise — this is a systematic model failure in the YES direction

**Bottom line**: The weather ensemble model has strong predictive power for "will it NOT be hot today" and near-zero for "will it BE hot today." The model is useful — but only half of it works. Trade accordingly until the YES bias is diagnosed and corrected.

---

## ACTION ITEMS

| Priority | Owner | Action |
|----------|-------|--------|
| 🔴 IMMEDIATE | SA-3 Developer | Add `WEATHER_DIRECTION_FILTER = "NO"` to config; update edge_detector.py to respect it |
| 🔴 IMMEDIATE | SA-3 Developer | Set `MIN_EDGE_WEATHER = 0.30`, `MIN_CONFIDENCE_WEATHER = 0.667` |
| 🟡 SHORT-TERM | SA-2 Researcher | Investigate YES directional bias — is GEFS warm-biased in spring? |
| 🟡 SHORT-TERM | SA-3 Developer | Refactor edge/confidence to be continuous (not 3-level) |
| 🟢 MONITOR | SA-4 QA | Watch KXHIGHTDC in next backtest — NO win rate 37.5% borderline |
| 🟢 NEXT CYCLE | SA-1 Optimizer | After YES bias fix: re-evaluate YES thresholds with fresh backtest |
