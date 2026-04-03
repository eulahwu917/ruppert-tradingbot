# crypto_1d — X (Twitter) Sentiment as Signal 5 (S5)
**Date:** 2026-03-30  
**Author:** Strategist (Ruppert)  
**Status:** PROPOSAL — Awaiting David's decision  
**Module:** crypto_1d (daily BTC/ETH above/below, 5pm ET settlement)

---

## Executive Summary

**Recommendation: Add S5 as a modifier signal — but NOT yet. Build the infrastructure now, shadow-score for 2–4 weeks, then activate with weight 0.10 only after signal quality is validated.**

X sentiment is a real edge at the daily horizon when properly filtered. But it's also the most gameable and noisiest signal in crypto. The architecture below makes it robust enough to add value without introducing instability.

---

## 1. What Signal?

### Options Evaluated

| Option | Pros | Cons | Verdict |
|--------|------|------|---------|
| **Raw sentiment score** (aggregate bullish/bearish tone from top accounts) | Directly correlates with retail positioning | Highly gameable; single viral tweet moves it; tone-detection is error-prone | ❌ Too fragile alone |
| **Breaking news detection** ("ETF approval", "exchange hack", "regulation ban") | Clear directional catalyst; best alpha source | Requires fast NLP + keyword matching; rare events; high stakes if wrong | ✅ Use as FILTER, not signal |
| **Influencer consensus** (net bullish/bearish across fixed curated list) | Aggregation reduces single-tweet noise; stable account list | Still gameable; influencers lag price; large followings move markets (reflexive) | ✅ Use as signal with aggregation guards |
| **Macro account sentiment** (Fed/inflation/risk-off language from macro voices) | Less gameable; tracks global risk appetite | Indirect connection to BTC/ETH price; slow-moving | 🔶 Include as one component |

### Decision: Composite approach — 3-layer filter

1. **Layer 1 — Breaking News Filter (GATE, not weight):**  
   Scan for high-alert keywords in recent 2h window before entry. If detected → skip trade entirely OR flip direction based on event type. Examples:
   - `"ETF approved" / "SEC approves"` → strong bull catalyst → only enter if composite already bullish, else skip
   - `"exchange hack" / "Binance hack" / "SEC ban"` → strong bear catalyst → only enter if composite already bearish, else skip
   - This is a **circuit breaker**, not a scored signal.

2. **Layer 2 — Influencer Consensus Score (WEIGHTED, S5):**  
   Net bullish/bearish tone across a fixed curated list of ≥15 accounts over the past 6–12 hours. Aggregated into a single score in [-1, +1]. This is S5.

3. **Layer 3 — Macro Sentiment Damper (OPTIONAL PHASE 2):**  
   Add macro voices (e.g., @federalreserve adjacent accounts, risk-off language detectors) as a 0.05 weight modifier in Phase 2 after Layer 2 is validated.

### Most Reliable, Least Gameable Design

- **Aggregation across ≥15 accounts** — a single influencer can't dominate
- **6–12 hour lookback** — not real-time, reducing reaction to single viral moments
- **Signal resets at scan time** (09:30 ET) — fresh pull each day, not accumulated overnight noise
- **Hard minimum account count gate:** If <10 of 15 accounts posted in lookback window → signal = 0.0 (no opinion)
- **Historical correlation gate (Phase 2):** Only maintain weight if rolling 30-day correlation with same-day BTC/ETH direction is >0.10

---

## 2. Which Accounts to Monitor

### Curated List (15 accounts, fixed — changes require Strategist review)

**BTC/ETH Directional Voices (most signal value):**
| Handle | Rationale |
|--------|-----------|
| @PlanB | BTC stock-to-flow; directional macro bias |
| @APompliano | High-reach retail pulse; sentiment proxy |
| @CathieDWood / @ARKInvest | Institutional positioning signal |
| @michael_saylor | BTC maximalist; his tweets move price |
| @WhalePanda | Experienced trader; good contrarian signal |
| @DocumentingBTC | Bullish bias; tracks on-chain accumulation signals |
| @glassnode | On-chain analytics; data-driven |
| @woonomic | On-chain analytics; Willy Woo |
| @Raoul_GMI | Macro + crypto; high credibility |

