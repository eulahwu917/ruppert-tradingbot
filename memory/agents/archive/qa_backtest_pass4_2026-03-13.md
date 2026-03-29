# QA Pass 4 — Accuracy Backtest Report
**SA-4 QA** | 2026-03-13 19:00 PDT
**Backtest period**: 2026-02-27 → 2026-03-13

---

## CHECK 1: Syntax (ast.parse)

| File | Result |
|------|--------|
| `backtest_engine.py` | ✅ PASS |
| `report.py` | ✅ PASS |
| `backtest.py` | ✅ PASS |

---

## CHECK 2: Backtest Run

- **Return code**: 0 (clean exit, no crash)
- **STDERR**: empty (no errors, no warnings)
- **Mode**: ACCURACY
- **Capital**: $400.00

---

## CHECK 3: Results

**Results file**: `results/20260313_190058_accuracy_report.txt`

| Metric | Value |
|--------|-------|
| Total markets evaluated | 288 |
| Triggered | 268 |
| Trigger rate | **93.1%** |
| Correct | 126 |
| Win rate | **47.0%** |

**Config used:**
- `min_edge_weather`: 0.15 (15%)
- `min_confidence_weather`: 0.55 (55%)
- `same_day_skip_hour`: 14

### Per-City Results (all 16 cities)

| City | Triggered | Correct | Win Rate |
|------|-----------|---------|----------|
| KXHIGHTMIN | 18 | 13 | 72.2% |
| KXHIGHCHI | 16 | 10 | 62.5% |
| KXHIGHAUS | 17 | 10 | 58.8% |
| KXHIGHPHIL | 18 | 10 | 55.6% |
| KXHIGHTSEA | 18 | 10 | 55.6% |
| KXHIGHTSATX | 16 | 9 | 56.2% |
| KXHIGHTOKC | 16 | 8 | 50.0% |
| KXHIGHTDC | 16 | 7 | 43.8% |
| KXHIGHTATL | 16 | 7 | 43.8% |
| KXHIGHNY | 17 | 7 | 41.2% |
| KXHIGHTLV | 17 | 7 | 41.2% |
| KXHIGHDEN | 18 | 7 | 38.9% |
| KXHIGHTDAL | 15 | 5 | 33.3% |
| KXHIGHMIA | 16 | 5 | 31.2% |
| KXHIGHTMIN SFO | 17 | 5 | 29.4% |
| KXHIGHLAX | 17 | 6 | 35.3% |

### Top 3 Cities by Win Rate
1. **KXHIGHTMIN** — 72.2% (13/18)
2. **KXHIGHCHI** — 62.5% (10/16)
3. **KXHIGHAUS / KXHIGHTSATX / KXHIGHPHIL / KXHIGHTSEA** — 55-58% range

### Bottom 3 Cities by Win Rate
1. **KXHIGHTMIN SFO (KXHIGHTMIN SFO)** — 29.4% (5/17) ❌ Below 40% floor
2. **KXHIGHMIA** — 31.2% (5/16) ❌ Below 40% floor
3. **KXHIGHTDAL** — 33.3% (5/15) ❌ Below 40% floor

---

## CHECK 4: Sanity Checks

| Check | Threshold | Actual | Result |
|-------|-----------|--------|--------|
| Trigger rate | 5%–60% | **93.1%** | ❌ **CRITICAL FAIL** |
| Win rate | 40%–80% | 47.0% | ✅ PASS |
| Min triggered markets (total) | ≥ 20 | 268 | ✅ PASS |
| No crash / divide-by-zero | n/a | Clean | ✅ PASS |
| SFO win rate < 40% floor | n/a | 29.4% | ⚠️ WARNING |
| MIA win rate < 40% floor | n/a | 31.2% | ⚠️ WARNING |
| DAL win rate < 40% floor | n/a | 33.3% | ⚠️ WARNING |

---

## Issues Found

### 🔴 CRITICAL: Trigger Rate 93.1% — Thresholds Far Too Loose

The algorithm is triggering on 93.1% of all markets. The sanity threshold is 5–60%. This means:
- `min_edge_weather: 0.15` (15%) and `min_confidence_weather: 0.55` (55%) are not filtering effectively
- The edge/confidence signal is almost always satisfied — the model is nearly always "confident enough"
- This is either a threshold calibration issue (thresholds too low) or the edge distribution itself is too wide
- Result: The bot would be in almost every single market, which defeats the purpose of selectivity

**SA-1 Optimizer must tighten thresholds** before this is production-ready.
Suggested starting point: raise `min_edge` to 0.20–0.25 and `min_confidence` to 0.60–0.65, then re-run.

### ⚠️ WARNING: 3 Cities Below 40% Win Rate Floor

SFO (29.4%), MIA (31.2%), and DAL (33.3%) are all below the 40% floor — these cities have negative expected value at current thresholds. The model's signal for these cities may be unreliable:
- MIA: known NWS grid issue (404 errors, NWS layer disabled) — degrades signal quality
- SFO: coastal microclimate may require different bias corrections or ensemble weighting
- DAL: no known data issue — may need investigation

**Recommendation**: Blacklist SFO and MIA from trading pending signal improvements. Flag DAL for Optimizer review.

---

## Overall Verdict

### ❌ NEEDS MORE FIXES

**Blocker**: Trigger rate of 93.1% is wildly out of range (expected: 5–60%). The algorithm has no selectivity at current thresholds — it would enter nearly every market. This must be fixed by SA-1 Optimizer before any further deployment consideration.

**Action items for next cycle:**
1. **SA-1 Optimizer**: Raise `min_edge_weather` and `min_confidence_weather` to bring trigger rate into 15–40% range
2. **SA-1 Optimizer**: Review SFO, MIA, DAL signal quality — consider city blacklist or per-city threshold overrides
3. **SA-3 Developer**: After Optimizer provides new thresholds, update config and re-run backtest
4. **QA (SA-4)**: Will re-verify in QA Pass 5

The win rate of 47.0% overall is acceptable (within 40–80% band), but meaningless until trigger rate is fixed — currently the bot would be indiscriminately entering all markets, destroying any edge.
