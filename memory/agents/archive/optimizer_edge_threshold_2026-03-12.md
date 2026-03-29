# Optimizer Analysis: Weather Edge Threshold (15%) Review
_SA-1 Optimizer | 2026-03-12 | Flagged for CEO + David consideration_

---

## Executive Summary

**Current threshold assessment: SLIGHTLY TOO HIGH for validated markets (NY, CHI). APPROPRIATE for Miami.**

**Recommended change:**
- NY + CHI weather trades: lower minimum edge from 15% → **12%**
- Miami weather trades: **keep at 15%** (or halt entirely) until NWS layer is restored
- Floor (no-go zone): never below 10% — spread erosion risk

---

## 1. Historical Performance at 15%: Entry Edge Values

From trade logs (`trades_2026-03-10.jsonl`), using the sign convention `edge = noaa_prob - market_prob` (negative = NO has edge):

| Ticker | Outcome | noaa_prob | market_prob | Edge (NO) | Notes |
|--------|---------|-----------|-------------|-----------|-------|
| KXHIGHMIA B85.5 | **WIN** | 3.88% | 33% | **29.1%** | Exited 95¢ rule |
| KXHIGHNY B66.5 | **WIN** | 9.87% | 31% | **21.1%** | Exited 95¢ rule |
| KXHIGHCHI B52.5 | **WIN** | 0.16% | 19% | **18.8%** | Exited 95¢ rule |
| KXHIGHCHI B50.5 | **WIN** | 0.60% | 19% | **18.4%** | Exited 95¢ rule |
| KXHIGHCHI B48.5 | **WIN** | 1.73% | 19% | **17.3%** | Exited 95¢ rule — closest to threshold |
| KXHIGHMIA B83.5 | **LOSS** | 6.80% | 58% | **51.2%** | Settled against us — degraded signal |

**Critical observation:** All 5 wins came from entries between 17.3% and 29.1% edge — not dramatically above the 15% floor. The *lowest* winning entry (CHI B48.5, 17.3%) was only 2.3 percentage points above threshold.

**The loss (MIA B83.5) had 51.2% computed edge** — massive by any measure — yet still lost. This was a **signal quality failure**, not a threshold failure. The GEFS-only signal for Miami was systematically wrong. High computed edge ≠ reliable trade; it just means the model disagreed strongly with the market, which is meaningless if the model is miscalibrated.

**Conclusion from history:** The 15% threshold didn't fail on the loss. It would have passed the entry regardless at any reasonable threshold (51% edge clears everything). The threshold is protecting against *near-zero* edge trades, not against *bad signal* trades.

---

## 2. What Does 15% Edge Mean in Practice?

Edge convention: `edge_NO = market_prob_YES - model_prob_YES`

| If market prices YES at... | We need model to say YES < ... | For 15% edge on NO |
|---|---|---|
| 30¢ | < 15% | Moderately restrictive |
| 25¢ | < 10% | Restrictive |
| 20¢ | < 5% | Very restrictive |
| 19¢ (our Chicago wins) | < 4% | Very restrictive |

**The Chicago wins (market at 19¢) required our GEFS model to say <4% probability.** In practice, our noaa_prob was 0.16%–1.73%. So we were well inside the threshold on those trades — the 15% gate wasn't limiting us there.

The question is: what trades *fail* the 15% gate that we're missing? These would be cases where:
- Market prices YES at 25¢, our model says 12-14% → edge = 11-13% → passes 10%, fails 15%

For a 25¢ YES contract: market is saying 25% chance of the temperature hitting that band. Our model says 12-14%. That's a legitimate disagreement — the market is pricing 2x our model probability. This does represent real edge.

**Ensemble uncertainty reality:** A 31-member GEFS ensemble for 1-2 day horizon forecasts has relatively tight distributions for extreme temperature outcomes. Ensemble spread doesn't typically create ±15% uncertainty on a "will Chicago hit 52°F?" question in March. A 12-14% model probability vs. 25% market price is a meaningful signal, not noise.

---

## 3. What Happens at 10% Threshold?

**EV math:** With Kalshi's ~2% spread, net EV at 10% edge = **8%** (positive, but thin)

**Position sizing:** At 10% edge with 25% Kelly, Kelly fraction ≈ 0.10/0.90 × 0.25 ≈ 2.8% of capital. At $400 capital, Kelly-sized = ~$11. Entry size remains `min($25, 2.5% capital)` = $10, so position size is unchanged from 15% entries.

**Win/loss ratio change:** More entries → more trades, potentially including some 10-14% edge trades that are noisier. At this edge level, model calibration matters more because the margin for error is smaller.

**Risk:** At 10% threshold, a model that's even 3% off on probability can flip a trade from +EV to -EV. For Miami (degraded signal), this is too risky. For Chicago and NY (validated, NWS-backed), calibration is better.

---

## 4. What Happens at 8% Threshold?

**Not recommended.** 
- Net EV after 2% spread = **6%** — technically positive, but spread eats 25% of your edge
- Any model imprecision (and all ensemble models have imprecision) can push this negative
- Kelly-optimal size at 8% edge is tiny (~$3-5), making execution fees disproportionately large
- This is speculation territory, not systematic edge harvesting

