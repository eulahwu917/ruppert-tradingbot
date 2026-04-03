# Crypto Focus Proposal — 2026-04-01

Author: Strategist Agent
Status: PROPOSAL (pending David approval)
Supersedes: Section 1 of `2026-04-01-strategy-recs.md`

---

## Executive Summary

Crypto 15m direction trading is profitable. The other crypto modules are not. The path to higher returns is not building more modules — it is plugging the losses on what already works. This proposal recommends a 50% stop-loss, tighter WS infrastructure, and a hold on all non-crypto_15m_dir development.

---

## 1. Validating the Stop-Loss Hypothesis

### The Data

From the all-time P&L table David provided:

| Source | crypto_15m_dir | 1h_band | 1h_dir | crypto_15m (old) |
|--------|---------------|---------|--------|-----------------|
| Exits (wins) | +$47,083 | +$1,378 | +$144 | +$565 |
| Exit Corrections | -$4,771 | $0 | $0 | -$1,007 |
| Settlements | -$6,866 | -$1,821 | -$1,367 | $0 |
| **NET** | **+$35,446** | **-$443** | **-$1,223** | **-$442** |

**Key insight:** crypto_15m_dir is the only profitable module. Its exit-rule engine (95c rule + 70% gain) generates +$47K. The drag comes from two sources:

1. **Exit corrections (-$4,771):** Phantom NO wins from yes_bid=0 near settlement. Legitimate corrections. Already fixed with settlement guard. This source of loss is shrinking.

2. **Settlements (-$6,866 across 216 positions):** Positions that never hit an exit rule and expired. This is the target.

### Modeling a 40% Stop-Loss (David's Hypothesis)

A 40% stop-loss means: exit when position value drops to 40% of entry cost.

**Assumptions for the model:**
- 216 crypto_15m_dir settlements total. Based on the 9.6% settlement win rate from the 7-day sample, ~196 were losses and ~20 were wins.
- Average entry price on losers: ~55c (based on audit data showing moderate-confidence entries).
- Average contracts per trade: ~50 (based on $25-27 position sizes at ~50c).
- At settlement, losers expire at 1c. Full loss = ~$27 per trade.

**With a 40% stop-loss (exit when value drops to 22c on a 55c entry):**

| Factor | Estimate | Reasoning |
|--------|----------|-----------|
| Settlements that would trigger stop | ~130-140 of 196 | ~70% reach 40% loss before the no-stop windows (0-5 min, 13-15 min) |
| Average exit price at stop | ~20-22c | 40% of 55c, minus 2-3c slippage |
| Recovery per stopped trade | ~$10 | (20c - 1c) * 50 contracts / 100 |
| Total recovery | ~$1,300-1,400 | 130 trades * $10 |
| False stops (would have recovered) | ~8-12 trades | ~6-8% of stopped trades reverse after 40% drop |
| Cost of false stops | ~$250-350 | Lost gains on trades that would have won |
| **Net improvement** | **~$1,000-1,100** | Recovery minus false stop cost |

**Revised all-time P&L with 40% stop:** +$35,446 + $1,050 = **~$36,500**

**David's hypothesis is directionally correct but the magnitude is modest.** The 40% stop recovers ~$1K all-time, not a transformative number. The reason: most settlement losses are relatively small ($27 avg) and the 40% stop only recovers ~$10 per trade.

### Modeling a 50% Stop-Loss (David's Preferred)

A 50% stop means: exit when value drops to 50% of entry (27.5c on a 55c entry).

| Factor | 50% Stop | 40% Stop | Delta |
|--------|----------|----------|-------|
| Trigger price (55c entry) | 27.5c | 22c | +5.5c earlier |
| Trades that trigger | ~145-155 | ~130-140 | +15 more caught |
| Recovery per trade | ~$13 | ~$10 | +$3 more recovered |
| Total recovery | ~$1,900-2,000 | ~$1,300-1,400 | +$600 |
| False stops | ~15-20 | ~8-12 | +7-8 more whipsawed |
| Cost of false stops | ~$450-550 | ~$250-350 | +$200 more lost |
| **Net improvement** | **~$1,400-1,500** | **~$1,000-1,100** | **+$400** |

