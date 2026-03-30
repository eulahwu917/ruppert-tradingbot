# STRAT-15M-THRESHOLD-RELAX-2026-03-29

**Module:** crypto_15m  
**Status:** PROPOSED — pending Dev implementation  
**Author:** Ruppert Strategist  
**Date:** 2026-03-29  
**Goal:** Data collection mode — get 30+ trades into the Optimizer as fast as possible

---

## Background

The 15m crypto module has logged **40,381 decisions with zero entries**. The bot is operational and generating real signals — but every candidate is being blocked by risk filters calibrated for profitability, not data collection.

David's instruction: **skew towards getting trades through. We can always tighten later.**

---

## Skip Reason Audit (40,381 total decisions)

| Skip Reason | Count | Adjustable? |
|---|---|---|
| LATE_WINDOW | 22,149 | ❌ Timing, not adjustable |
| EARLY_WINDOW | 10,320 | ❌ Timing, not adjustable |
| **THIN_MARKET** | **2,512** | ✅ R4 threshold |
| **LOW_KALSHI_LIQUIDITY** | **1,026** | ✅ R3 threshold |
| **WIDE_SPREAD** | **788** | ✅ R2 threshold |
| **LOW_CONVICTION** | **747** | ✅ MIN_CONVICTION |
| **INSUFFICIENT_EDGE** | **674** | ✅ MIN_EDGE |
| DAILY_CAP | 310 | ✅ Rate limit |
| STRATEGY_GATE | 333 | ❌ Settlement timing |

**Adjustable blocks: 5,747** (of which the top 5 are directly threshold-driven)

---

## Threshold Analysis: Actual Values vs Current Thresholds

### Current DEMO Config (environments/demo/config.py)

These are the **already-relaxed** DEMO values that are still blocking everything:

| Threshold | Config Key | Current DEMO Value | Original PROD Value |
|---|---|---|---|
| R2 Max Spread | `CRYPTO_15M_MAX_SPREAD` | 15c | 8c (hardcoded) |
| R3 Liquidity Min Pct | `CRYPTO_15M_LIQUIDITY_MIN_PCT` | 0.001 (0.1% of OI) | 0.003 |
| R4 Thin Market Ratio | `CRYPTO_15M_THIN_MARKET_RATIO` | 0.05 (5% of 30d avg) | 0.25 |
| MIN_CONVICTION | inline `abs(raw_score) < 0.15` | 0.15 | 0.15 |
| MIN_EDGE | `CRYPTO_15M_MIN_EDGE` | 0.05 | 0.08 |

### Filter Execution Order (from crypto_15m.py)
R1 EXTREME_VOL → R2 WIDE_SPREAD → R3 LOW_KALSHI_LIQUIDITY → R4 THIN_MARKET → R5 STALE → R6 EXTREME_FUNDING → R7 LOW_CONVICTION → R8 DRAWDOWN → R9 MACRO → R10 BASIS_RISK → INSUFFICIENT_EDGE

**Important:** THIN_MARKET (R4) fires AFTER WIDE_SPREAD (R2) and LOW_KALSHI_LIQUIDITY (R3). The 2,512 THIN_MARKET blocks represent entries that already passed spread and liquidity checks.

---

## Actual Value Distributions (from 7,912 signal-bearing log entries)

### R2: WIDE_SPREAD (788 blocks, current threshold: 15c)
The 788 WIDE_SPREAD blocks have the following spread distribution:
- p0: 9c | p25: 10c | p50: 14c | p75: 25c | p90: 43c | p95: 59c | p100: 98c
- **Spread 9–15c: 411 entries** (52%) — barely above the threshold
- Spread 16–20c: 85 entries (11%)
- Spread 21–30c: 169 entries (21%)
- Spread >30c: 123 entries (16%)

**Observation:** Half the WIDE_SPREAD blocks are spreads of just 9–15c. These are not broken markets — they're normal Kalshi 15m markets with slightly wider books.

