# Optimizer Learnings Log
_Cumulative learnings from loss analysis. Each entry builds on previous context._
_Last updated: 2026-03-12 (evening)_

---

## 2026-03-12 Lesson: Directional Signal ≠ Entry Block

**What happened:** BTC reclaimed $72,000 today. BTC +2.3%, ETH +4.1%, XRP +2.5%. The bot sat out the entire day with zero crypto entries because the smart money signal read "bearish" and a bearish block was active. The block was removed mid-day (CEO + David approved), but the move was already done.

**The error:** The bearish block was treating a directional signal as a no-edge signal. These are not the same thing.

### Core lesson: Direction ≠ Edge

Our crypto contracts are **NO/high-strike** positions — we bet that BTC will NOT reach a high threshold by a given date. A bearish smart money signal actually *aligns* with NO contracts, not against them. But even when the signal is bullish (or wrong about direction), edge on a NO/high-strike contract can still exist if the Kalshi market is overpricing the probability of an extreme move.

**The correct mental model:**
- Smart money signal = directional bias indicator (where smart money thinks price is going)
- Edge = gap between our probability estimate and Kalshi's market price
- These are independent variables. Direction wrong ≠ edge gone.

**When a directional block makes sense:**
- For LONG contracts (YES on price increase): a bearish signal should reduce confidence, but not block entirely
- For NO/high-strike contracts (our primary type): a bearish signal actually SUPPORTS the position — it should *increase* confidence, not block it

**What we should block on:**
- Edge below threshold (<10%)
- Confidence below threshold (<50%)
- DVOL extreme / high uncertainty regime
- Band proximity conflicts (per prior learnings)
- Position limits / daily cap reached

**What we should NOT block on:**
- Smart money direction alone
- Any single signal reading without edge gate confirmation

### Estimated cost today

BTC/ETH/XRP all moved +2-4% bullish. Our NO/high-strike contracts on elevated price bands (e.g., NO on BTC >$80K by Friday) likely had genuine edge with Kalshi mispricing those probabilities. With 3 possible entries at standard sizing (~$25 each), estimated missed edge: **$15-40** depending on contract selection and edge magnitude. Not catastrophic at demo scale, but the pattern at live scale is unacceptable.

### Rule addition (for CEO review)

Recommend: Smart money signal should function as a **confidence modifier** (±10-15% on confidence score), never as a **binary entry gate**. The edge threshold gate (10% minimum) already prevents low-quality entries. A directional signal on top of that is refinement, not a veto.

---

## 2026-03-12 Loss Review

**Period:** 2026-03-10 to 2026-03-12
**Total realized losses reviewed:** -$31.48 across 4 losing trades
**Total wins in same period:** +$116.00 (estimated, 9 winning trades)
**Net context:** System is profitable, but loss patterns warrant attention.

---

### Loss #1: KXCPI-26AUG-T0.3 YES

- **What happened:** Manual entry at 33c, manually closed at 24c. Loss = -$3.42. Position was ~38 contracts (~$12.54 entry).
- **Root cause:** Manual trade with no documented edge calculation. Market was pricing YES at 33c (i.e., 33% probability CPI > 0.3% in August 2026). If bot edge requirement applies (10%), the model would need to believe fair value was ≥43%. No record of that calculation existing.
- **Learning:** Manual trades bypass the algorithm's edge gate entirely. There is no audit trail showing what edge was calculated before entry. The loss itself is small (-$3.42), but the *process failure* is the concern — not the magnitude.
- **Recommendation (for CEO review):** FLAG — Should manual CPI trades require a written edge calculation (even informal) before David approves? A discipline check: "What is my edge, and where does it come from?" before every manual entry.

---

### Loss #2: KXCPI-26NOV-T0.3 YES

- **What happened:** Manual entry at 37c, manually closed at 29c. Loss = -$1.36. Position was ~17 contracts (~$6.29 entry — smaller than standard sizing).
- **Root cause:** Same as Loss #1 — manual trade, no documented edge. Market was pricing YES at 37c (37% probability CPI > 0.3% in November 2026). Entry required believing fair value ≥47% for 10% edge.
- **Pattern note:** Both T0.3 CPI trades (AUG and NOV) entered near the same price band (33c-37c). Both lost. Both moved against us 8-9c before manual close. This suggests either: (a) the market was right and we had no genuine edge, or (b) we entered then lost conviction and closed before giving the trade time to develop.
- **Learning:** Premature manual close may have crystallized losses that could have recovered, OR the entry was speculative from the start. Without documented edge at entry, it's impossible to know which.
- **Recommendation (for CEO review):** FLAG — The two T0.3 trades suggest a pattern of entering CPI YES at ~35c without confirmed edge, then exiting when they move against us. This is not a systematic approach. Consider whether CPI module should require minimum documented edge before David even sees a recommendation.

---

### Loss #3: KXCPI-26JUN-T0.0 YES