**Macro/Risk Sentiment (indirect but useful):**
| Handle | Rationale |
|--------|-----------|
| @KobeissiLetter | Macro trader; risk sentiment |
| @zerohedge | Fear/greed gauge (contrary indicator at extremes) |
| @NorthmanTrader | Technical/macro; risk-off signal |

**Official/News Sources (breaking news layer):**
| Handle | Rationale |
|--------|-----------|
| @SEC_News | SEC official; regulation announcements |
| @Grayscale | ETF/product announcements |
| @CoinDesk | Breaking crypto news; objective |
| @Cointelegraph | Breaking crypto news; backup source |

**Total: 16 accounts** (slightly above minimum for redundancy)

### Account List Maintenance Rules
- Review list quarterly or after a major signal failure
- Never add meme accounts or accounts with <100K followers
- Always have ≥3 official/news sources (hard news detection)
- Maximum 3 accounts from same narrative category (no single-narrative dominance)

---

## 3. Signal Weight

**Recommended weight for S5: 0.10**

### Rationale

Current weight distribution: S1=0.30, S2=0.25, S3=0.25, S4=0.20 → Total=1.00

S5 is a **soft signal** (qualitative, gameable, API-dependent). Hard rules:
- S5 weight ≤ S4 at all times (OI regime is harder/more reliable)
- S5 should never be the tie-breaker — it's a nudge, not a vote

**When adding S5 at weight 0.10:**
- Existing weights scale down proportionally: S1→0.27, S2→0.225, S3→0.225, S4→0.18, S5→0.10
- **S1 remains dominant.** Hard price signals retain 67.5% of composite weight.
- S5 can swing the composite by at most ±0.10 points — meaningful but not decisive

**Reject 0.15:** Too much influence for a gameable signal. 0.15 could override S4 on any given day.

**Dynamic weight reduction rules:**
- If S5 raw_score = 0.0 (no opinion / insufficient posts) → distribute 0.10 proportionally to S1-S4
- If breaking news detected → disable S5 (Layer 1 gate handles it as circuit breaker instead)

---

## 4. How It Combines

### Architecture: Weighted Additive (Same Pattern as S1-S4)

S5 integrates into `compute_composite_score()` exactly like S1-S4 — a weighted `raw_score` in [-1, +1].

```python
# crypto_1d composite (with S5)
raw_composite = (
    w1 * s1['raw_score'] +   # 0.27 — 24h momentum
    w2 * s2['raw_score'] +   # 0.225 — funding rate regime
    w3 * s3['raw_score'] +   # 0.225 — ATR band (still 0 for non-directional days)
    w4 * s4['raw_score'] +   # 0.18 — OI regime
    w5 * s5['raw_score']     # 0.10 — X sentiment consensus
)
```

**S5 raw_score mapping:**
- `net_bullish > 0.3` → `raw_score = +0.5` (mild bull nudge)
- `net_bullish > 0.6` → `raw_score = +1.0` (strong bull; cap at +1.0)
- `net_bullish < -0.3` → `raw_score = -0.5` (mild bear nudge)
- `net_bullish < -0.6` → `raw_score = -1.0`
- `-0.3 ≤ net_bullish ≤ 0.3` → `raw_score = 0.0` (neutral zone — no opinion)

### Does It Boost or Dampen?

Both. S5 is **additive** — it shifts the composite in the direction of consensus.
- **Agreement scenario:** S1/S2/S4 point bullish AND S5 is bullish → composite increases → higher P_above → stronger above bet
- **Disagreement scenario:** S1/S2/S4 point bullish BUT S5 is strongly bearish → composite decreases → may cross no_trade threshold → trade skipped

This is the desired behavior: sentiment **can veto** a trade when strongly contrary, but cannot **generate** a trade by itself (0.10 weight is too small to clear the MIN_EDGE threshold from zero).

### NOT Recommended: 6th Dimension

Adding S5 as a separate dimension (outside the composite) creates combinatorial complexity with no benefit at this stage. Single composite score with clear weight attribution is the right architecture.

---

## 5. Implementation Complexity

### What's Needed

**Minimal viable implementation:**

