# Optimizer Analysis: Bearish Directional Trading — Crypto Module
_SA-1 Optimizer | 2026-03-12_

---

## Recommendation: **HOLD**

Do not build this feature until the prerequisites below are met.

---

## Rationale

### 1. Smart Money Signal Quality Is Too Weak for Directional Conviction

The "bearish all day" classification today is driven by a single dominant wallet (`0x8dxd`), which accounts for the vast majority of tracked dollar volume ($827K down vs $419K up). Critically, that same wallet holds **both bullish and bearish positions on the same assets for the same settlement hours**:

- BTC 4PM: $2,972 down + $1,001 up (net bearish, but hedged)
- BTC 5:45–6PM: $609 down + $1,149 up (net **bullish**)
- ETH 5PM: $1,893 up + $581 down (net bullish)
- XRP 5PM: $1,539 up + $21 down (net bullish)

This is a **scalper/market-maker**, not smart money with directional conviction. The aggregate calculates as "bearish" because a few large down positions outweigh the up positions by dollar value — not because this wallet is making a clearcut bearish directional bet.

Additionally, per `team_context.md`: **5 of 8 tracked wallets are fake/placeholder**. The entire smart money module is running on 3 real wallets, with one dominant scalper distorting the signal. Using this as a trade trigger is premature.

**Verdict:** "Smart money bearish" today means "one scalper has more dollars on down than up." That is not a reliable directional signal.

---

### 2. Zero Historical Validation for Bearish-Direction Entries

All crypto trade history is as follows:

| Date | Ticker | Side | Setup | Outcome |
|------|--------|------|-------|---------|
| 2026-03-10 | KXETH-26MAR1117-B2030 NO | Bearish/neutral momentum | Win (exit ~70% gain) |
| 2026-03-10 | KXETH-26MAR1117-B2070 NO | Bearish/neutral momentum | Win (exit ~70% gain) |
| 2026-03-11 | KXETH-26MAR1217-B2100 NO (edge=14.8%) | BEARISH momentum day | Win (+$17.98, 70% gain rule) |
| 2026-03-11 | KXETH-26MAR1217-B2140 NO (edge=11.2%) | BEARISH momentum day | Win (+$21.28, 70% gain rule) |

**Critical observation:** The March 11 entries (B2100, B2140) were placed on a **BEARISH momentum day** (per crypto_scan_latest.json: momentum=BEARISH, RSI=48, below 20h MA). These were NO entries on bands ABOVE the current price ($2031) — i.e., betting ETH would NOT rise to $2100–$2140. They won because ETH did not rise.

This means the current bot already successfully captures a form of "bearish edge" — it enters NO on high-strike bands when the market overprices upward moves. The bearish direction signal was present, but entries were still BLOCKED per current behavior. These trades happened through a **different path** (edge gate alone, not direction gating).

Wait — if March 11 entries were placed on a BEARISH momentum day and the bot currently BLOCKS all entries when bearish, these trades should not have been placed. This is worth flagging as a possible code path inconsistency (strategy.py may not yet be wired into the crypto scan loop per team_context.md: "bot/strategy.py not yet wired into main.py — pending").

Regardless: **there are zero bearish-directed trades where we entered BECAUSE of a bearish signal** in the trade history. No ground truth for whether the bearish direction gate adds or removes edge.

---

### 3. The Edge Model Is Structurally Symmetric But Empirically Unvalidated on the Bear Side

The edge calculation applies a symmetric ±8% sigma momentum drift:
- BULLISH: `mu = current_price + sigma * 0.08`
- BEARISH: `mu = current_price - sigma * 0.08`

The model_prob → market_prob → edge pipeline is the same for both directions. **In theory**, this is symmetric and sound.

**In practice:** The edge model has been validated on 4 NO entries (high-strike bands, ETH-only), all of which settled profitably. We do not know whether the model's probability estimates for downside scenarios (low bands, or "price drops below X") are calibrated correctly. Brier skill scores have not been computed (pending per optimizer.md).