- **What happened:** Manual entry at 77c, manually closed at 71c. Loss = -$1.92. Position was ~32 contracts (~$24.64 entry — near standard $25 sizing).
- **Root cause:** This is the most concerning of the three. At 77c, YES on CPI > 0.0% means the market priced a 77% chance CPI would be positive in June 2026. To have 10% edge, the model needed to believe this was ≥87% likely. Critically: the risk/reward is extremely unfavorable — risking 77c to profit 23c (3.35:1 capital at risk vs. gain). Even at 87% confidence, this is a poor bet from a Kelly perspective.
- **Learning:** High-probability, low-upside trades (>70c entry) have an unfavorable risk/reward profile for prediction markets. The 95c rule helps exit winners efficiently, but at 77c entry, there is only 23c of upside remaining. Any adverse move disproportionately damages the P&L.
- **Recommendation (for CEO review):** FLAG — Consider whether there should be a maximum entry price for YES/NO trades (e.g., flagging entries >65c as "limited upside" requiring explicit override). A 77c entry on a macro event means accepting a 3.35:1 loss-to-gain ratio.

---

### Loss #4: KXHIGHMIA-26MAR11-B83.5 NO

- **What happened:** Bot entered NO at ~42c on 2026-03-10 (source=bot/weather). Miami's actual high on March 11 exceeded 83.5°F. Trade settled YES, fully against our NO position. Estimated loss: -$24.78. This is the largest single loss in the review period — ~6.2× larger than the three CPI losses combined.
- **Root cause (multi-factor):**
  1. **NWS layer disabled for Miami.** `team_context.md` explicitly notes "Miami NWS grid (MFL 110,37) returns 404 → NWS layer disabled for Miami." The signal was running on GEFS ensemble alone, without NWS verification that other cities use. This is a known degraded-signal condition.
  2. **Miami bias correction under-validated.** The +4°F bias correction for Miami was based on 1 day of backtest data (per `optimizer.md` 2026-03-11 entry: "Miami bias correction (+4°F) is based on 1 backtest day only — insufficient"). Previous settlement KXHIGHMIA-26MAR10-B84.5 also lost to Miami heat. That's 2 consecutive Miami losses to warm temperatures, suggesting the bias correction is systematically insufficient.
  3. **Entry at 42c = near-threshold pricing.** NO at 42c means the market was already pricing 58% chance the temperature WOULD exceed 83.5°F. The bot disagreed and thought NO had >57% probability (42c + 15% edge). But market-implied 58% YES suggests 83.5°F was a genuinely contested threshold — the market was not pricing this as a comfortable NO.
- **Learning:** Miami is a problem market for the weather module. Two sequential losses, NWS layer down, bias correction unvalidated. The signal quality is demonstrably lower than NY/Chicago, yet the bot is sizing Miami positions at full standard size ($24.78 is near the $25 cap).
- **Recommendation (for CEO review):** FLAG — Two options worth CEO evaluation: (a) halt Miami weather trades until NWS layer is repaired and bias has 10+ settlement data points, or (b) apply a Miami-specific position size reduction (e.g., 50% of standard size) while the signal is degraded. Do NOT simply raise the edge threshold without fixing the underlying data problem.

---

### Loss #5 (Embedded Paradox): Miami B85.5 vs B83.5

- **What happened:** On the same day (March 11, 2026), the bot held TWO Miami NO trades at different temperature bands:
  - B85.5 NO: **Won** (+$11.47, exited via 95c rule)
  - B83.5 NO: **Lost** (-$24.78, settled YES)
  - Miami's actual high: somewhere between 83.5°F and 85.5°F (above B83.5 threshold, below B85.5 threshold)