**Hard floor: 10% minimum, full stop.**

---

## 5. Why Is Weather at 15% and Crypto at 10%? Is There Logic Here?

| Factor | Weather | Crypto |
|--------|---------|--------|
| Signal source | 31-member GEFS ensemble | Multi-TF RSI + smart money |
| Signal quality | Well-calibrated (except Miami) | Smart money: 5/9 wallets placeholder |
| Model uncertainty | Quantifiable, ensemble spread known | Extreme tail risk, DVOL unpredictable |
| Validation data | 10+ settlements for NY/CHI | Recent operational only |
| Spread structure | Fixed 2% Kalshi spread | Fixed 2% Kalshi spread |

**The asymmetry is partially inverted.** Our crypto signal has *lower* quality (placeholder wallets, heavy-tail risk) yet runs at a *lower* edge threshold. If anything, crypto should require higher edge to compensate for signal uncertainty, not lower.

**Was 15% weather arbitrary?** Almost certainly yes. There's no documented rationale in the codebase or optimizer logs for why 15% was chosen over 12% or 13%. The 10% crypto threshold was also set without a rigorous derivation — it likely reflects "feels safe above spread."

**Logical parity analysis:**
- If we trust crypto at 10% (net 8% EV), we should trust weather at 10-12% for validated markets
- Weather signal for NY/CHI is arguably *more* reliable than our crypto smart money signal
- A consistent position: weather (NY/CHI) at 12%, crypto at 10%, Miami at 15% pending repair

---

## 6. Dry Day Analysis: 2026-03-12 (0 trades, 36 markets, 4 scans)

**Two competing hypotheses:**

**H1: Market is efficient today.** Kalshi participants have priced weather contracts close to fair value. Most markets are within 10-15% of true probability. Our GEFS model agrees with market pricing. 0 trades = correct behavior.

**H2: Threshold is too restrictive.** There exist 10-14% edge trades we're skipping. Lowering to 12% would find 2-5 viable entries today.

**Evidence available:**
- No raw scan output was logged with market_prob vs. noaa_prob comparisons for 2026-03-12
- Cannot directly test H2 without re-running scanner in diagnostic mode
- 36 markets across 4 scans (peak count) — this is a reasonably large scan universe

**Base rate argument:** In 2 days of operation, we found 6 qualifying weather trades (5 wins + 1 loss). That's approximately 3 trades/day average. Today yielding 0 is 2 standard deviations below that tiny sample mean — but the sample is too small to be meaningful.

**What this means:** A single 0-trade day is insufficient evidence to conclude the threshold is too restrictive. However, combined with the observation that our winning trades clustered near the threshold floor (17-29% edge), a slight reduction to 12% is supported by the data.

---

## Summary Assessment

| Question | Finding |
|---------|---------|
| Is 15% too high? | Slightly — for NY/CHI only |
| Root cause of our weather loss | Degraded signal (Miami), not low threshold |
| Minimum viable threshold | 10% (spread erosion floor) |
| Recommended for NY/CHI | **12%** |
| Recommended for Miami | **15%** (or halted — per Loss Review rec) |
| Is 8% viable? | No — too close to spread |
| Is crypto at 10% internally consistent? | Questionable — crypto signal quality is lower |
| Today's 0-trade day | One data point; inconclusive |

---

## Recommendation for CEO + David (Flag Only — CEO Decides)

### Option A: Tiered threshold by signal quality *(Optimizer's preferred recommendation)*
- NY, CHI weather: lower to **12%** (net 10% EV after spread; validated signal)
- Miami weather: keep at **15%** until NWS restored + 10 settlement validations
- Crypto: consider raising to **12%** (signal quality does not justify 10% — flag separately)
- Fed/Econ: **12%** as implemented

**Expected effect:** On a day like today (36 markets, 0 above 15%), lowering to 12% for NY/CHI would likely add 1-4 entries depending on today's market pricing. This needs scanner diagnostic data to confirm.

### Option B: Uniform 12% across all modules
- Simpler. Easier to audit. Internally consistent.
- Lose the signal-quality differentiation — that's fine given crypto signal is arguably weaker.

### Option C: Keep 15% weather, investigate before changing
- Run scanner in diagnostic mode for 3-5 days at 12% threshold in shadow mode (log would-be trades without executing)
- Accumulate: if shadow trades at 12-15% edge are winning, lower the threshold
- Conservative approach, data-driven before committing

**Optimizer recommendation:** Option A (tiered), with Option C as the evidence-gathering path before implementation. Shadow mode for 3-5 days at 12% gives real data rather than this analysis reasoning from a 6-trade sample.

---

## Risk Summary

| Change | Risk | Magnitude |
|--------|------|-----------|
| Lower NY/CHI to 12% | More entries at thinner edge; model errors matter more | Low-Medium |
| Lower Miami to 12% | Degraded signal = fake edge; likely more losses | HIGH — don't do this |
| Lower to 10% | Acceptable but thin; requires calibrated model | Medium |
| Lower to 8% | Spread erosion; negative EV zone | HIGH — hard no |
| Keep at 15% | Miss legitimate 12-15% trades; leaves money on table | Low |

---

_Written by SA-1 Optimizer. Flagged for CEO review. No code changes recommended until CEO + David alignment._
