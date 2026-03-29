# SA-1 Optimizer — Scope Validation Report
_Date: 2026-03-12 | Authored by: SA-1 Optimizer_
_Status: Complete — for CEO review before David presentation_
_Validating: researcher_scope_2026-03-12.md_

---

## Summary

Researcher report is high quality. Data sources are legitimate. Most recommendations hold up. However, three critical issues were found that must be resolved before building the Fed module, and two recommendations require modification. Nothing warrants a full hold. Overall verdict: green-light the cheap stuff now, build Fed module only after addressing the operational gaps.

---

## Fed Rate Decision — MODIFY (not PROCEED)

**Verdict: Do not build v1 as scoped. Three blockers found. Redesign before development.**

### Issue 1: Scan timing cannot capture the primary edge window — CRITICAL

**The finding:** CPI and NFP release at 8:30 AM ET = **5:30 AM PT**. The documented edge window is 30-60 minutes after print = 6:00–6:30 AM PT. Our scan schedule runs at 7am, 12pm, 3pm, and 10pm PT.

**The problem:** By the time our 7am scan runs, the 30-60 minute post-print window has fully elapsed. The FedWatch probabilities will have already repriced; Kalshi will have largely caught up. We arrive after the party ends.

**What this means:** The primary edge thesis — exploiting the Kalshi lag after CPI/NFP prints — **requires a calendar-triggered scan, not the existing schedule.** A new task that fires at 5:30 AM PT on CPI/NFP release days (typically 2nd-3rd Wednesday of each month for CPI, first Friday for NFP) is a prerequisite. This is a non-trivial scheduling change that requires CEO + David approval.

**Workaround:** The secondary edge windows (2-4 weeks before meeting, when dot plot or speech surprises the market) ARE capturable by the existing schedule — those are slow-moving repricing events. These are lower magnitude (1-5¢ vs 5-15¢) but more compatible with our current architecture.

**Recommendation:** Scope v1 as a secondary-window-only strategy (works within existing scan schedule). Design v2 as calendar-triggered. Do not promise primary-window access in v1.

---

### Issue 2: CME FedWatch EOD is insufficient for the primary edge — CRITICAL

**The finding:** EOD API = yesterday's closing probabilities from 30-Day Fed Funds futures. On the morning of a CPI print, we'd be holding T-1 day probabilities while the market reprices in real-time.

**The problem:** For the 30-60 minute post-print window, we'd be comparing stale FedWatch probabilities against live Kalshi prices. We might see an "edge" that no longer exists, or miss one that does exist, because our reference data is 12+ hours old.

**FRED ZQ workaround (as proposed by Researcher):** FRED typically has a 1-business-day lag on daily series. It does NOT provide real-time intraday futures pricing. The FRED workaround will NOT solve the intraday window problem.

**Actual solutions:**
- CME intraday API: custom pricing from CME sales (enterprise cost, likely >$25/mo)
- Scrape CME FedWatch webpage directly on print days (free, but requires parsing; webscraping is fragile)
- Quikbase / Quandl / alternative data providers: may have real-time ZQ data at lower cost

**For the secondary-window strategy (slow repricing over days/weeks):** EOD data IS sufficient. If the edge develops over days, T-1 close is adequate to capture it. This is another reason to scope v1 as secondary-window-only.

**Recommendation:** v1 uses EOD. Clearly document that the 30-60 minute CPI/NFP window is out of scope for v1. Intraday access deferred to v2.

---

### Issue 3: "Day before meeting = efficient" means our 10pm scan is low-value for Fed — MEDIUM

**The finding:** The Fed Reserve study (Diercks, Katz, Wright, February 2026 — confirmed real and credible) specifically found that Kalshi achieves a "perfect forecast record" **the day before FOMC meetings** with "statistically significant improvement vs. Fed Funds futures." This is the most-efficient point in the cycle for Kalshi. Spreads compress to <3¢.

**The problem:** Our 10pm scan runs every day, including nights before FOMC meetings. At that point, the market is fully priced in. We'd be seeing near-zero edge on all Fed contracts. This is NOT where we should be looking.

**Opportunity framing:** The study confirms the edge exists EARLIER in the cycle, when Kalshi is still repricing from recent macro data. Our 10pm scan is most useful 2-6 weeks before a meeting when the market is "digesting" incoming macro prints.

**Recommendation:** When Fed module is live, add contract age filter: skip Fed contracts within 48h of FOMC meeting. Trade only contracts >48h from the decision date.