### R3: LOW_KALSHI_LIQUIDITY (1,026 blocks, current: min_depth = max(OI×0.001, 50))
Book depth distribution for blocked entries:
- p0: $2 | p10: $5 | p25: $16 | p50: $24 | p75: $35 | p90: $45 | p95: $47 | p100: $281
- **Depths <$50: 993 entries** (97%) — the $50 floor is the binding constraint
- Depths $50–$99: 18 entries
- Depths ≥$100: 15 entries

**Observation:** The $50 fallback floor (when dollar_oi=0 or OI is unavailable) is the dominant blocker. Real Kalshi 15m book depths at $20–$50 are small but functional for $5–$25 position sizes.

### R4: THIN_MARKET (2,512 blocks, current: OKX vol ratio < 0.05)
THIN_MARKET entries already passed spread (p50 spread = 2c!) and liquidity checks:
- Spread: p50=2c, p75=5c, p90=8c — excellent spreads
- Depth: p50=$200, p75=$612, p90=$1,586 — solid liquidity
- |raw_score|: p25=0.20, p50=0.41, p75=0.69 — strong signals

**This is the biggest blocker.** 2,512 entries with good spreads, good Kalshi liquidity, and meaningful signals are being killed by the OKX volume ratio filter. Of these, **2,027 would also pass relaxed conviction and edge thresholds**.

The current threshold (0.05 = 5% of 30d avg) is still blocking during normal low-volume periods (Asian session, weekends, thin hours).

### R7: LOW_CONVICTION (747 blocks, current: |raw_score| < 0.15)
|raw_score| distribution for blocked entries:
- p0: 0.00 | p50: 0.07 | p75: 0.11 | p90: 0.13 | p95: 0.14 | p100: 0.15

**Observation:** These are genuinely weak signals — median |raw_score| = 0.07. However, in data-collection mode, even weak signals are useful if they produce trades that teach the model. The 0.15 threshold is cutting off signals that have directional conviction, just less of it.

### INSUFFICIENT_EDGE (674 blocks, current: MIN_EDGE = 0.05)
Edge distribution for blocked entries:
- p0: -0.057 | p25: 0.003 | p50: 0.021 | p75: 0.040 | p90: 0.051 | p99: 0.082

**Observation:** p50 edge = 2.1%, p90 = 5.1%. These are thin but non-zero edges. In data collection mode, a 2–3% edge is meaningful — it means the model has directional conviction, just not enough to clear the 5% bar.

---

## Recommendations: Data Collection Mode Thresholds

### Philosophy
- Minimum viable = "not a completely broken market"
- We are NOT trying to be profitable right now
- We ARE trying to generate 30+ diverse trades across all 4 assets (BTC/ETH/XRP/DOGE)
- Tag all data-collection trades with their actual quality metrics for later Optimizer segmentation

### Proposed Changes

#### R4: THIN_MARKET — `CRYPTO_15M_THIN_MARKET_RATIO`
| | Value |
|---|---|
| **BEFORE** | `0.05` (5% of 30d avg OKX 5m volume) |
| **AFTER** | `0.01` (1% of 30d avg) |

**Rationale:** The 2,512 blocked THIN_MARKET entries already have excellent Kalshi spreads (median 2c) and strong book depth (median $200). They are passing all Kalshi liquidity checks. The OKX volume filter exists to ensure price discovery is reliable — at 1% we still require the underlying market to be trading, just not at peak volume. A near-zero or completely dead OKX book would show as <0.1%; 1% allows thin-but-functional periods. Expected additional passes: ~2,027 entries with meaningful signals.

#### R2: WIDE_SPREAD — `CRYPTO_15M_MAX_SPREAD`
| | Value |
|---|---|
| **BEFORE** | `15` cents |
| **AFTER** | `25` cents |

