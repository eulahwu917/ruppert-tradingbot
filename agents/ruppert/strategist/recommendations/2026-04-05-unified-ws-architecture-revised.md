# Revised Recommendation: Unified WS Architecture
**Date:** 2026-04-05
**Author:** Strategist
**Status:** REVISED — incorporates David's feedback on all 6 adversarial points

---

## Summary

The unified WS architecture proposal stands. Six adversarial challenges were raised; David reviewed them and provided feedback on each. This document addresses all six with code-verified findings, revised positions where warranted, and a clear implementation path.

---

## Point #1 — S2 Funding Rate TTL: Is 15m or 30m Refresh Technically Feasible?

**David's question:** Keep at 1h, but could we go tighter — 15m or 30m?

**Short answer:** Yes, technically feasible. 30m is the recommended tightening.

**OKX rate limit analysis:**
- Public endpoint: **20 requests per 2 seconds per IP** (from `docs/apis/okx.md`)
- We query one symbol per call, 5 symbols total (BTC, ETH, XRP, DOGE, SOL)
- At 30m refresh: 5 calls every 30 min = **0.17 calls/min** — trivially within rate limits
- At 15m refresh: 5 calls every 15 min = **0.33 calls/min** — also trivially within rate limits
- No rate limit concern at either cadence.

**Why not 15m?**
Funding rates settle every **8 hours** on OKX. The rate does not change more frequently than that — the data returned by `/public/funding-rate-history` is historical settled rates, not real-time intraday fluctuation. Fetching every 15m would be reading the same 8h-old data 32× per settlement period. The only thing that changes intraday is the *current period's* expected rate, which requires a different endpoint (`/public/funding-rate` — live rate, not history).

**Revised recommendation:**
- **Keep TTL at 1h for the history-based z-score signal.** The 1h TTL is already well within the 8h settlement cycle. There is no signal benefit from refreshing history more frequently.
- **If you want real-time funding sentiment:** OKX has a separate endpoint `/public/funding-rate` that returns the live predicted rate for the current 8h window. This *would* benefit from tighter polling (30m). But this requires a new function — it's an enhancement, not a TTL change.
- **Bottom line:** Funding rate TTL stays at 1h. The adversarial challenge was correct that tighter is *possible*, but David's instinct to keep it at 1h is correct for the history-based signal. The 15m/30m question would only matter for a live-rate endpoint, which we don't currently use.

---

## Point #2 — ISSUE-062 / Live Spot Price: Do We Even Need External Spot Price?

**David's question:** Why did we defer ISSUE-062? Does Kalshi provide a live spot price? Doesn't Kalshi contract pricing reflect the underlying?

**What ISSUE-062 actually is:**

Read `agents/ruppert/data_analyst/ws_feed.py` lines 375–381:

```python
current_price = signal['price']
# TODO ISSUE-062: current_price comes from get_*_signal() via crypto_client.py cache.
# It may be stale by seconds to minutes relative to the live WS tick that triggered this call.
# market_cache stores live Kalshi bid/ask but not spot (fiat) price — no get_spot_price() method.
# A non-blocking spot price improvement requires crypto_client.py to expose a module-level
# last_known_price dict that ws_feed.py's WS handler updates on each tick. That refactor is
# deferred.
```

The issue is: `current_price` is sourced from `get_btc_signal()` in `crypto_client.py`, which caches price for **5 minutes** (TTL=300s). When a WS tick fires, the price used in the model could be up to 5 minutes stale.

**David's core insight is right, but with nuance:**

Kalshi contract prices DO reflect underlying BTC movement — but they reflect *probability*, not raw spot price. Here's the distinction:

- `KXBTCD-...-T84000` trades at 72¢. That 72¢ encodes the market's probability that BTC ends above $84K. It doesn't directly give us a spot price — it gives us a Bayesian estimate of where BTC is relative to a threshold.
- To derive spot price from Kalshi contracts, you'd need to solve the inverse: find the strike where YES price ≈ 50¢ (at-the-money contract). That's *possible* but adds complexity and latency.