---

### Issue 4: KXFEDDECISION multi-outcome structure — CLEAN (no issue found)

**The finding:** KXFEDDECISION offers 4 outcomes: Maintain / Cut 25bps / Cut 50bps+ / Hike. Each outcome has its own YES/NO binary contract.

**Assessment:** Our existing edge model (prob vs market price) applies cleanly. Compare FedWatch probability for outcome X vs Kalshi YES price for outcome X. If FedWatch says 75% Hold and Kalshi prices Hold-YES at 63¢ → 12¢ raw edge. Standard model.

**One nuance:** All outcome probabilities sum to 1.0 (on FedWatch) and separately all Kalshi YES prices approximately sum to 1.0 (Kalshi enforces this via settlement). No new modeling required. We select the single highest-edge outcome to trade, same as current approach for other modules.

**Verdict:** No modeling changes needed for contract structure.

---

### Issue 5: Is the edge thesis fundamentally credible? — YES, with caveats

**What the research confirms:**
- Fed Reserve study (Feb 2026): Kalshi CPI forecasts "statistically significant improvement" over Bloomberg consensus
- Same study: Kalshi prediction markets "can lag on sudden repricing" (direct confirmation of arbitrage window)
- Cross-platform arbitrage bots reportedly generated ~$40M profits Apr 2024–Apr 2025 (millisecond-speed, institutional)
- Favorite-longshot bias confirmed in prediction markets (avoid <10¢ contracts) — Researcher correctly flagged this

**What the research does NOT confirm:**
- The specific "5-15¢ edge in 48h window after print" claim. This is Researcher's synthesis, not a directly cited figure. The logic is sound but I could not verify this specific range independently. Treat it as a plausible estimate, not an established constant.
- "Shock alpha study (Kalshi Research)" — I could not confirm the source. May exist internally at Kalshi but isn't a published paper. Treat as plausible not confirmed.

**Kalshi liquidity in the post-CPI window:** The Researcher correctly notes SIG as institutional market maker with 100,000+ contracts depth and 2-3¢ spreads. However, during fast repricing events (first 30 minutes after CPI print), spreads can temporarily widen as market makers reprice. Slippage risk is real in that window. HRRR: For a $25 entry size, even 5¢ of slippage on a $25 position = $1.25 cost. Still profitable at 10¢+ edge. This is manageable.

**Overall Fed verdict:** Edge thesis is real. Implementation gaps are blockers for v1 as scoped. Modified v1 (secondary window only, EOD data, existing scan schedule) is buildable and has positive expected value — but smaller edge than the primary post-print window.

---

## Quant Research Section — Fed Prediction Market Edge

### Federal Reserve Study (Diercks, Katz, Wright — February 2026)
_Confirmed real, published at federalreserve.gov/econres/feds/files/2026010pap.pdf_

**Title:** "Kalshi and the Rise of Macro Markets"

**Key findings relevant to our edge:**
1. Kalshi headline CPI forecasts outperform Bloomberg consensus with statistical significance
2. Kalshi Fed rate decision markets achieve "perfect forecast record" on the DAY BEFORE FOMC meetings — confirming the day-before market is fully efficient (no edge there for us)
3. Kalshi provides "high-frequency, continuously updated" data vs. survey methods — confirms the real-time update advantage
4. Paper notes Kalshi "can lag on sudden repricing" — direct academic validation of our arbitrage window thesis

**Edge sizes (not directly quantified in study):** The study measures forecasting accuracy, not exploitable edge vs. FedWatch. Edge sizing (5-15¢) is inferred, not from this paper.

**Important caveat:** This is a Fed staff working paper, NOT an official Federal Reserve opinion or policy statement. "Does not reflect official opinions of the Federal Reserve itself." Credible but not an institutional endorsement.

### Structural Market Context
- Funding rate arbitrage bots between Kalshi and Polymarket: ~$40M profits in 12 months (Apr 2024–Apr 2025)
- Cross-platform Kalshi/Polymarket arb windows: 2-4 seconds (millisecond-speed, not relevant to our approach)
- Kalshi/FedWatch divergence window: 30-60 minutes (human/bot-speed, relevant to our approach)
- The structural difference: institutional futures traders (FedWatch participants) reprice faster than Kalshi retail/semi-institutional market

### Favorite-Longshot Bias (confirmed in literature)
- Contracts priced <10¢ win less than implied probability
- Contracts priced >80¢ win more than implied
- **Action:** Avoid buying Fed contracts below 10¢ (including speculative Cut 50bps+ bets). Trade mainstream outcomes only.