**Rationale:** 411 of the 788 WIDE_SPREAD blocks have spreads of just 9–15c — barely over the current limit. Kalshi 15m markets naturally widen to 10–25c during less active periods. A 25c spread on a 50c YES contract is 50% round-trip cost — painful for profit, but these markets are still functional for data collection. We draw the line at 25c to avoid truly broken orderbooks (p75 of blocks = 25c, so this captures the majority). Spreads >25c (123 entries, 16% of blocks) remain filtered — those are genuinely poor execution conditions.

#### R3: LOW_KALSHI_LIQUIDITY — `CRYPTO_15M_LIQUIDITY_MIN_PCT` + floor
| | Value |
|---|---|
| **BEFORE** | `0.001` (0.1% of OI), floor `$50` when OI unavailable |
| **AFTER** | `0.0005` (0.05% of OI), floor `$20` when OI unavailable |

**Rationale:** 97% of liquidity blocks are hitting the $50 absolute floor when dollar_oi=0. The Kalshi 15m markets typically have $20–$50 of book depth — which is sufficient to fill a $5–$25 position. Dropping the floor to $20 unlocks most of these. We keep a floor to avoid trading into literally empty books. Also reduce the OI-based pct from 0.1% to 0.05% for proportional cases. Expected additional passes: ~993 entries.

#### R7: LOW_CONVICTION — inline threshold in `check_risk_filters()`
| | Value |
|---|---|
| **BEFORE** | `abs(raw_score) < 0.15` → block |
| **AFTER** | `abs(raw_score) < 0.05` → block |

**Rationale:** The raw_score is a weighted z-score composite. A score of 0.05 means at least one signal component (likely TFI at weight 0.42 or OBI at 0.25) is showing a mild directional z-score. This is not noise — it's a weak but real signal. The 0.15 threshold was chosen for profitability; for data collection, 0.05 allows us to capture the full signal distribution. Note that 246 of the 747 LOW_CONVICTION blocks have |raw_score| < 0.05 — those remain filtered (flat/noise). Expected additional passes: ~501 entries.

#### MIN_EDGE — `CRYPTO_15M_MIN_EDGE`
| | Value |
|---|---|
| **BEFORE** | `0.05` (5%) |
| **AFTER** | `0.02` (2%) |

