# Strategy Recommendations — 2026-04-01

Author: Strategist Agent
Status: RECOMMENDATION (pending David approval)

---

## 1. Stop-Loss for Crypto 15m Binary Contracts

### Current State

- 412 trades across 7 days. 329 exited via rules (95c / 70% gain) at 100% win rate.
- 83 reached settlement: 75 total losses (settled at 1c), 8 wins (settled at 99c). Settlement win rate = 9.6%.
- Active exits generate ~$47K; settlement losses cost ~$6.5K. Net P&L = ~$41K.
- No per-position stop-loss exists today. Only defense is the 3-consecutive-loss circuit breaker.

### Is 80% the Right Threshold?

**No. 80% is too loose for 15-minute binary options.** Here's why:

Binary options have a non-linear payoff. A contract bought at 55c that drops to 11c (80% loss) has almost certainly lost — the market is pricing the outcome at 89% against you with only minutes left. There's no recovery path like equities.

However, an **aggressive stop-loss on 15m binaries is also wrong** because:

1. **Price is not linear with time.** A contract at 55c can swing to 30c and back to 95c within 5 minutes on a single candle reversal. Binary option mid-prices are extremely volatile mid-window.
2. **Bid-ask spread penalty.** Exiting early on Kalshi means hitting the bid. Typical YES bid/ask spread is 3-8c. Selling a losing position at 30c bid when the "true" price is 35c costs 5c on top of the loss.
3. **Expiry at 0 vs early exit at 10c.** If you sell at 10c, you recover 10c but pay ~0.2c taker fee. If you hold to expiry at 0, you lose the full amount but pay no exit fee. The 10c recovery minus fees = ~9.8c saved. That IS worth it.

### Recommended Approach: Time-Gated Value Stop

**Don't use a pure price-based stop. Use a time + price hybrid.**

| Window Elapsed | Stop Trigger | Action |
|---------------|-------------|--------|
| 0–5 min | No stop | Too early; price noise dominates |
| 5–10 min | Position value < 20% of entry | Exit at market (sell at bid) |
| 10–13 min | Position value < 35% of entry | Exit at market |
| 13–15 min | No stop | Too close to expiry; spread cost > recovery |

**Why these numbers:**

- **20% threshold at 5-10 min:** If you bought at 55c and the contract is now at 11c with 5-10 minutes remaining, there's an 89% implied probability against you. Recovery requires a full reversal in the underlying AND enough time for Kalshi price to reflect it. Expected value of holding: ~11c × P(reversal) ≈ 2-4c. Expected value of selling: ~9-10c (bid minus fees). Selling wins.
- **35% threshold at 10-13 min:** With only 2-5 minutes left, even a 35% value (19c on a 55c entry) signals the market has high conviction against you. Less time for reversal = higher bar for holding.
- **No stop after 13 min:** With <2 minutes left, the bid-ask spread widens dramatically (market makers pull quotes). You'd sell at a terrible price. Better to let it settle.

### Concrete Implementation

```
STOP_LOSS_ENABLED = True
STOP_LOSS_RULES = [
    {"elapsed_min": 5,  "elapsed_max": 10, "value_pct": 0.20},
    {"elapsed_min": 10, "elapsed_max": 13, "value_pct": 0.35},
]
```

**Expected P&L impact on historical data:**

- Of 75 settlement losses, ~45-50 would have triggered the stop between 5-13 min.
- Average entry on losers: ~55c. Average stop exit: ~15c (vs 1c at settlement).
- Recovery per stopped trade: ~14c × avg 50 contracts = ~$7 per trade.
- Total recovery estimate: **$315-$350 across 45-50 trades** (~5% of settlement losses recovered).
- Cost: ~2-3 trades that would have reversed get stopped out. Estimated cost: ~$150-$200.
- **Net improvement: ~$150-$200 per week, or ~$600-$800/month.**

This is modest but positive. The real value is **tail risk reduction** — preventing a catastrophic session where 5+ trades all expire at 0.

### Different Thresholds by Strategy Duration

| Strategy | Stop-Loss Approach | Rationale |
|----------|-------------------|-----------|
| **Crypto 15m** | Time-gated value stop (above) | Short duration, high noise, binary payoff |
| **Crypto 1h** | Value < 25% after 30 min | More time for mean reversion; slightly looser |
| **Crypto 1D** | Value < 15% after 12 hours | Long duration allows regime changes; very loose |
| **Weather** | NO STOP | Multi-day resolution, price discovery too thin, spreads too wide |