---

## Weather Additions — PROCEED with one caveat

**Verdict: PROCEED. All three additions are validated. Flag the commercial use caveat on Open-Meteo.**

### ECMWF via Open-Meteo — CONFIRMED FREE, with one catch

**Verification:** Confirmed accurate. ECMWF achieved fully open data status October 1, 2025, releasing its entire Real-time Catalogue under Creative Commons CC-BY-4.0 license. Open-Meteo is providing ECMWF IFS data at full native resolution under this policy.

**The catch the Researcher missed:** Open-Meteo's free tier is explicitly for **non-commercial use** (< 10,000 API calls/day). For commercial use, users must contact Open-Meteo directly. A trading bot is a commercial application. We are likely in a gray zone right now, or technically violating terms.

**Resolution options:**
a) Open-Meteo's commercial tier is affordable (~$50–100/mo range based on public pricing pages) — verify before building
b) Use ECMWF open data directly (the raw data is genuinely free under CC-BY 4.0); more engineering effort
c) Contact Open-Meteo to confirm our usage is permissible

**This should not block the build** — commercial plans exist and are cheap. But Developer should confirm this before hitting production.

**Resolution claim:** Researcher says "9km native resolution." More precisely: as of Oct 2025, Open-Meteo provides 9km access. ECMWF's own open data is currently 25km real-time; 9km arrives in 2026 with 2-hour latency. Open-Meteo may be providing 9km via a different access arrangement. For our purposes (weather forecasting for US cities), this is a minor distinction — both are far better than GFS (28km). Not a blocker.

**15-20% accuracy improvement claim:** This is consistent with well-documented ECMWF vs. GFS comparisons in academic literature, particularly at 3-7 day range. Legitimate claim. Worth the switch.

---

### Combining ECMWF + ICON (3 ensemble members) — Sound approach, verify weight assumptions

**Is more always better?** In ensemble theory: yes, if models have independent error structure and are well-calibrated. ECMWF, GFS, and ICON are developed independently with different assimilation methods — their errors are not perfectly correlated. Adding ICON provides additional independent information.

**Proposed weights (Researcher):** ECMWF 40%, GFS/GEFS 25%, HRRR 25% (<24h only), ICON 10%

**Assessment of weights:**
- ECMWF at 40% is appropriate — it is the best medium-range model. This is consistent with WMO skill scoring.
- HRRR at 25% for <24h is aggressive but defensible. HRRR is the best short-range US model. However: HRRR is initialized from GFS/RAP — it's not fully independent from GFS for forecasts >6 hours. The 25% GFS + 25% HRRR allocation for <24h forecasts effectively concentrates weight in GFS-family models.
- ICON at 10% is reasonable for a corroboration signal.

**Practical concern:** These weights are not validated against our specific target cities or Kalshi market accuracy. They're theoretically sound but should be treated as starting defaults to be tuned. The "divergence >4°F = reduce size" rule is the right fallback when ensemble members disagree — this is more important than getting the exact weights right initially.

**Verdict:** Weights are reasonable starting defaults. The decision rule (ECMWF+GFS agreement = high confidence, divergence >4°F = smaller size) is more important operationally. Build with these weights, tune after 20+ settlements.

---

### NOAA GHCND for Bias Correction — PROCEED, caveats noted