```bash
# xurl search: pull recent tweets from account list
xurl search "from:PlanB OR from:APompliano OR from:michael_saylor ... OR from:CoinDesk" \
  --since 6h --max-results 100 --fields text,author_id,created_at
```

**Then:**
1. **Keyword sentiment parse** (no NLP library needed for v1):
   - Bullish keywords: `"bull", "buy", "long", "moon", "accumulate", "breakout", "ATH", "rally", "bullish"`
   - Bearish keywords: `"bear", "sell", "short", "crash", "dump", "correction", "bearish", "breakdown", "danger"`
   - Neutral keywords: `"uncertain", "wait", "watching", "unclear"` → contribute 0 to score
   - Per-tweet score: +1 (bull keywords present), -1 (bear keywords), 0 (neutral/both/neither)
   - Per-account score: average of their tweets in the window
   - Net_bullish: average of per-account scores across all accounts with ≥1 tweet

2. **LLM fallback (optional, Phase 2):**  
   If keyword match rate is low (<40% of tweets scored), use a single LLM call (GPT-4o-mini or Claude Haiku) to batch-classify 20 tweets at once. Cheap. But not needed for v1 — keyword matching is sufficient for directional consensus.

**Complexity verdict:**
- **v1 (keyword matching): ~80 lines of Python.** `xurl search` + simple keyword counter + average. 1-2 hours of Dev time.
- **v2 (LLM classification): ~30 additional lines.** API call with structured output. Optional enhancement.

**API cost:** xurl search on this query costs ~1 Basic API call per scan. Twice daily = negligible.

---

## 6. Risk of Noise — Guardrails

### Noise Sources and Mitigations

