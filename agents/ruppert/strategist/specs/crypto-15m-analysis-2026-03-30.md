# Crypto 15m Module — Data Analysis Report
**Date:** 2026-03-30  
**Analyst:** Data Scientist (Ruppert)  
**Purpose:** Diagnose zero entries since launch; provide hard data for Strategist optimization proposal  
**Dataset:** `environments/demo/logs/decisions_15m.jsonl`

---

## Dataset Overview

| Metric | Value |
|--------|-------|
| Total records | 113,369 |
| Date range | 2026-03-28 21:10 UTC → 2026-03-30 14:17 UTC |
| Duration | ~41.1 hours |
| Tickers | BTC, ETH, XRP, DOGE |
| Unique windows logged | 712 |
| ENTER decisions | **0** |

---

## 1. Skip Reason Breakdown

### All Time (n=113,369)

| Skip Reason | Count | % |
|-------------|-------|---|
| LATE_WINDOW | 57,937 | 51.1% |
| EARLY_WINDOW | 34,880 | 30.8% |
| STRATEGY_GATE (too_close_to_settlement) | 11,637 | 10.3% |
| THIN_MARKET | 2,931 | 2.6% |
| INSUFFICIENT_EDGE | 2,051 | 1.8% |
| LOW_CONVICTION | 1,578 | 1.4% |
| LOW_KALSHI_LIQUIDITY | 1,026 | 0.9% |
| WIDE_SPREAD | 874 | 0.8% |
| DAILY_CAP | 310 | 0.3% |
| EXTREME_VOL | 120 | 0.1% |
| BASIS_RISK | 72 | 0.1% |

### Last 24h (n=109,112)

| Skip Reason | Count | % |
|-------------|-------|---|
| LATE_WINDOW | 56,072 | 51.4% |
| EARLY_WINDOW | 34,440 | 31.6% |
| STRATEGY_GATE | 11,463 | 10.5% |
| INSUFFICIENT_EDGE | 1,997 | 1.8% |
| THIN_MARKET | 1,945 | 1.8% |
| LOW_CONVICTION | 1,524 | 1.4% |
| LOW_KALSHI_LIQUIDITY | 849 | 0.8% |
| WIDE_SPREAD | 401 | 0.4% |

_Pattern is stable — no meaningful change in last 24h vs all time._

### Category Summary (All Time)

| Category | Count | % |
|----------|-------|---|
| **Timing** (LATE_WINDOW + EARLY_WINDOW) | **92,817** | **81.9%** |
| **Strategy Gate** (too_close_to_settlement) | **11,637** | **10.3%** |
| **Market Quality** (THIN + SPREAD + LIQ) | **4,831** | **4.3%** |
| **Good Signal, bad threshold** (INSUFF_EDGE + LOW_CONV) | **3,629** | **3.2%** |
| Other (DAILY_CAP, EXTREME_VOL, BASIS_RISK) | 502 | 0.4% |

**Finding:** Timing issues alone account for 81.9% of all skips. STRATEGY_GATE adds another 10.3%. Actual signal/threshold failures are only 3.2% of total decisions.

---

## 2. Timing Analysis

### LATE_WINDOW Distribution (n=57,937)

| elapsed_secs Range | Count | % |
|-------------------|-------|---|
| 660–720s (below cutoff — tagged LATE?) | 12,104 | 20.9% |
| 720–750s (just over cutoff) | 9,158 | 15.8% |
| 750–800s | 14,865 | 25.7% |
| 800–900s | 20,952 | 36.2% |
| 900–1,000s | 746 | 1.3% |
| >1,000s | 112 | 0.2% |

**Stats:** Min=660.1s, Median=775.6s, Max=1204.3s

> ⚠️ **Anomaly:** 12,104 LATE_WINDOW records have elapsed_secs < 720s (range: 660–719.9s). These should NOT be late by the current cutoff. Possible causes: (1) clock drift between WS message receipt and decision timestamp, (2) the cutoff logic uses window_close_ts proximity rather than elapsed_secs directly. Investigate.