**The real question: do we actually need real-time spot price for the WS feed path?**

Looking at what `current_price` is used for in `evaluate_crypto_entry()`:
1. **Band probability:** `_band_probability(low, high, current_price, sigma)` — the model's P(BTC lands in band). A 5-min stale price is mostly fine here since band probability is smooth and slow-moving.
2. **Threshold direction:** `strike_type = 'greater' if strike > current_price else 'less'` — this determines whether a T-contract is above or below current price. A 5-min stale price on a $2K+ move could misclassify direction, but that's rare.
3. **Sigma computation:** `sigma = current_price * realized_vol * math.sqrt(hours_left)` — scaling factor, not terribly sensitive to 5-min stale.

**For the cache refresh trigger (>3% move):** David's instinct is correct — we don't need an external spot price for this. We can infer large price moves from the Kalshi orderbook itself: if the at-the-money contract's YES ask shifts dramatically between ticks, that implies underlying moved. A simpler proxy: track the `yes_ask` change on the nearest-ATM contract across consecutive WS ticks. If it moves >5¢ in a single tick, that implies a significant price move.

**Revised recommendation on ISSUE-062:**

The deferral was correct given the complexity. But David's framing reframes the problem usefully:

- **Don't fetch external spot price on every WS tick** — that would be blocking I/O on the hot path.
- **Use CoinGecko price cache as-is (5-min TTL)** — the staleness risk is bounded and mostly acceptable for band/threshold models.
- **For the unified WS architecture specifically:** The proposed `last_known_price` module-level dict in `crypto_client.py` is still the right technical fix (non-blocking, updated by WS ticks). But priority is low — we can collect WS data with 5-min stale price and the signal quality is still good.
- **ISSUE-062 remains deferred** — it's a refinement, not a blocker for the unified WS architecture.

---

## Point #3 — Shadow Trading in DEMO: Re-Assessing Risk

**David's point:** DEMO IS the shadow environment. Shadow trading within DEMO is pointless — we're already trading fake money.

**He's completely right.**

The original adversarial challenge raised the shared `SHADOW_MODE` flag as an operational risk: accidentally enabling band trading in DEMO via the wrong flag. But David's reframe changes the severity calculus entirely:

- DEMO uses fake money. If band trading accidentally enables in DEMO, we lose fake dollars. There is no financial harm.
- The real risk would be in LIVE, where a misconfigured shadow flag could cause real losses. But LIVE mode has its own hard gates (`require_live_enabled()`, explicit `RUPPERT_ENV='live'` check) that are separate from the DEMO shadow flag.
- A `SHADOW_MODE` within DEMO is a shadow-within-a-shadow. It adds complexity without adding safety.

**Revised recommendation:**

Drop the `SHADOW_MODE` flag concern. The current approach — `DRY_RUN = True` blocks order placement, all logging continues — is exactly right for DEMO. When we want shadow data on daily modules, we just run them in DEMO with `DRY_RUN = True`. That IS the shadow environment.

The one thing still worth doing: make sure the `SHADOW_MODE` flag in the unified WS spec **only ever appears in DEMO context** and cannot be accidentally inherited by a LIVE deployment. But this is a documentation/config hygiene issue, not an architectural risk.

---

## Point #4 — Model Selection: Is There Historical Data to Pick a Winner?

**David's point:** If one model is clearly better, use that one. If both have strengths, 50/50 is fine as a starting point.

**What the data shows:**

The current models are:
- **Log-normal model** (`_band_probability()` in `ws_feed.py`) — uses normal CDF on BTC price distribution
- **Student-t model** (`_t_cdf()` in `ws_feed.py`) — uses fat-tailed distribution for threshold contracts

**Historical win rate data (from settled trades):**

Checked the trade logs (`trades_2026-04-02.jsonl` through `trades_2026-04-04.jsonl`). All band and threshold daily trades were **purged** from the logs on 2026-04-04 (the 790+ band/threshold records cleanup after the WS gate bug). We have no settled band/threshold outcomes to compare models against.