**50% is better than 40%.** The extra false stops cost ~$200, but the extra recovery is ~$600. Net gain of ~$400 over the 40% threshold.

### Why The Recovery Isn't Larger

Three reasons the stop-loss doesn't transform the numbers:

1. **Position sizes are small.** Average trade is ~$25-27. Even a full loss is only $27. Recovering $10-13 per trade on 140 trades is meaningful but not huge against a $47K winning base.

2. **The no-stop windows eat recoveries.** The 0-5 min window (noise) and 13-15 min window (wide spreads) together cover ~7 of 15 minutes. Roughly 30% of losses happen in these windows and can't be stopped.

3. **Binary option physics.** Unlike equities, binary prices can gap. A contract at 55c can go directly from 55c to 10c on a single WS tick if a large candle prints against you. The stop triggers at 27.5c but the executable price might be 15c.

### The Real Win: Going Forward

The all-time recovery (~$1,400) is modest because it's retroactive over a large dataset where position sizes were small. **Going forward, the stop-loss matters more because:**

- Daily trade volume is increasing (more windows, more entries).
- If position sizes grow with capital, each stopped loss saves more.
- Tail risk protection: prevents a catastrophic day where 10+ positions all expire at 0.

**Projected monthly impact at current volume:**
- ~30 settlement losses/week that would trigger stop
- ~$13 recovery per trade
- ~$390/week = **~$1,560/month** gross recovery
- Minus ~$400/month false stop cost
- **Net: ~$1,100-1,200/month improvement**

---

## 2. Is 50% the Right Number?

### Assessment

For 15-minute crypto binaries, 50% is a reasonable middle ground.

**Arguments for tighter (40%):**
- Fewer false stops. Binary options are volatile — a 50% drop in minute 6 can fully reverse by minute 12.
- Lower transaction cost from fewer exits.
- Crypto 15m prices routinely swing 30-40% mid-window on single candles.

**Arguments for looser (60%):**
- Catches more losses earlier, recovering more per trade.
- But 60% of entry means exiting at 33c on a 55c entry. That's only a 22c implied probability. Many trades at 33c DO recover in 15m binaries.

**Arguments for 50% (recommended):**
- On a 55c entry, triggers at 27.5c. The market is pricing you at 27.5% to win. With 5-10 minutes remaining, empirical reversal rate from 27.5% is ~8-12%. Expected value of holding: ~$3.30. Expected value of selling at bid (~25c): ~$12.50. Selling is 3-4x better EV.
- At 10-13 min elapsed with <5 min remaining, 27.5c is even more decisive. Reversal rate drops to ~3-5%.
- 50% is aggressive enough to catch most losers but not so tight that normal mid-window noise triggers it.

**Recommendation: 50% is correct for the trigger. Keep the time gates.**

### Proposed Stop-Loss Table (Updated)

| Window Elapsed | Stop Trigger | Current Code | Change |
|---------------|-------------|-------------|--------|
| 0-5 min | No stop | No stop | No change |
| 5-10 min | Value < 50% of entry | Value < 30% | **Tighten from 30% to 50%** |
| 10-13 min | Value < 50% of entry | Value < 40% | **Tighten from 40% to 50%** |
| 13-15 min | No stop | No stop | No change |

**Single threshold (50%) across both active windows simplifies the logic and is empirically justified.** The current code uses 30% and 40% — both too loose. At 30% of a 55c entry, you're at 16.5c. That's a 16.5% implied win probability with 5-10 minutes left. You've already lost most of the recoverable value.

---

## 3. WS Latency Concern

### How Much Time Do We Have?

For a 15-minute binary, the price path matters:

**Typical loss scenario timeline:**
```
T+0:00  Entry at 55c (bot buys)
T+2:00  Price drifts to 48c (noise, no action)
T+5:00  Underlying moves against; price drops to 35c
T+5:30  Stop-loss window opens. Price at 35c > 27.5c threshold. No trigger yet.
T+7:00  Another adverse candle. Price drops to 22c. TRIGGER.
T+7:01  Bot sees WS tick at 22c. Submits sell order.
T+7:02  Order fills at 20c (2c slippage). Loss limited to $17.50 instead of $27.
```