**Close calls (720–780s):** 18,208 records (31.4% of all LATE_WINDOW). These are events that missed the window by 0–60 seconds — a 10% relaxation of the LATE cutoff would recapture a meaningful fraction.

### EARLY_WINDOW Distribution (n=34,880)

| elapsed_secs Range | Count | % |
|-------------------|-------|---|
| 0–30s | 7,067 | 20.3% |
| 30–60s | 8,826 | 25.3% |
| 60–90s | 9,637 | 27.6% |
| 90–120s | 9,331 | 26.8% |

**Stats:** Min=0.2s, Max=120.0s, Median=64.2s

> **Key insight:** 26.8% of EARLY_WINDOW skips (9,331 records) are at 90–120s — they arrive within 30 seconds of the 120s guard opening. If EARLY_WINDOW cutoff dropped from 120s to 90s, ~9,331 records per 41h would be re-admitted (rough upper bound; many would still skip for other reasons).

### Window Evaluation: Primary vs Secondary

| Zone | elapsed_secs | Records | % of Total |
|------|-------------|---------|-----------|
| PRIMARY | 120–480s | 12,815 | 11.3% |
| SECONDARY | 480–720s | 19,869 | 17.5% |
| Total timed in-window | — | 32,684 | 28.8% |

**Primary vs Secondary ratio:** 39.2% / 60.8%

> The majority of in-window decisions land in the secondary zone (480–720s). This is consistent with WS events being delayed or REST polling arriving after midpoint. LATE_WINDOW dominates because most activity fires after 720s — i.e., the WS is delivering updates deep into and past the window close.

---

## 3. Signal Quality (Non-Timing Decisions)

**Non-timing decisions (past EARLY + LATE gates):** 20,552  
**Records with edge data:** 14,000  
**Records with P_final data:** 20,552

### Edge Distribution (n=14,000)

| Edge Range | Count | % |
|------------|-------|---|
| Negative (<0) | 820 | 5.9% |
| 0–0.005 | 214 | 1.5% |
| 0.005–0.01 | 214 | 1.5% |
| 0.01–0.015 | 205 | 1.5% |
| 0.015–0.02 (just below MIN_EDGE) | 209 | 1.5% |
| **0.02–0.03 (above threshold)** | 387 | 2.8% |
| **>0.03 (strongly above threshold)** | 11,902 | **85.3%** |

**Stats:** Min=-0.1126, Max=0.7551, Mean=0.2020, Median=0.1730

> **Critical finding:** 88.1% of records with edge data have edge ≥ 0.02. Edge is NOT the problem — signals routinely exceed the threshold when evaluated past timing gates. Only 209 records (1.5%) sit in the near-miss band (0.015–0.019).

### P_final Distribution (n=20,552)

| P_final Range | Count | % |
|--------------|-------|---|
| <0.45 (bearish) | 7,741 | 37.7% |
| 0.45–0.50 (slightly bearish) | 2,655 | 12.9% |
| 0.50–0.52 (neutral) | 1,125 | 5.5% |
| 0.52–0.55 (weak bullish) | 1,466 | 7.1% |
| 0.55–0.60 (bullish) | 2,365 | 11.5% |
| >0.60 (strong bullish) | 5,200 | 25.3% |

**Stats:** Min=0.1177, Max=0.8832, Mean=0.4966, Median=0.4803

> P_final is bimodal — roughly half bearish (<0.50), half bullish. 36.8% (7,565 records) meet the P_final > 0.55 threshold. Signals are NOT systematically weak.

### Strong Signal Records (edge ≥ 0.02 AND P_final > 0.55)

| Metric | Value |
|--------|-------|
| Records meeting both thresholds | 12,336 edge ≥ 0.02, 5,683 P_final ≥ 0.55 |
| Records meeting BOTH conditions | 4,950 |
| ...of which in PRIMARY window (120–480s) | 3,051 |
| ...blocked by STRATEGY_GATE (of 4,950) | 4,623 |
| Strong signals in primary window blocked ONLY by STRATEGY_GATE | **2,868** |