**The 15m crypto data** (296 trades, ~87% NO win rate) is from a *directional* model (TFI/OBI/MACD), not the band/threshold probability models. These are completely different model types — the 15m win rate tells us nothing about which band/threshold probability model is more accurate.

**Conclusion:** We have zero historical data on band/threshold model accuracy. We cannot pick a winner empirically yet.

**Revised recommendation:** Start 50/50 ensemble as David suggested. Once daily modules accumulate 50+ shadow decisions with outcomes, run a Brier score comparison between the log-normal and t-distribution predictions. That will tell us which model is better calibrated. Until then, 50/50 is the intellectually honest approach — equal weight on two reasonable priors.

---

## Point #5 — 30-Day Timeline

**David's note:** "I will be the judge of that."

Accepted. We'll collect the shadow data and let results speak.

Brief context for the record: the statistical point stands that 30 days / 50+ trades gives us enough for a directional read, but confidence intervals will be wide. More data is always better. David will evaluate when we have enough to make a call.

No further argument needed on timeline.

---

## Point #6 — 15m Path Isolation: Plain English Explanation

**David's question:** "I don't understand." What's the risk and what's the fix?

**The problem in plain English:**

The 15m trading path is our fastest path — it reacts to live WS ticks within milliseconds and must execute in under a second to catch good prices. The unified WS architecture proposes adding cache refreshes for S1-S5 signals (funding rate, volatility, etc.) that get triggered when price moves >3%.

The risk: refreshing those signals means making HTTP calls to OKX, CoinGecko, or Kraken *while a WS tick is being processed*. Python's asyncio event loop can only do one thing at a time. If the cache refresh takes even 500ms (a slow API call), then for that 500ms, no 15m ticks are being processed. A lot can happen in 500ms — we could miss a position that needs exiting, or miss the entry window entirely.

This is less about "slowing down" and more about **blocking**: a single slow refresh blocks everything else until it finishes.

**The simple fix:**

Run cache refreshes in the **background** — not blocking the main WS tick handler. The asyncio equivalent is `asyncio.create_task(refresh_cache())` instead of `await refresh_cache()`. This launches the refresh without waiting for it to finish. The WS tick handler returns immediately, the 15m path stays fast, and the cache refresh completes a few seconds later in the background.

The only downside: for those few seconds between "trigger fired" and "cache updated," the model is still using the old signals. This is fine — the next tick will use the fresh data.

**Implementation note:** `ws_feed.py` already uses asyncio. The `evaluate_crypto_entry()` function is called from the async message handler. Adding `asyncio.create_task()` for the cache refresh is a one-line change. No architectural refactor needed.

---

## Overall Verdict: Unified WS Architecture — Proceed

With David's feedback incorporated, all six challenges are resolved:

| Point | Original Challenge | Revised Position |
|-------|------------------|-----------------|
| #1 S2 TTL | Concern about stale funding data | **Keep 1h.** Data settles every 8h; 15/30m refresh adds no signal value for history-based z-score. |
| #2 ISSUE-062 | Deferred spot price fix | **Deferral was correct.** Kalshi prices don't give us spot directly; 5-min CoinGecko cache is acceptable. External spot price not needed for >3% trigger (use ATM contract move as proxy). |
| #3 Shadow flag | Risk of shared SHADOW_MODE flag | **Not a real risk.** DEMO = shadow environment. Fake money means the operational risk of accidentally enabling band trading is essentially zero. |
| #4 Model selection | Which model to use | **Start 50/50.** No historical data to pick a winner. Brier score comparison after 50+ shadow decisions. |
| #5 30-day timeline | Statistical concern | **David decides.** Noted and accepted. |
| #6 15m path isolation | Risk of blocking WS handler | **Simple fix:** `asyncio.create_task()` for background refreshes. One-line change. |

**Recommended next step:** Proceed with the unified WS architecture as proposed. The only implementation guard needed is #6 — ensure all cache refreshes triggered from the WS tick handler use `create_task()` (non-blocking). Everything else is either acceptable as-is or handled by existing code.

Daily modules remain off until shadow WR >45% / 50+ decisions.