- **Root cause — Band Selection Logic:** The bot selected both as valid NO trades simultaneously. But these bands have asymmetric risk profiles:
  - B85.5 is a more conservative threshold — requires a more extreme warm event to lose
  - B83.5 is a near-threshold bet — only 2°F from B85.5, but much closer to the market-implied range
  - B83.5 NO at 42c = market saying 58% chance it gets exceeded (contested)
  - B85.5 NO likely entered at a lower price (higher NO probability = market more confident it wouldn't reach 85.5°F)
- **The paradox in dollar terms:** We lost -$24.78 on B83.5 while winning +$11.47 on B85.5. Net on Miami: -$13.31. If we had only entered B85.5 (the more conservative band), we would have netted +$11.47.
- **Learning:** The bot is simultaneously entering trades where one protects the other. When B85.5 hits 95c (market is certain high < 85.5°F), B83.5 may already be losing (high is between 83.5 and 85.5). The trades are **anti-correlated in outcome** — entering both creates a situation where we hedge ourselves while paying full cost for both positions.
- **Recommendation (for CEO review):** FLAG — Consider whether the weather module should apply a "band proximity rule": if entering multiple NO bands on the same city/date, only take the most conservative (highest threshold) band, or cap at one band per city per day. The current behavior of entering adjacent bands creates correlated risk — if the temp hits 83.5°F, it's likely to be near 85.5°F too (and vice versa for exits).

---

### Overall Pattern

**1. Manual vs. Bot discipline gap is real.**
All 3 CPI losses are manual trades. All 9 wins are bot trades. This is not coincidental — the bot enforces edge requirements, entry sizing, and exit rules. Manual trades have none of these guardrails. The CPI losses total only -$6.70, but they represent a pattern of entering without documented edge. If this behavior scales (larger positions, more frequent manual trades), it becomes a meaningful drag.

**2. Miami is a structurally degraded signal.**
Both Miami-specific losses (March 10 and March 11) trace back to the same root cause: NWS layer down + insufficient bias calibration. This is a known issue being traded through at full position size. The Miami losses total -$24.78 (March 11 alone) plus the March 10 loss from the prior review. Miami has now lost twice in a row. The bot's GEFS-only signal for Miami is not performing.

**3. The exit strategy is working — don't touch it.**
Every single win used either the 95c rule or 70% gain exit. No wins required holding to settlement. This is important: the exit strategy is the single most consistent source of alpha in the system. It captures gains early, avoids settlement-binary risk, and prevents winners from turning into losers. This pattern should be preserved and prioritized in any future tuning.

**4. Near-threshold entries carry hidden tail risk.**
B83.5 at 42c (market: 58% YES) is a near-threshold bet. The market was essentially saying "flip of a coin, slightly toward warm." Entering these at full position size concentrates loss risk. The bot's 15% edge requirement theoretically protects against this, but with a degraded Miami signal, the edge calculation may be systematically overestimating NO probability.

**5. High-priced YES entries (>65c) have poor risk/reward.**
The 77c CPI YES trade illustrates a structural issue: at that price, max upside is 23c, max downside is 77c. Even with genuine edge, the Kelly-optimal size would be very small. Entering at near-standard sizing ($24.64) is inconsistent with the asymmetric payoff.

---

### Priority Recommendations

1. **HIGH: Halt or size-reduce Miami weather trades until NWS layer is restored and 10+ settlements validate bias correction.** Two consecutive Miami losses with a known degraded signal is a clear risk management issue. Data: -$24.78 loss on March 11 alone from a signal that `team_context.md` explicitly flags as impaired.

2. **HIGH: Manual CPI trades must document edge before entry.** Even a one-line note: "Edge: model says 55%, market at 37%, edge = 18%." Without this, manual trades are speculative, not systematic. Data: 3/3 manual CPI trades lost; 9/9 bot trades won.

3. **MED: Investigate band proximity rule for weather.** Entering adjacent NO bands on same city/date creates anti-correlated positions where one offsets the other. On March 11, B85.5 partially offset B83.5, but the net was still -$13.31. A single B85.5 trade would have returned +$11.47. Data: entering B83.5 + B85.5 simultaneously cost $13.31 more than B85.5 alone.

4. **MED: Flag entries above 65c as "limited upside" requiring explicit justification.** At 70c+, max remaining profit is ≤30c against full downside exposure. Kelly-optimal sizing at these prices is a fraction of standard. Data: KXCPI-26JUN-T0.0 at 77c risked 77c to gain 23c (3.35:1 unfavorable).

5. **LOW: Review CPI directional bias.** All 3 manual CPI trades were YES (CPI elevated). Confirm this reflects genuine model signal vs. macro confirmation bias. If David consistently enters CPI YES without documented bearish alternatives considered, this should be flagged as a selection bias.

---

_Next review: after Friday 2026-03-14 demo period ends and first live-trade settlements are logged._

---

## 2026-03-12 Intraday Learning — Bearish Block Cost

**Event:** BTC reclaimed $72,000 on 2026-03-12. ETH +4.1%, BTC +2.3%, XRP +2.5% on the day.

**What happened:** Smart money signal read "bearish" all day. The bearish block (`drift_sigma = -0.6`) was active → bot placed 0 crypto trades across 3 scans (7am, 12pm, 3pm).

**The error:** "Bearish" smart money signal ≠ "no edge." The bot was looking for NO/high-strike contracts (betting price stays below a threshold). In a bullish market, high-strike NO contracts *still have edge* — the market may underprice how high price will go. Blocking on direction signal conflated two independent questions: (1) which direction is price moving? and (2) is the Kalshi market mispriced?

**Real cost:** 3 missed scan windows on a +4% ETH day. Estimated 2-3 viable entries not taken.

**Fix applied:** Bearish block removed 2026-03-12 (CEO + David approved). `drift_sigma` now hardcoded to 0.0.

**Lesson for future Optimizer reviews:**
- Direction signal is useful context, NOT a gate. It belongs in the trade note/log, not the entry condition.
- A signal being "wrong" on direction does not mean no edge exists — these are independent.
- Smart money "bearish" with 5/9 wallets still placeholder = low-confidence signal. Don't let low-confidence signals block high-confidence edge calculations.
- Flag any future "direction = block entry" logic as HIGH priority for review.