---

## 2. Sports Odds Feasibility Assessment

### Data Summary

- 299 snapshots collected (hourly, 8am-8pm PDT)
- 59 matched snapshots (both Kalshi + Vegas prices)
- 41 flagged as tradeable (delta >= 3 percentage points)
- 240 Kalshi-only snapshots (Vegas not yet posted)

### Is a 5% Gap Enough Edge?

**Marginal. Here's the math:**

| Entry Price | Taker Fee | Net Edge from 5% Gap | Maker Fee | Net Edge (Maker) |
|-------------|-----------|----------------------|-----------|-------------------|
| 50c (coin flip) | 3.5% | **1.5%** | 0.9% | **4.1%** |
| 62c (moderate fav) | 2.7% | **2.3%** | 0.7% | **4.3%** |
| 87c (heavy fav) | 0.9% | **4.1%** | 0.2% | **4.8%** |

**At taker fees:** A 5% gap yields only 1.5-4.1% net edge depending on price level. At 50c (where most "value" bets live), 1.5% net edge means you need 200+ bets to have statistical confidence you're profitable. That's months of data.

**At maker fees:** Much better — 4.1-4.8% net edge. But maker orders require posting limit orders and waiting for fills, which may not happen if the gap closes quickly.

**Critical problem: Gap persistence.** The feasibility study found gaps close within minutes to 2 hours as arbitrageurs act. If you detect a 5% gap on an hourly scan, by the time you place a trade, the gap may be 1-2%. **You need sub-minute detection + execution to capture the full 5%.**

### Best Market Types

| Market Type | Edge Quality | Liquidity | Recommendation |
|-------------|-------------|-----------|----------------|
| **Moneylines (game winner)** | Best — Vegas lines are sharpest, so Kalshi mispricing is real signal | Good (KXNBAGAME has 130K+ OI) | PRIMARY TARGET |
| **Spreads** | Moderate — harder to devig, Kalshi may not offer | Low on Kalshi | SKIP for now |
| **Totals (over/under)** | Moderate — less sharp market, more noise | Medium | SECONDARY (if available) |
| **Player props** | Potentially high edge but very thin | Very low | SKIP |

### Go/No-Go Recommendation

**CONDITIONAL GO — with strict gates:**

The data collection phase has been valuable but is insufficient to greenlight live trading. The signal is promising but unproven.

**Conditions for GO:**

1. **Minimum confirmed edge:** Collect 50+ matched snapshots where the gap at detection time is verified against the gap at a realistic execution time (+2 minutes). If average executable gap >= 3% after fees, proceed.

2. **Execution speed upgrade:** Move from hourly polling to **5-minute polling** during pre-game windows (12-24h before tip). Cost: ~3x more OddsAPI credits (~150/month vs ~50/month). Still within free tier.

3. **Maker-only execution:** All sports trades must use limit orders posted at mid-market or better. No taker orders. This cuts fee drag from 2.7% to 0.7% and is the difference between profitable and unprofitable.

4. **Sizing:** Start at $25/trade (minimum viable). Max 2% of capital per game. Daily cap: 4 games. This limits downside to ~$100/day while gathering live execution data.

5. **Kill switch:** If net P&L after 30 trades is negative, pause for review.

**Timeline:**
- Now through April 15: Upgrade polling to 5-min, add execution-time gap measurement
- April 15-30: Analyze executable gaps. If >= 3% net (after maker fees): wire into strategy gate
- May 1: Go live with $25/trade sizing if data supports it

**If conditions are NOT met:** Keep collecting data. Sports is a nice-to-have diversifier, not a core strategy. Crypto 15m generates ~$5K-6K/day. Sports might add $50-100/day at best. Don't rush it.

---

## Summary of Recommendations

| Item | Recommendation | Expected Impact |
|------|---------------|-----------------|
| 15m Stop-Loss | Time-gated value stop (20% at 5-10min, 35% at 10-13min) | +$600-800/month, tail risk reduction |
| 1h/1D Stop-Loss | Looser thresholds (25% at 30min / 15% at 12h) | TBD — design after 15m validated |
| Weather Stop-Loss | None | N/A — spreads too wide |
| Sports Trading | Conditional GO — upgrade polling, maker-only, $25 sizing | +$50-100/day IF edge confirmed |
| Sports Kill Switch | Pause after 30 trades if net negative | Capital preservation |

---

*Next review: 2026-04-08 (after one week of stop-loss data + sports polling upgrade)*