**Is 20-30 year station data better than current approach?** Yes, definitively. Our current bias corrections are based on 1-3 days of backtest data (per prior optimizer notes — Miami's +4°F is from 1 backtest day). That's not a statistical sample; it's a guess.

**GHCND approach:** Pulling 20+ years of TMAX per station and computing monthly average bias vs. model forecast output is textbook statistical calibration. This is how NWS and private forecasters build their bias corrections. Legitimate methodology.

**Caveats (Researcher did not fully address):**
1. **Station moves:** Many NOAA stations have been relocated over 50 years, introducing discontinuities. Use the closest current station, not a historical composite.
2. **Urban heat island drift:** Cities like Miami and NYC have warmed 1-2°F beyond regional background over 30 years due to development. A 30-year mean will be slightly cooler than current baseline. Mitigate: use 10-15 year recent data, not 30-year mean, OR use temperature anomaly (deviation from period mean) rather than absolute correction.
3. **Model resolution shift:** Bias vs. GFS-28km is different from bias vs. ECMWF-9km. Once we switch to ECMWF as primary, recompute biases against ECMWF output specifically.
4. **Monthly stratification required:** Seasonal bias varies significantly. Summer Miami vs. Winter Miami are different biases. Monthly splits are essential, not optional. Researcher implies this but it should be explicit.

**Priority:** This directly fixes the Miami problem identified in the loss review. Miami has had 2 consecutive losses from a structurally degraded signal. GHCND bias correction is the highest-priority fix in the weather module.

**Verdict:** PROCEED. Use 10-15 year recent data window with monthly stratification. Compute against ECMWF output (not just GFS) once ECMWF is live.

---

## Crypto Additions — MODIFY

**Verdict: All three additions are worth adding, but each has important caveats the Researcher understated.**

### Funding Rates as Contrarian Signal — PROCEED with modification

**Literature validation:** Confirmed. Well-established in academic and practitioner literature. Key quantitative finding: funding rate changes explain ~12.5% of 7-day price variation (Presto Labs research). Structural bias: BTC funding is positive 92% of the time (BitMEX Q3 2025 study) — meaning elevated positive funding is extremely common; only extreme extremes are signal.

**What the Researcher got right:**
- Threshold calibration (>0.05% elevated, >0.10% extreme) is reasonable
- Contrarian interpretation (extreme positive = longs crowded = correction risk) is correct
- Free API access on Binance and Bybit: confirmed

**What the Researcher understated:**
1. **Trailing indicator problem:** Research shows funding rates frequently act as a trailing indicator, not leading. They reflect existing leverage, which is already priced into momentum signals we have. High funding during a bull run doesn't mean reversal is imminent — it can stay high for weeks.
2. **92% positive structural bias:** Our threshold calibration must account for this. If positive funding is the norm, flagging >0.05% as "elevated" will fire constantly and add noise. The threshold should be benchmarked against rolling 30-day average, not absolute level. Flag funding that is X standard deviations above recent norm, not just above absolute threshold.
3. **Independent signal concern:** Our existing crypto module uses EWMA vol and multi-TF RSI. These capture the same leveraged-long-market state through price. Funding rate as a CONFIRMING signal is useful; as an independent signal it partially overlaps.

**Required modification:** Use funding rate as a CONFIRMATORY signal only (not independent trade trigger). Its highest value is when it confirms momentum direction — e.g., negative funding + positive RSI momentum = higher confidence long signal. Also normalize against rolling baseline, not fixed threshold.

---

### Deribit DVOL as Volatility Filter — PROCEED with important caveat

**Does high IV reduce win rate on our NO/high-strike contracts?**

This is the key question and the Researcher's answer is only half-correct. The Researcher says "DVOL > 80 = reduce confidence." That's reasonable but misses the other direction.

**Our specific contracts:** We trade NO on high-strike crypto price thresholds. Example: NO on "Will BTC reach $115,000 by Friday?" If BTC is at $96K, we're trading that it won't gain 20% in a week.

**Effect of high IV on our positions:**
- High DVOL means options market prices wider distribution of outcomes
- For a NO contract on a high strike: high IV actually makes the YES option (the far OTM call) worth MORE in options terms
- This means Kalshi should be pricing YES HIGHER during high IV environments
- If Kalshi is slow to update: **high IV may create MORE mispricing in our favor on NO contracts**, not less
- The Researcher's recommendation (DVOL >80 = reduce confidence) might be backwards for our specific strategy

**But there's a legitimate concern:** High volatility = realized outcomes diverge more from model predictions. Even if our edge estimate is correct, high vol environments produce more "tail events" (sudden pumps) that can blow out NO positions. This is variance risk, not edge erosion.

**Revised recommendation:** DVOL should inform position SIZING (reduce size in high-vol regime = lower variance), not confidence (don't necessarily reduce edge estimate). The distinction matters: we may have MORE edge in high-vol environments, but take SMALLER positions due to outcome variance. Consider: DVOL >80 → halve position size, keep full edge estimate.

**Also add:** DVOL floor effect — extremely low DVOL (<40) means market doesn't expect significant moves. This is UNFAVORABLE for us — our NO contracts on high strikes are essentially "free money" at low vol, but the market will price them efficiently (very low YES price = our edge may already be priced in).

---

### Fear & Greed Index — PROCEED with reduced weight

**Is it independent from our existing signals?**

**Partially independent — but less than Researcher implies.**

Components breakdown:
- Volatility (25%): Derived from BTC price history → **overlaps significantly with our EWMA vol**
- Market Momentum/Volume (25%): BTC price/volume vs. 30/90d averages → **overlaps significantly with our multi-TF RSI and magnitude momentum**
- Social Media (15%): Twitter sentiment → partially independent
- Surveys (15%): **CURRENTLY PAUSED** — this component is inactive
- Dominance (10%): BTC market cap % → partially independent
- Google Trends (10%): Search volume → independent

**Effective independence analysis:** ~50% of the score (volatility + momentum) is derived from the same price data that drives our existing signals. With surveys paused, the truly independent component is ~35-40% of the score. The F&G Index is not as independent a signal as described.

**Still worth adding?** Yes, but with reduced expectations. The social + trends + dominance components do add some marginal information. The implementation cost is trivially low (1 API call/day). Value is in extreme readings only (0-20 extreme fear, 80-100 extreme greed) — mid-range readings add noise.

**Recommended weighting:** Cap its influence at ±5% confidence modifier (not ±10% as implied by Researcher). Apply only at extreme readings. Document explicitly that it partially overlaps with existing momentum signals.

---

## Overall Priority Ranking (what to build first)

### Tier 1 — Build immediately (free, high impact, low risk)
All three of these can go to Developer in one batch:

**1. ECMWF + ICON via Open-Meteo**
- Directly fixes the weather signal quality gap
- Directly helps with Miami (ECMWF excels at coastal/maritime)
- Low implementation effort (add `model=` parameter to existing Open-Meteo calls)
- Blocker: Confirm commercial use terms with Open-Meteo before hitting production
- Estimated impact: +15-20% weather accuracy on 3-5 day contracts

**2. GHCND Bias Correction Rebuild**
- Directly addresses the #1 loss cause from the 2026-03-12 loss review (Miami degraded signal)
- Replaces ad-hoc corrections based on 1-3 days with statistically robust monthly calibrations
- Requires data engineering (NOAA API pull, 10-15 years per city) but no model changes
- Must be computed against ECMWF output once ECMWF is live (two-step: add ECMWF first, then rebuild biases)

**3. Funding Rates (Binance + Bybit)**
- Free, clean signal, zero cost
- Modify to use rolling baseline normalization (not fixed threshold)
- Confirmatory signal only — wire into crypto_client.py

### Tier 2 — Build next sprint (still free, moderate complexity)

**4. Deribit DVOL**
- Free, well-validated
- Modify to inform position SIZING rather than confidence estimate
- DVOL >80 → halve size; DVOL <40 → flag as potentially well-priced-in
- Low-medium implementation effort

**5. Fear & Greed Index**
- Trivial implementation (1 API call/day)
- Reduced scope: ±5% modifier at extreme readings only
- Worth doing but very low priority vs. items above

### Tier 3 — Scope separately, significant prerequisites required

**6. Fed Rate Decision Module (v1, secondary window only)**
- Not ready to build as originally scoped
- Prerequisites before Developer touches this:
  - CEO + David agree on: secondary-window-only v1 scope (no CPI/NFP real-time needed)
  - CEO + David decide: calendar-triggered v2 scan timing (requires Task Scheduler change)
  - CME EOD API: $25/mo needs David's spending approval (spending real money = David approves)
  - Add FOMC calendar to config (scheduled meeting dates) + "48h exclusion" rule
- Estimated timeline: Build after Friday review, after live trading approved
- High ceiling potential ($25/mo cost, multi-contract liquid market) but needs proper scoping first

---

## Flags for CEO / David

| Flag | Severity | Description |
|------|----------|-------------|
| Open-Meteo commercial use | MEDIUM | Trading bot may not qualify for free tier. Confirm terms before going live with ECMWF/ICON. |
| Fed v1 scan timing gap | HIGH | 30-60 min post-CPI edge window unreachable with current schedule. Scope v1 as secondary-window-only. |
| CME API spend approval | LOW | $25/mo requires David's explicit approval before subscribing. |
| GHCND bias recompute | HIGH | Must recompute biases against ECMWF output AFTER ECMWF goes live — doing it now vs. GFS would produce stale corrections. |
| Funding rate threshold | MEDIUM | Fixed absolute threshold (>0.05%) is noisy given 92% structural positive bias. Must use rolling baseline normalization. |
| Fear & Greed overlap | LOW | ~50% overlap with existing price signals. Reduce expected impact accordingly. |

---

_Validation complete. Researcher's scope report is high quality and buildable with the above modifications. Recommend CEO review before Developer is engaged on Fed module. Weather + crypto additions can proceed to Developer immediately._
