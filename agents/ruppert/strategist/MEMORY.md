# MEMORY.md — Strategist Long-Term Memory
_Owned by: Strategist agent. Updated after significant decisions, algo changes, or pattern discoveries._

---

## Algorithm Parameters (current)
- Weather direction filter: **RETIRED 2026-03-28** — both YES and NO now trade based on edge sign
- Fractional Kelly sizing — max tier 16% (80%+ confidence), graded down to 5% (25-40% confidence). Do not change without Optimizer proposal + David approval. See kelly_fraction_for_confidence() in strategy.py for full tier table.
- 95c rule + 70% gain exit — PRIMARY alpha source, do not tune without strong evidence
- Multi-model ensemble: ECMWF 40% + GEFS 40% + ICON 20%
- MIN_CONFIDENCE['weather'] = 0.25

## Optimizer State
- Bonferroni threshold: 0.05/6 = 0.0083
- Min dataset before proposals: 30 trades per module
- Frequency: monthly, or 30+ trades, or 3+ losses in 7 days
- Last run: never (dataset too small as of 2026-03-28)

## Key Decisions
- 2026-03-28: Weather NO-only filter retired. Both directions now allowed based on edge sign (David's decision).
- 2026-03-28: Same-day re-entry blocked in ruppert_cycle.py (Strategist decision)
- OPTIMIZER_* constants in config.py — all tunable thresholds centralized there

## Lessons Learned
- Confidence field was not logged before 2026-03-26 — old win-rate data by confidence tier is invalid
- Mar 13 loss (-$341): direction filter not enforced. Root cause: guard was skipped. Now fixed.

## 🔁 Deferred: Full Optimizer Engine (revisit when data is in)

**Context (2026-03-28):** optimizer.py is ~40% of what's needed as a full algo optimization engine.
Current gaps identified:
- No specific parameter values in proposals (says "raise min_edge" but not "to what")
- No parameter sweep / simulation against historical data
- No proposal → dev spec pipeline
- No proposal history tracking (optimizer_history.jsonl)
- Notification routing now handled via heartbeat ✅

**David's instruction:** Once domains start hitting 30+ scored trades, Strategist should:
1. Pull the actual optimizer_proposals_*.md output
2. Assess quality — are proposals specific enough? actionable?
3. Compare against the gap list above — what still needs to be built?
4. Write a follow-up spec only for what's actually missing based on real data

**Do NOT build the full engine spec preemptively — wait for real data first.**

## Watchlist / Open Questions
- Crypto sigmoid scale (1.0) is uncalibrated — autoresearcher will tune from live data (need 30 trades first)
- Brier score calibration not yet meaningful — need more scored outcomes

---

## ⏳ Pending Hypotheses — Needs Data
_Logged 2026-03-31. Reviewed from 133 corrected crypto_15m_dir trades (6 days post-bugfix). Sample is too thin for conclusions — log for future testing._

### Context: The Anomaly That Triggered These
Analysis of 133 corrected crypto_15m_dir trades found losses had **higher** avg edge (23.6%) and confidence (0.84) than wins (19.4%, 0.81). This is counterintuitive — higher signal quality correlating with worse outcome. Three hypotheses below attempt to explain this.

---

### Hypothesis 1: High Confidence = Betting Against Strong Market Consensus = Expensive NO Entry
**Theory:** When our model fires with high confidence saying DOWN, the market may already be pricing YES high (strong consensus UP). High confidence on our side correlates with expensive NO entry (70c+), which has asymmetric payoff against us — we risk 70c to win 30c.

**Implication:** Proposal A (payoff-aware NO scaling) already addresses this. Scaling down size at 70c+ entry implicitly manages the high-confidence-at-expensive-price risk without blocking the trade.

**David's note:** Going against market consensus CAN have huge payouts when we're right (asymmetric upside). The right answer is NOT to block these trades — it's to SIZE them correctly for the asymmetry. Proposal A (scale down, not block) is the correct approach.

**Data needed to test:**
- 30+ trades per confidence bucket (0.40–0.60, 0.60–0.80, 0.80+) with NO entry price logged
- Key question: Does confidence correlate with entry price in the loss set?

**Review trigger:** When we have 30+ trades per confidence bucket — approx May 2026 with current volume.

---

### Hypothesis 2: Short-Term Momentum Measures Brief Dips in Broader Uptrends
**Theory:** TFI/OBI/MACD detect real bearish momentum at entry time, but 15m windows settle on the FINAL price at close. A dip at T+0 may fully reverse by T+15. High edge at entry ≠ high probability of correct settlement outcome.

**David's new idea — Terminal Momentum Signal (T-2min scan):**
Scan/re-evaluate signal 2–3 minutes BEFORE settlement. If the terminal momentum signal contradicts the entry signal, exit early rather than hold to settlement. The terminal signal measures what the market is doing in the final minutes — a potentially stronger predictor of settlement outcome than the entry-time signal.

This is NOT an exit signal based on P&L — it's a signal-contradiction-based early exit:
- Entry signal said DOWN → terminal signal says UP → exit early
- Entry signal confirmed by terminal signal → hold to settlement

**Data needed to test:**
- Requires instrumenting TFI/OBI/MACD logging at T-2min for each open position (shadow data first — no trading decisions until we have enough logged data)
- Compare entry-time signal vs. terminal signal vs. settlement outcome across 100+ trades

**Review trigger:** Once T-2min shadow logging is instrumented and we have 100+ paired records — likely Q3 2026. Spec for shadow logging should be written before then.

---

### Hypothesis 3: Sample Size — The Edge/Confidence "Reversal" May Be Noise
**Theory:** 133 trades over 6 days is thin. The 4pp edge difference (23.6% vs 19.4%) between losses and wins is likely not statistically significant at the cohort level. Need 300+ trades per cohort for reliable conclusions.

**Action:** Do NOT change thresholds, confidence tiers, or edge filters based on this finding. Wait for sufficient data.

**Review trigger:** 300+ trades per cohort — approx Q3/Q4 2026 at current volume.

---

### Approved Proposals (Pending Spec → Dev)
- **Proposal A: Payoff-Aware NO Scaling** — scale down size at 70c+ NO entry price. Approved in principle. Spec → Dev when David gives the go.
- **Proposal B: Correlated Window Halt** — halt trading when multiple correlated windows show losses simultaneously. Approved in principle. Spec → Dev when David gives the go.

---

## 2026-03-31 Evening Session Update

### Crypto Win Rate Analysis (296 trades, Mar 30-31)

**Side Asymmetry — Most Important Finding:**
- NO side: **87.6% WR** — primary alpha engine
- YES side: **56.3% WR** — weak flank, needs gate filter

**Dead Zone:**
- 09:00 EDT: **38.9% WR** (18 trades) — strong candidate for skip gate. Do not trade this hour.

**Entry Price Sweet Spot:**
- 35–65c: **80–82% WR** — optimal range
- Below 35c: **57–65% WR** — avoid or downsize significantly

**Asset Win Rates:**
- ETH 79.5% | XRP 74.7% | DOGE 75.7% | BTC 70.3%

### Polymarket Decision
- **DO NOT wire into live signal weights yet**
- Shadow log Polymarket consensus + smart money at entry for 7 days
- Target: 200+ shadow trades → correlation analysis
- Primary use case hypothesis: YES-side gate filter (56.3% is the weak flank)
- Client: `agents/ruppert/data_analyst/polymarket_client.py`

### Analysis Tool
- `python scripts/data_toolkit.py winrate --module crypto_15m_dir --days 7 --by asset,hour,side`
- Use this for all win rate analysis — returns in <3s

### Capital at EOD: ~$13,146