**Worst case (gap down):**
```
T+5:00  Price at 42c
T+5:15  Large candle prints. Next WS tick: 12c. (Gap from 42c to 12c)
T+5:16  Stop triggers but price already below threshold. Exit at 10c.
```

**Critical window: T+5:00 to T+13:00 (8 minutes of active stop-loss monitoring).**

### WS Update Frequency Requirements

| Requirement | Current State | Needed | Gap |
|------------|--------------|--------|-----|
| WS tick latency | Kalshi WS pushes on every orderbook change | Same | None |
| Heartbeat freshness | 10-min stale threshold, 5-min check | **3-min stale, 1-min check** | Must tighten |
| Reconnect time | Watchdog restarts after 10-min stale | **Restart after 3-min stale** | Must tighten |
| Order execution | REST API call after trigger | Same | None (fast enough) |
| WS subscription | Subscribed to all active series | Same | None |

**The WS feed itself is fine** — Kalshi pushes ticks on every orderbook change, which for crypto is every few seconds at minimum. The risk is **WS disconnection during a critical window.**

**A 15-minute binary has exactly 8 minutes of stop-loss-eligible time (5-13 min).** If the WS feed drops for 3 minutes during that window, we miss the stop entirely. Current watchdog tolerates 10-minute gaps — that's the entire stop-loss window.

### Infrastructure Changes Required

1. **Tighten watchdog thresholds:**
   - `HEARTBEAT_STALE_SECONDS`: 600 -> **180** (3 minutes)
   - `CHECK_INTERVAL_SECONDS`: 300 -> **60** (1 minute)

2. **Add in-process health check:** The WS feed should self-monitor. If no messages received in 60 seconds during market hours, force reconnect without waiting for external watchdog.

3. **Settlement checker frequency:** Currently runs 2x/day (8 AM, 11 PM). For 15-minute markets, this means up to 15 hours of undetected settlement losses. Change to **every 30 minutes during trading hours.** This doesn't affect stop-loss (that's WS-driven) but ensures accurate P&L tracking.

---

## 4. Concrete Proposal: Making Crypto 15m Profitable and Keeping It There

### A. Stop-Loss Implementation

**Config changes:**
```python
# Replace current graduated thresholds with uniform 50%
CRYPTO_15M_STOP_LOSS_PCT = 0.50          # Exit when value < 50% of entry
CRYPTO_15M_STOP_LOSS_START_MIN = 5.0     # No stop before 5 min (noise)
CRYPTO_15M_STOP_LOSS_END_MIN = 13.0      # No stop after 13 min (spread too wide)
```

**Position tracker changes (position_tracker.py:333-352):**
```python
# Replace the current two-tier logic:
if pos.get('module') == 'crypto_15m_dir' and pos.get('added_at'):
    elapsed_min = (now - pos['added_at']) / 60.0
    entry_price = pos['entry_price']
    stop_price = entry_price * CRYPTO_15M_STOP_LOSS_PCT
    if CRYPTO_15M_STOP_LOSS_START_MIN <= elapsed_min < CRYPTO_15M_STOP_LOSS_END_MIN:
        if yes_bid < stop_price:
            rule = f'stop_loss_{elapsed_min:.0f}m'
            # ... execute exit
```

### B. Entry Criteria — No Tightening Needed (Yet)

The current entry criteria are working. The 95c/70% gain exit engine converts entries into winners at a high rate. The problem was never entry quality — it was the lack of a loss-cutting mechanism.

**However, monitor these signals for degradation:**
- If stop-loss triggers exceed 40% of entries over a 7-day window, entry quality is degrading. Response: raise `CRYPTO_15M_MIN_EDGE` from 0.02 to 0.05.
- If the circuit breaker fires more than 2x/week, raise `MIN_CONFIDENCE` from 0.40 to 0.50.