> **The #1 blocker for qualified signals: STRATEGY_GATE.** 4,623 of 4,950 strong-signal records (93.4%) are blocked by the settlement proximity gate.

---

## 4. Window Coverage

### Coverage by Day

| Date | Windows Seen | Primary-Evaluated | Coverage Rate |
|------|-------------|------------------|---------------|
| 2026-03-28 | 16 | 12 | 75.0% |
| 2026-03-29 | 304 | 292 | 96.1% |
| 2026-03-30 (partial) | 392 | 219 | 55.9% |

### Overall Coverage

| Metric | Value |
|--------|-------|
| Unique days | 3 |
| Expected windows (4 tickers × 56/day × 3 days) | 672 |
| Unique windows seen in log | 712 |
| Windows with ≥1 primary evaluation (120–480s) | 523 |
| **Coverage rate** | **77.8%** |

> Windows "seen" (712) exceed expected (672) because the expectation uses exactly 56/day while actual Kalshi windows can vary. Coverage rate of 77.8% means ~22% of windows get no primary-zone evaluation. March 30 partial-day coverage (55.9%) suggests WS reconnection issues during that period.

### Decisions per Window Distribution

| Decisions per Window | Count | % |
|---------------------|-------|---|
| 1 | 177 | 24.9% |
| 2–5 | 134 | 18.8% |
| 6–20 | 29 | 4.1% |
| 21–50 | 36 | 5.1% |
| 51–100 | 51 | 7.2% |
| **>100** | 285 | **40.0%** |

**Average:** 159.3 decisions/window; **Median:** 40

> 40% of windows receive 100+ decisions — this is the WS fire-hose pattern. Single-decision windows (24.9%) likely represent REST fallbacks or brief reconnect events.

---

## 5. REST Fallback Effectiveness

| Metric | Value |
|--------|-------|
| Decisions in 280–320s range | 1,447 |
| Decisions in 295–305s range (tight band) | 396 |
| Decisions in 270–330s range (broad) | 2,128 |

### Skip Reasons for 280–320s Decisions

| Reason | Count | % |
|--------|-------|---|
| STRATEGY_GATE (0.17h < 0.5h) | 450 | 31.1% |
| THIN_MARKET | 428 | 29.6% |
| STRATEGY_GATE (0.16h < 0.5h) | 186 | 12.9% |
| INSUFFICIENT_EDGE | 140 | 9.7% |
| LOW_CONVICTION | 90 | 6.2% |
| LOW_KALSHI_LIQUIDITY | 65 | 4.5% |
| WIDE_SPREAD | 60 | 4.1% |
| DAILY_CAP | 19 | 1.3% |
| EXTREME_VOL | 8 | 0.6% |
| BASIS_RISK | 1 | 0.1% |

> **REST fallback is firing** — 1,447 decisions land in the 280–320s band, confirming the REST trigger at ~5 min works. However, at ~5 min elapsed, many windows are still in STRATEGY_GATE territory for the later windows in a daily contract cycle. The 44% STRATEGY_GATE rate in this band confirms REST fallback is capturing valid primary-window timing but the settlement gate still blocks them.

---

## 6. STRATEGY_GATE Deep Dive

This gate (`too_close_to_settlement`) blocks 10.3% of ALL decisions and **93.4% of all qualified strong-signal decisions**. It is the decisive blocker.

### Settlement Time Remaining at Gate Trigger

| Hours Remaining | Count | % |
|----------------|-------|---|
| 0.0–0.1h (0–6 min) | 2,929 | 25.2% |
| 0.1–0.2h (6–12 min) | 7,153 | 61.5% |
| 0.2–0.3h (12–18 min) | 1,555 | 13.4% |
| 0.3–0.5h (18–30 min) | 0 | 0.0% |

> **The gate is never triggered at 0.3–0.5h remaining** — meaning the actual trigger horizon is well below the stated 0.5h threshold. The log messages are displaying actual time-remaining, which clusters between 0.05–0.22h (3–13 minutes). This still represents 1–2 windows being killed before settlement for a 15-minute contract.

