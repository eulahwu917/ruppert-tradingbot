# Strategic Proposal: T-Type Weather Markets
**Date:** 2026-03-30  
**Author:** Strategist (Ruppert)  
**Status:** RECOMMENDATION — Pending David Approval

---

## Executive Summary

**Verdict: Replace B-type entirely. Pivot to T-type as primary weather signal path.**

The B-type module is structurally broken — not because of bad models, but because we're betting on 1°F precision when our forecast RMSE is ±3-5°F. That's not a tuning problem; it's a category error. T-type markets solve this directly. With 10x+ the liquidity and a forgiving threshold structure, T-type is the right vehicle for the edge we actually have.

---

## 1. Replace or Add? → **Replace B-type entirely**

**Recommendation: Full replacement, not parallel operation.**

Rationale:
- B-type has a structural flaw that cannot be patched: we're asking a ±3-5°F model to pick 1°F bands. This is 10x overconfidence baked into the signal design. The model isn't broken — the market application is.
- Running B-type alongside T-type wastes capital on a losing structure. Every dollar in B-type is a dollar not in T-type.
- B-type liquidity is thin; T-type OI (34K+ on NYC alone) means we can actually size real positions.
- Clean break also simplifies the codebase — one weather module, one settlement mechanism.

**What happens to B-type?**
- Halt new B-type entries immediately
- Let existing positions settle naturally (don't force-exit)
- Archive the module; keep the code for reference

**Exception case:** If a future B-type market has extremely high conviction AND the band aligns with the model's point estimate ± <1°F, we could revisit selectively. But this is a rare exception, not a strategy.

---

## 2. Signals for T-Type — Does "Predicted Temp vs Threshold" Give Edge?

**Yes — but with caveats. The signal is real; the calibration work is non-trivial.**

### The Core Signal
Our ensemble produces a point estimate: `predicted_high = T°F`. The T-type market asks: "will the actual high be above/below threshold X?"

Signal formula:
```
margin = predicted_high - threshold
edge_exists = |margin| > calibrated_confidence_interval
```

Example: NYC threshold is 77°F. Our ensemble says 83°F. Margin = +6°F. With a ±3°F RMSE, P(actual > 77) is roughly 97%+ (z = 2.0). That's a real edge.

Contrast with B-type: "will it land in the 77-78°F band?" with 83°F prediction and ±3°F RMSE = ~12% probability. Terrible.

### What Makes T-Type Work
- **Direction + margin is enough.** We don't need precision; we need to be right about "above vs below" with comfortable margin.
- **Large margins = high edge.** When predicted temp is 8°F+ from threshold, we're in strong territory.
- **Small margins = pass.** When we're within ±2°F of threshold, the bet is a coin flip. Don't play.

### Signal Quality Framework

| Margin vs Threshold | Action | Notes |
|---|---|---|
| ≥8°F | Strong bet, full size | Z ≥ 2.7, P(win) > 99% |
| 5-8°F | Standard bet | Z ~1.7-2.7, P(win) ~95-99% |
| 2-5°F | Small bet or skip | Z ~0.7-1.7, P(win) ~75-95% |
| <2°F | **No bet** | Too close, coin flip territory |

**Key calibration step needed:** Convert our ensemble RMSE into a proper city-by-city, season-by-season confidence model. NYC in March may have different RMSE than Miami in July. This is the core model work.

### Additional Signals to Layer
- **NWS official forecast vs threshold:** If NWS point forecast also clears the threshold by >5°F, conviction increases.
- **Model agreement:** If all ensemble members agree on side of threshold, that's a high-confidence bet.
- **Climatological base rate:** Historical % of days where city high exceeds threshold this time of year. Use as prior, not primary signal.
- **Market implied probability vs our probability:** If Kalshi market shows 60% and our model says 85%, that's the edge. Bet the gap.

---

## 3. Sizing T-Type Trades

**Recommended sizing framework:**

### Starting Point (Conservative Phase — First 30 Days)
- Max per trade: $100
- Max daily weather exposure: $500 across all cities
- No leverage, no pyramiding

### Scaling Logic
- Start at $50 per trade for first 20 trades to build performance data
- If win rate > 70% after 20 trades, scale to $100 per trade
- If win rate > 80% after 50 trades, evaluate $200 per trade
- Hard stop: if 5 consecutive losses, pause and audit model

### Why We Can Size More Than B-type
- NYC T-type: 34K OI and 56K 24h volume = deep liquidity
- Our position sizes ($50-$500) are negligible vs market depth — no slippage concern
- We can actually get fills at fair prices, unlike thin B-type bands
- Multiple cities = natural diversification (5 cities × 2 thresholds = 10 potential daily markets)

### Correlation Risk
Weather in NYC and Chicago in March is somewhat correlated (same jet stream). Don't treat 5 cities as 5 independent bets. Effective independence factor: roughly 3-4 independent "bets" across 5 cities. Max daily exposure should account for this.

### Minimum Edge Threshold for Bet
- Only bet when our implied probability > market implied probability by ≥10 percentage points
- Example: if Kalshi shows 55% YES and our model says 75%, bet YES (20pp edge)
- If edge is <10pp, skip — the market already priced it in

---

## 4. T-Type vs NOAA Audit — Does Audit Become Less Urgent?

**The audit is still necessary, but the urgency changes.**

### Why the Audit Matters Less for T-Type
- T-type is forgiving of ±3-5°F RMSE — the main source of B-type failure is less fatal
- We don't need hyper-accurate point estimates; we just need to be on the right side of the threshold
- An 80% accurate directional model is good enough for T-type with margin filters

### Why the Audit Still Matters
- **Systematic bias > random error.** If our model consistently over-predicts NYC highs by 4°F, we'll get the direction wrong on below-threshold markets. Random error (RMSE) is fine; systematic bias is not.
- **City-specific calibration.** The audit should reveal whether our model is calibrated differently per city. A Miami model bias ≠ Denver bias.
- **Refines margin thresholds.** A good audit tells us our real confidence intervals, which lets us tighten the "minimum margin" rules in Section 2.

### Revised Audit Priority
- **Before the switch:** Audit for systematic bias only (1-2 days of work)
- **After 30 days of T-type trading:** Full audit using live performance data
- The full audit becomes a tuning exercise, not a life-or-death diagnostic

**Audit action items (pre-switch):**
1. Run ensemble backtests vs NWS actuals for last 90 days, per city
2. Calculate mean bias (not just RMSE) per city per season
3. Adjust point estimates for bias before computing threshold margins

This is lightweight. Don't let audit scope creep delay the T-type launch.

---

## 5. Recommended Next Steps — Build Order

### Phase 1: Stop the Bleeding (Do Immediately)
1. **Halt B-type entries.** No new positions. Let existing settle.
2. **Document the B-type post-mortem.** Lock in the lesson: precision mismatch = structural failure.

### Phase 2: Bias Audit (2-3 days)
3. **Run 90-day backtest** of ensemble point estimates vs NWS actuals, per city
4. **Calculate mean bias per city** — apply correction factors to point estimates
5. **Determine real RMSE per city** to calibrate margin thresholds

### Phase 3: T-Type Module Build (1 week)
6. **Scanner:** Query Kalshi KXHIGH series for T-type markets (upper + lower thresholds)
7. **Signal engine:** `margin = abs(predicted_high_bias_corrected - threshold)` → map to P(win)
8. **Edge filter:** Only flag when P(win) ≥ 75% AND market implied probability gap ≥ 10pp
9. **Sizer:** Apply sizing rules from Section 3
10. **Logger:** Track all bets with margin, city, threshold, predicted, actual, outcome

### Phase 4: Paper Trading (1 week)
11. **Run T-type module in paper mode** for 5-7 trading days
12. **Validate signal quality** — are high-margin bets actually winning?
13. **Check fill quality** — is the liquidity as good as OI suggests?

### Phase 5: Live Launch (After Paper Validation)
14. **Go live at $50/trade** for first 20 trades
15. **Review after 20 trades** — if win rate ≥ 65%, scale to $100
16. **Full performance review at 60 days**

---

## Risk Factors

1. **Weather markets are seasonal.** NYC in March is different from August. Model calibration may shift.
2. **Threshold prices move.** Just because OI is high doesn't mean the price will be fair when we enter.
3. **NWS reporting delay.** Settlement depends on next-morning NWS report — verify timing matches our expectations.
4. **Model drift.** If we're using a static ensemble, it may degrade. Plan periodic retraining checks.

---

## Decision Summary

| Decision | Recommendation |
|---|---|
| B-type fate | **Kill it. Halt immediately.** |
| T-type approach | **Add as sole weather module** |
| Primary signal | **Predicted temp vs threshold margin, bias-corrected** |
| Minimum edge | **≥8°F margin OR ≥10pp market implied probability gap** |
| Starting size | **$50/trade, max $500/day** |
| NOAA audit urgency | **Reduced — focus on bias detection only, skip full audit for now** |
| Build order | **Bias audit → T-type module → paper trade → live** |
| Timeline to live | **~2 weeks from approval** |

---

## Approval Required

David: Do you want to proceed with this plan? Specifically:
1. Approve halting B-type entries?
2. Approve T-type module development at the sizing/edge thresholds above?
3. Any changes to the build order or timeline?

One question at a time — what's your call on halting B-type first?