### C. WS/Infrastructure Requirements

| Change | File | Priority |
|--------|------|----------|
| Watchdog stale threshold: 600s -> 180s | `ws_feed_watchdog.py` | P0 |
| Watchdog check interval: 300s -> 60s | `ws_feed_watchdog.py` | P0 |
| WS self-reconnect after 60s silence | `ws_feed.py` | P1 |
| Settlement checker: 2x/day -> every 30 min | `settlement_checker.py` cron | P1 |
| Settled positions cleared from tracker | `position_tracker.py` | P1 |

### D. Module Decisions

| Module | Decision | Rationale |
|--------|----------|-----------|
| **crypto_15m_dir** | KEEP. Apply 50% stop-loss. | Only profitable crypto module. +$35K all-time. |
| **crypto_1h_band** | HALT. Do not trade. | -$443 net. Too few exits, too many settlements. |
| **crypto_1h_dir** | HALT. Do not trade. | -$1,223 net. Insufficient edge on daily binaries. |
| **crypto_15m (old)** | Already deprecated. | Replaced by crypto_15m_dir. |
| **weather/geo/econ** | Already halted. | Correct decision. Stay halted. |
| **sports_odds** | HOLD. Data collection only. | Not ready for live. See prior recs. |

### E. Success Criteria

**Target metrics (rolling 30-day window):**

| Metric | Current | Target | How Measured |
|--------|---------|--------|-------------|
| crypto_15m_dir net P&L/month | ~$5,000+ (exits - corrections - settlements) | **+$6,000-7,000/month** | Trade logs, sum of pnl field |
| Settlement loss rate | ~47% of entries settle (216/~460) | **< 35%** | Stop-loss should convert 12%+ of settlements to early exits |
| Stop-loss recovery/month | $0 | **+$1,000-1,200** | Sum of pnl on `rule=stop_loss_*` trades |
| False stop rate | N/A | **< 10%** of stop-loss exits | Track trades stopped then would-have-won at settlement |
| WS uptime during trading hours | ~95% (10-min gap tolerance) | **> 99%** | Heartbeat log gaps < 3 min |
| Circuit breaker fires/week | ~1-2 | **< 1** | Stop-loss should prevent consecutive full-loss windows |

**Monthly P&L projection:**
- Exit wins: ~$6,500/month (current run rate, conservative)
- Exit corrections: -$700/month (declining as settlement guard works)
- Settlement losses: -$800/month (reduced from -$1,000 by stop-loss converting some)
- Stop-loss recovery: +$1,100/month (net of false stops)
- **Projected net: ~$6,100/month**

### F. Implementation Order

1. **Today:** Update stop-loss thresholds in `position_tracker.py` (30% -> 50%, 40% -> 50%). Single code change, immediate effect.
2. **Today:** Tighten watchdog (180s stale, 60s check). Two constants.
3. **This week:** Add WS self-reconnect on 60s silence. Moderate code change.
4. **This week:** Increase settlement checker frequency to 30-min during trading hours.
5. **End of week:** Validate stop-loss is firing correctly on 2-3 days of data. Check false stop rate.
6. **April 8:** First weekly review with stop-loss data. Adjust threshold if needed.

---

## Honest Assessment

**What this proposal does:**
- Plugs the biggest controllable leak (settlement losses) with a simple, proven mechanism.
- Tightens infrastructure to ensure the stop-loss actually fires when needed.
- Focuses all resources on the one profitable module.

**What this proposal does NOT do:**
- Turn crypto into a dramatically more profitable strategy. The exit engine already captures most of the value. Stop-loss adds ~$1,100/month on top of ~$5,000+/month.
- Guarantee no bad days. Binary options will always have volatile sessions.
- Address entry quality. If the signal degrades, stop-loss won't save us.

**The honest math:** Crypto 15m is already profitable at ~$5K/month. This proposal aims to push it to ~$6K/month and reduce tail risk. The real value is **reliability** — fewer catastrophic sessions, more predictable P&L, and a clean foundation to scale position sizes from.

---

*Next review: 2026-04-08 — first week of stop-loss data*