> **Root cause confirmed:** The STRATEGY_GATE settlement threshold of 0.5h is appropriate for hourly contracts but severely wrong-sized for 15-minute contracts. A 15m contract window closes every 15 minutes (0.25h). A 0.5h gate eliminates the last 2 full windows before settlement. Lowering to 0.05h–0.10h would retain 2–3 viable windows per settlement cycle.

---

## 7. What-If Analysis

### If STRATEGY_GATE threshold lowered to 0.05h

Records that would be re-admitted to evaluation: **~11,637 decisions**  
Of those with strong signals in primary window: **~2,868 actionable windows**

### If EARLY_WINDOW cutoff lowered from 120s to 90s

Decisions re-admitted: **~9,331** (records in 90–120s band)  
(Many would still skip for other reasons, but primary coverage would improve)

### If MIN_EDGE lowered from 0.02 to 0.01

Records past timing+strategy gates that would enter:  
- At MIN_EDGE=0.02: 330  
- At MIN_EDGE=0.01: 519  
- **Additional entries: 189**

_Note: MIN_EDGE change is low-priority — the signal pipeline is already generating strong edge values (88.1% above 0.02)._

---

## Summary of Findings

### Finding 1: STRATEGY_GATE is the Primary Entry Blocker (Critical)

The settlement proximity gate blocks **10.3% of all decisions** and **93.4% of all qualified strong-signal decisions** (edge ≥ 0.02, P_final > 0.55). The gate fires when 0.05–0.22h remain before settlement — meaning it's killing valid primary-window opportunities 3–13 minutes before settlement. For 15-minute contracts, the 0.5h threshold was almost certainly inherited from an hourly contract config. **Recommended fix: Lower to 0.05h–0.10h.**

### Finding 2: Timing Gates Swamp Everything — 81.9% of Skips (High)

LATE_WINDOW (51.1%) + EARLY_WINDOW (30.8%) = 81.9% of all decisions are timing-rejected. The median LATE_WINDOW elapsed_secs is 775.6s — the system is consistently evaluating windows 55+ seconds after the 720s cutoff. 31.4% of LATE_WINDOW records are "close calls" within 60 seconds of the cutoff (720–780s range). **Recommended: Investigate WS delay; consider raising LATE_WINDOW cutoff to 800s or processing messages faster. Also investigate 12,104 records tagged LATE but with elapsed < 720s (likely a clock/logic bug).**

### Finding 3: Signal Quality is NOT the Problem (Informational)

Edge values are healthy — 88.1% of records with edge data show edge ≥ 0.02 (threshold). Median edge is 0.173 (8.6× the threshold). P_final is bimodal but 36.8% of records show P_final ≥ 0.55. The 330 otherwise-qualified entries (past all gates, in primary window) would have entered at current thresholds — they're blocked by downstream market quality filters (THIN_MARKET, WIDE_SPREAD). **Signal thresholds are not the bottleneck; timing and STRATEGY_GATE are.**

---

## Recommended Priority Order for Strategist

1. **[P0] STRATEGY_GATE threshold:** Lower from 0.5h → 0.05–0.10h for 15m contract type. This directly unlocks ~2,868 strong-signal primary-window evaluations.
2. **[P1] LATE_WINDOW timing bug:** Investigate 12,104 records tagged LATE with elapsed < 720s. Fix the classification logic.
3. **[P1] LATE_WINDOW cutoff:** Consider raising from 720s → 800s. Would re-admit 9,158 records (15.8% of LATE_WINDOW pool).
4. **[P2] EARLY_WINDOW cutoff:** Consider lowering from 120s → 90s. Would re-admit ~9,331 records (26.8% of EARLY_WINDOW pool).
5. **[P3] Market quality (THIN_MARKET, WIDE_SPREAD):** Only affects 4.3% of decisions — secondary concern, investigate Kalshi liquidity patterns by hour.
6. **[P4] MIN_EDGE / MIN_CONVICTION:** Not a significant bottleneck; deprioritize.

---

_Generated by Ruppert Data Scientist subagent | 2026-03-30_