Furthermore, the ±8% sigma drift is small — it shifts the probability distribution by less than a tenth of a sigma. On a day when price moves 5–10%, this drift is swamped by actual realized volatility. The directional signal adds minimal structural edge to the probability model itself.

---

### 4. Strike Selection Is Harder for Bearish Plays and the Edge May Not Be There

**Bullish case (NO on high-strike):** When bullish and price is rising, the market often overprices the probability of extreme upward bands. The bot exploits this: NO on B2100 when ETH is at $2031 (market says 79% YES for a $70 upward move). That market overpricing creates the edge.

**Bearish case (NO on high-strike or YES on low-strike):**
- NO on high-strike in a bearish market: High-strike bands are already priced cheaply by the market (market agrees price won't go that high). NO is expensive (already near $0.90+). Edge opportunity is minimal.
- YES on low-strike (price will fall to low band): This is a directional bet on downward magnitude. The key challenge: how far down? A YES on "ETH below $1,900" when ETH is at $2,031 requires a ~6.5% drop in a single settlement period. The market prices this conservatively; if smart money is just a scalper with hedged positions, we have no informational advantage.

**Critical structural asymmetry:** Our 3 wins exploited overpriced high-band YES contracts (the market thought ETH was more likely to reach those bands than our model did). The equivalent for bearish plays would be finding overpriced low-band YES contracts (market says there's an X% chance of a big drop, but our model says less). That's a different market microstructure — it requires finding a different class of mispriced contract.

---

### 5. Overtrading Risk Is Real and Correlated

On a BEARISH momentum day, ALL crypto assets trend bearish together. Today (March 12), the crypto_scan_latest.json shows **BTC, ETH, XRP, and DOGE all momentum=BEARISH simultaneously**.

If bearish entries are enabled, a single bearish macro day could trigger entries across all 4 tickers simultaneously. With $25 max per entry and a $50 per-ticker cap, that's potentially $100–$200 deployed in a single scan cycle — compared to ~$25–$50 on a typical bullish scan.

The daily 70% cap provides some protection, but on a $400 demo capital base, 70% = $280. A bearish crypto sweep could consume a large fraction of the daily cap while the edge on bearish-direction contracts has zero historical validation.

---

## Prerequisites Before Building

These must be satisfied before bearish crypto entries are built or enabled:

1. **Fix Polymarket wallet quality.** Replace the 5 fake/placeholder wallets with real high-volume traders from the Polymarket leaderboard. The smart money signal must reflect multiple independent directional views, not one scalper's hedged book. Minimum threshold: 5+ real wallets, no single wallet > 40% of tracked dollar volume. _(Priority: HIGH — this affects all crypto signal quality, not just the bearish change)_

2. **Validate the bear signal is directional, not noise.** Run a 2-week retrospective: for each day the combined signal was BEARISH, did crypto prices actually close lower within the settlement window than they opened? Compute hit rate. If bear_signal hit rate is not meaningfully above 50%, the signal is not directional — it's a stop indicator, and the current behavior (block entries) is correct.

3. **Paper-trade bearish entries for 2 weeks before enabling.** The edge model has been validated only on the NO/high-strike/bullish path. Run simulated bearish entries in parallel with the live bot (dry_run mode) and measure: edge at entry, model_prob vs actual settlement, and calibration vs the bullish-path results.

4. **Determine which contract type to target first.** NO-on-high-strike (price won't go up) vs YES-on-low-strike (price will go down) have different risk profiles and different market microstructures. These should be validated separately, not bundled as equivalent alternatives.

---

## What This Analysis Does NOT Block

The current "bearish momentum day = block entries" behavior is **probably too conservative** given that our March 11 NO-on-high-strike wins occurred on a bearish momentum day. There may be value in **relaxing the block** (not adding directional bearish entries, but allowing the existing NO-on-high-strike logic to run regardless of direction signal). This is a separate, smaller change with lower risk that should be evaluated first.

---

_Analysis based on: 4 settled crypto trades, crypto_scan_latest.json (2026-03-11), crypto_smart_money.json (2026-03-12), crypto_client.py, team_context.md, optimizer_learnings.md_
_Next review trigger: after smart money wallet fix and 2-week bearish retrospective data available_