| Noise Source | Risk Level | Guardrail |
|--------------|------------|-----------|
| Single viral tweet floods signal | High | Account-level averaging (each account = 1 vote, not tweet-volume-weighted) |
| Coordinated pump/dump campaign | Medium | Fixed account list (curated, not trending); no "most followed" dynamic selection |
| Influencer paid to shill | Medium | Curated accounts only; exclude known shillers; quarterly review |
| API down / rate limit | Low | If xurl fails → s5 = {'raw_score': 0.0, 'unavailable': True}; redistribute weight |
| Stale tweets (account hasn't posted) | Low | Minimum 10-of-16 accounts must have posted in lookback window |
| Reflexivity (influencer sees price move, tweets about it) | Medium | 6h lookback (not 1h); price move is already in S1; S5 adds incremental info |
| Breaking news detected by keywords incorrectly | Low | Breaking news gate uses specific phrases, not single words (e.g., "SEC approves Bitcoin ETF" not "SEC") |

### Hard Guardrails (non-negotiable)

1. **Account-level vote** (not tweet count): 1 account = 1 vote regardless of tweet volume
2. **Minimum account gate**: <10 of 16 accounts posted → `raw_score = 0.0`
3. **Neutral band**: `|net_bullish| < 0.3` → `raw_score = 0.0` (only strong consensus counts)
4. **API failure default**: fail to 0.0, log warning, redistribute weight
5. **Breaking news circuit breaker** runs BEFORE S5 scoring — news events bypass the weighted system entirely
6. **Shadow period first** (see Recommendation): validate signal before live deployment

---

## 7. Recommendation

### VERDICT: Build shadow infrastructure now. Activate in 2–4 weeks.

**Do NOT activate S5 immediately.** The module is newly live with 4 signals that are not yet calibrated (Strategist MEMORY: sigmoid scale uncalibrated, need 30 trades). Adding a 5th signal before baseline is established makes it impossible to attribute P&L attribution.

### Phased Plan

**Phase A — Shadow Scoring (now, ~1 week of Dev time):**
- Build `compute_s5_x_sentiment(lookback_hours=6)` function
- Call it at each `evaluate_crypto_1d_entry()` scan
- Log S5 score alongside other signals in `decisions_1d.jsonl`
- **Do NOT include in composite** — shadow only
- Run for minimum 2 weeks / 20 trades

**Phase B — Correlation Analysis (after 2 weeks):**
- Strategist reviews shadow log: `decisions_1d.jsonl` → S5 score vs actual outcome
- If S5 shows ≥0.10 correlation with correct direction → activate at weight 0.10
- If S5 shows near-zero or negative correlation → keep as shadow, adjust methodology
- If correlation is strong but S5 often unavailable → fix the xurl query first

**Phase C — Activate with Weight 0.10:**
- Weights become: S1=0.27, S2=0.225, S3=0.225, S4=0.18, S5=0.10
- Monitor for 30 more trades
- Optimizer will assess S5 impact as part of next optimization cycle

**Phase D — Optional LLM Enhancement:**
- If keyword matching produces noisy classifications, add Claude Haiku batch-classify
- Estimated cost: <$0.01/day at current usage
- Only add if Phase C shows underperformance attributable to classification errors

### If David Wants to Skip Shadow and Activate Now

Use **weight 0.05** as a compromise (smaller nudge, lower regret if signal is bad). Review after 30 trades.

---

## 8. Decision Summary

| Question | Answer |
|----------|--------|
| What signal? | Influencer consensus (curated 16 accounts, 6h lookback) + breaking news circuit breaker |
| Which accounts? | 16 curated accounts: 9 BTC/ETH directional, 3 macro, 4 official/news |
| Weight | 0.10 (activate in Phase C after validation) |
| How does it combine? | Weighted additive with S1-S4; can boost or veto; cannot generate trade alone |
| Implementation complexity | ~80 lines Python; xurl search + keyword count; 1-2 hours Dev |
| Noise guardrails | Account-level averaging, 10/16 minimum, neutral band ±0.3, API fallback to 0.0 |
| Recommendation | **Shadow first (2+ weeks), then activate at 0.10** |

---

## 9. Implementation Spec (for Dev when ready)

**New function:** `compute_s5_x_sentiment(lookback_hours: int = 6) -> dict`

**Returns:**
```python
{
    'net_bullish': float,    # [-1, +1] account-consensus score
    'accounts_scored': int,  # how many accounts had posts in window
    'raw_score': float,      # [-1, +1] after neutral-band gate
    'breaking_news': bool,   # True if high-alert keywords detected
    'breaking_direction': str | None,  # 'bull' | 'bear' | None
    'unavailable': bool,     # True if xurl call failed
}
```

**Breaking news keywords (gate activates if found in any ≥500-follower account post):**
- Bull: `"etf approved"`, `"sec approves"`, `"etf launch"`, `"bitcoin reserve"`, `"legal tender"`
- Bear: `"exchange hack"`, `"sec charges"`, `"exchange bankrupt"`, `"sec ban"`, `"exchange shutdown"`, `"wallet drained"`, `"regulatory ban"`

**Call in `evaluate_crypto_1d_entry()`:**
```python
# Shadow mode (Phase A):
s5 = compute_s5_x_sentiment()
signals_dict['S5'] = s5  # logged to decisions_1d.jsonl; not in composite

# Active mode (Phase C):
# If s5['breaking_news'] → apply circuit breaker logic (separate from composite)
# Else → include in compute_composite_score() at weight 0.10
```

**Log additions to `_log_decision()`:**
```python
entry['signals']['S5'] = {
    'net_bullish': s5.get('net_bullish'),
    'accounts_scored': s5.get('accounts_scored'),
    'raw_score': s5.get('raw_score'),
    'breaking_news': s5.get('breaking_news'),
    'unavailable': s5.get('unavailable'),
}
```

---

## 10. Open Questions for David

1. **Timeline:** Ready to build shadow infrastructure now, or wait until crypto_1d accumulates 30 baseline trades first?

2. **Account list:** Any accounts David specifically wants included or excluded?

3. **Breaking news circuit breaker:** Should it cause an automatic skip, or should David get an alert and decide manually? (Manual alert is safer but requires David to be available at 9:30am ET.)

4. **LLM classification:** Comfortable with occasional Claude Haiku API calls (~$0.01/day) for better sentiment accuracy in Phase D? Or keep it pure keyword-only?

5. **Weight shortcut:** If David is confident in the signal concept, can we activate at 0.05 now instead of 0.10 after shadow validation?

---

*Generated by Ruppert Strategist subagent | 2026-03-30*  
*Status: PROPOSAL — requires David's decision on timeline and activation path*