**Rationale:** Edge = model_prob − market_price. At 2%, the model is saying "I have a 2% probability advantage over the market price." This is thin but positive and indicates meaningful directional conviction beyond random. The p50 of currently-blocked INSUFFICIENT_EDGE entries is 2.1% — meaning half the blocked entries sit right at the proposed new threshold. Min edge of 0% would be dangerous (we'd trade coin-flip markets); 2% is a meaningful signal floor. Expected additional passes: ~337 entries.

#### DAILY_CAP — `CRYPTO_15M_DAILY_CAP_PCT` 
| | Value |
|---|---|
| **BEFORE** | `0.04` (4% of capital per day) |
| **AFTER** | `0.06` (6% of capital per day) |

**Rationale:** 310 DAILY_CAP blocks suggests the cap is being hit regularly. In data collection mode, we want more trades per day, not fewer. Raising to 6% gives more room without being reckless. This change is secondary — only matters once other filters start letting trades through.

---

## Projected Impact

With all 5 changes applied simultaneously:

| Filter | Current Blocks | Est. Blocks After | Δ Passes |
|---|---|---|---|
| THIN_MARKET | 2,512 | ~485 | +2,027 |
| LOW_KALSHI_LIQUIDITY | 1,026 | ~33 | +993 |
| WIDE_SPREAD | 788 | ~377 | +411 |
| LOW_CONVICTION | 747 | ~246 | +501 |
| INSUFFICIENT_EDGE | 674 | ~337 | +337 |
| **Total** | **5,747** | **~1,478** | **+4,269** |

These 4,269 additional "would pass" entries occurred over just 2 days (2026-03-28 to 2026-03-29). That's ~2,135 per day. Even accounting for the daily cap, the module should generate **10–20 trades per day** once thresholds are relaxed — reaching the 30-trade Optimizer threshold in 2–3 days.

---

## Data Quality Tagging (ALREADY IMPLEMENTED)

The `data_quality` field in trade logs already captures:
- `standard`: passes all original PROD thresholds
- `thin_market`: OKX volume below 25% of 30d avg
- `wide_spread`: Kalshi spread > 8c
- `low_liquidity`: book depth below original $100 floor
- `unknown`: OKX volume data unavailable

The Optimizer will use this field to segment outcomes — relaxed-threshold trades are tagged and can be weighted or filtered separately in analysis.

---

## Implementation Notes for Dev

All changes are in `environments/demo/config.py` — no code changes needed except for the MIN_CONVICTION threshold which is hardcoded inline in `crypto_15m.py`.

### config.py changes:
```python
# BEFORE:
CRYPTO_15M_MIN_EDGE          = 0.05
CRYPTO_15M_LIQUIDITY_MIN_PCT = 0.001
CRYPTO_15M_MAX_SPREAD        = 15
CRYPTO_15M_THIN_MARKET_RATIO = 0.05
CRYPTO_15M_DAILY_CAP_PCT     = 0.04

# AFTER:
CRYPTO_15M_MIN_EDGE          = 0.02   # DATA COLLECTION: 2% min edge (was 0.05)
CRYPTO_15M_LIQUIDITY_MIN_PCT = 0.0005 # DATA COLLECTION: 0.05% of OI (was 0.001)
CRYPTO_15M_MAX_SPREAD        = 25     # DATA COLLECTION: 25c max spread (was 15)
CRYPTO_15M_THIN_MARKET_RATIO = 0.01   # DATA COLLECTION: 1% of 30d avg vol (was 0.05)
CRYPTO_15M_DAILY_CAP_PCT     = 0.06   # DATA COLLECTION: 6% of capital/day (was 0.04)
```

### crypto_15m.py code change (check_risk_filters, R7):
```python
# BEFORE:
if abs(raw_score) < 0.15:
    return {'block': 'LOW_CONVICTION', 'okx_volume_pct': okx_volume_pct}

# AFTER:
min_conviction = getattr(config, 'CRYPTO_15M_MIN_CONVICTION', 0.05)  # DATA COLLECTION: 0.05 (was hardcoded 0.15)
if abs(raw_score) < min_conviction:
    return {'block': 'LOW_CONVICTION', 'okx_volume_pct': okx_volume_pct}
```

And add to config.py:
```python
CRYPTO_15M_MIN_CONVICTION    = 0.05   # DATA COLLECTION: min |raw_score| (was hardcoded 0.15)
```

Also update the liquidity fallback floor (in `check_risk_filters`, R3):
```python
# BEFORE:
if dollar_oi > 0:
    min_depth = max(dollar_oi * liquidity_min_pct, 50.0)
else:
    min_depth = 100.0

# AFTER:
liquidity_floor = getattr(config, 'CRYPTO_15M_LIQUIDITY_FLOOR', 20.0)  # DATA COLLECTION: $20 (was $50/$100)
if dollar_oi > 0:
    min_depth = max(dollar_oi * liquidity_min_pct, liquidity_floor)
else:
    min_depth = liquidity_floor
```

And add to config.py:
```python
CRYPTO_15M_LIQUIDITY_FLOOR   = 20.0   # DATA COLLECTION: absolute floor $20 (was $50/$100)
```

---

## Reversion Plan

When Optimizer has 30+ trades and runs its first analysis, tighten thresholds back to production-grade values based on observed outcomes. Recommended review trigger: `OPTIMIZER_MIN_TRADES = 30` (already set in config).

Expected tightening: MIN_EDGE → 0.06+, MAX_SPREAD → 10, THIN_MARKET → 0.10+, based on what the data shows about outcome correlation with market quality.

---

*Spec generated by Ruppert Strategist — 2026-03-29*
