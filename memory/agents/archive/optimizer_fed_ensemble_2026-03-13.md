# SA-1 Optimizer — Fed Ensemble Design Recommendation
_Date: 2026-03-13 | Author: SA-1 Optimizer_
_Trigger: Polymarket slug_unknown failure at 12pm with March 18 FOMC 5 days out_

---

## Context

The existing `fed_client.py` uses Polymarket as its **only** probability source via slug-based lookup. Today this generated `polymarket_unavailable` / `slug_unknown` with 5 days to the March 18 meeting — a hard failure at exactly the moment a signal should be live.

**Note:** Before reading the existing code, I confirmed the historical flow:
- CME FedWatch was the original source, but required a paid API ($25/mo). It was removed.
- Polymarket replaced it (free, no auth) but has slug-dependency brittleness.

This ensemble design makes Polymarket the tertiary source, not the only one.

---

## Source Definitions

| # | Source | Type | Auth |
|---|--------|------|------|
| 1 | **CME FedWatch** (underlying API endpoint) | Market-implied probability (Fed Funds futures) | None if endpoint is public |
| 2 | **Polymarket** (existing slug lookup) | Prediction market probability | None |
| 3 | **FRED DFEDTARU** | Current target rate upper bound | None |

FRED is **not** a probability source — it plays a separate role (see Section 3).

---

## 1. Weighting

**Recommendation: CME 65%, Polymarket 35%. FRED is not weighted.**

Rationale:
- CME FedWatch is derived from Fed Funds futures — the deepest, most liquid market for FOMC rate expectations. Institutional money prices this. It is the reference.
- Polymarket is a prediction market with meaningful but far smaller liquidity. Valid signal, but epistemically inferior to futures.
- Equal weighting would be epistemically wrong. CME deserves primary weight.
- Do NOT weight FRED into the probability average — it is not a probability.

```python
# When both sources available
ensemble_p = 0.65 * cme_p + 0.35 * poly_p

# When CME only (Polymarket down)
ensemble_p = cme_p  # no penalty — CME is more authoritative anyway

# When Polymarket only (CME down)
ensemble_p = poly_p  # with confidence penalty (see Section 4)
```

---

## 2. Fallback Logic

**Rule: Minimum 1 probability source required. CME failure is lower severity than Polymarket failure.**

| Scenario | Action |
|----------|--------|
| Both CME + Polymarket ✅ | Full ensemble, normal confidence |
| CME ✅, Polymarket ❌ | CME only at 100% weight, no confidence penalty (CME > Polymarket) |
| CME ❌, Polymarket ✅ | Polymarket only at 100% weight, **−15% confidence multiplier** |
| Both ❌ | No signal. `skip_reason = 'all_prob_sources_unavailable'` |
| FRED ❌ | Skip FRED sanity check only. No impact on signal — FRED is advisory. |

**Today's failure would not have happened** — CME would have been the primary source with a live signal.

---

## 3. FRED's Role

**Use FRED as a direction sanity gate only. Do not weight it into the probability.**

FRED `DFEDTARU` gives us the current target rate upper bound (e.g., 4.50%). It cannot tell us the probability of a rate change. Best uses:

### 3a. Direction Validator
Confirms which direction is physically meaningful:
- If `fed_rate > 1.0%` → cuts AND hikes are both plausible → no constraint
- If `fed_rate ≤ 0.25%` → rate is at floor → ensemble `cut` probability > 30% is suspicious → apply 10% confidence reduction
- If `fed_rate ≥ 5.5%` → rate at recent ceiling → ensemble `hike` probability > 30% is suspicious → apply 10% confidence reduction

### 3b. Dashboard Context
Display "Current Fed rate: 4.25–4.50%" on the Fed card. Useful for David to understand the market context without affecting signal math.

### 3c. Switch from FEDFUNDS to DFEDTARU
The existing code uses `FEDFUNDS` (monthly, lagged). Switch to `DFEDTARU` (daily target upper bound) — more current, directly reflects actual policy.

```
https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFEDTARU
```

---

## 4. Confidence Scoring

**Yes — confidence should go UP when sources agree and DOWN when they diverge.**

Current formula is based only on extremity of probability (how far from 50/50). Extend it to include agreement factor.

```python
def compute_ensemble_confidence(
    cme_p: float | None,
    poly_p: float | None,
    ensemble_p: float,
    fred_sanity_ok: bool = True,
) -> float:

    # Step 1: Base confidence from probability extremity
    # 0.5 when prob = 50%, 1.0 when prob = 0% or 100%
    extremity = min(abs(ensemble_p - 0.5) * 2, 1.0)
    base_conf = 0.5 + extremity * 0.5  # range [0.50, 1.00]

    # Step 2: Source agreement factor
    if cme_p is not None and poly_p is not None:
        divergence = abs(cme_p - poly_p)
        if divergence <= 0.05:
            agreement_factor = 1.05   # < 5pp apart → strong agreement bonus
        elif divergence <= 0.10:
            agreement_factor = 1.00   # 5–10pp → neutral
        elif divergence <= 0.20:
            agreement_factor = 0.90   # 10–20pp → mild concern
        else:
            agreement_factor = 0.80   # > 20pp → significant divergence penalty
    else:
        # Single source only
        agreement_factor = 0.90 if cme_p is None else 1.00
        # CME-only: no penalty. Polymarket-only: -10%.

    # Step 3: FRED sanity gate
    fred_factor = 0.90 if not fred_sanity_ok else 1.00

    # Step 4: Final confidence (cap at 0.99)
    confidence = min(base_conf * agreement_factor * fred_factor, 0.99)
    return round(confidence, 3)
```

**Divergence example:** If CME says `maintain=72%` and Polymarket says `maintain=52%`, divergence = 20pp → agreement_factor = 0.90 → confidence takes a 10% hit. The ensemble still fires if edge and confidence thresholds clear, but with appropriate discount.

---

## 5. Edge Threshold

**Keep at 12% for DEMO. Do not lower yet.**

Reasoning:
- CME FedWatch is MORE market-efficient than Polymarket → edges against CME may be smaller
- We need actual ensemble data to know if CME consistently shows higher or lower edges
- Lowering the threshold without data would increase false positives
- Post-DEMO action: If backtest shows CME-based edges are reliably predictive at lower levels, revisit lowering to 10%

The 12% threshold has been validated by the Optimizer (see `optimizer_edge_threshold_2026-03-12.md`). **Do not bypass that validation for a convenience change.**

---

## 6. CME FedWatch Scraping Risks

**Do NOT scrape the HTML page. Find the underlying AJAX endpoint instead.**

### Why the HTML page is problematic
- FedWatch is a JavaScript SPA — a plain `requests.get()` returns an empty shell
- Requires headless browser (Selenium/Playwright) — heavy dependency
- CME has Cloudflare bot detection → high failure rate
- Page structure changes without notice → brittle

### Historical context
The original `fed_client.py` already tried this and removed it (see `developer_fed_polymarket_2026-03-12.md`): `_parse_fedwatch_json()`, `get_fedwatch_probabilities()`, `_scrape_fedwatch_html()` were all removed because the CME API required a paid subscription.

### Recommended approach for DEMO
Before assuming the API is paid, **Developer should inspect the FedWatch page's network requests** (Chrome DevTools → Network tab → XHR/Fetch). CME FedWatch makes AJAX calls to internal endpoints that often return clean JSON — these are sometimes public/unauthenticated.

Known endpoint pattern to investigate:
```
https://www.cmegroup.com/CmeWS/mvc/MktData/...
https://www.cmegroup.com/CmeWS/mvc/ProductType/...
```

If no public endpoint is found: **defer CME for post-DEMO and run DEMO with Polymarket as primary + FRED as sanity filter.** A 2-source ensemble (Polymarket + FRED gate) is still a massive improvement over the current single-source design.

### ToS risk
If an undocumented endpoint is used, there is mild ToS risk. For DEMO (no real money, private system), this is acceptable. For LIVE: use an official data vendor or the CME DataMine service.

---

## Implementation Summary for Developer

### Changes to `fed_client.py`

1. **New function `get_cme_fedwatch_probabilities(meeting_date)`**
   - Attempt to call CME AJAX endpoint (Developer to identify via network tab inspection)
   - Returns `{outcome: float}` same shape as Polymarket dict
   - Returns `None` on failure (same pattern as existing Polymarket function)

2. **Switch FRED series**: `FEDFUNDS` → `DFEDTARU`

3. **New function `compute_ensemble_confidence(cme_p, poly_p, ensemble_p, fred_sanity_ok)`**
   - Implement formula from Section 4 above

4. **New function `_fred_sanity_check(fed_rate, outcome, ensemble_p)`**
   - Returns `bool` — False if direction is physically implausible at current rate

5. **Refactor `get_fed_signal()`**
   - Call CME (primary) + Polymarket (secondary)
   - Apply fallback logic from Section 2
   - Compute ensemble probability per Section 1
   - Run FRED sanity check per Section 3
   - Compute confidence via new formula
   - Update signal dict: `prob_source` field → `'cme'`, `'polymarket'`, `'cme+polymarket'`
   - Add `cme_probs`, `poly_probs`, `ensemble_probs`, `source_divergence` to signal dict

6. **New skip_reason values**:
   - `all_prob_sources_unavailable` (new — was `polymarket_unavailable`)
   - Keep `polymarket_unavailable` for backward compat if CME also unavailable

### No changes needed
- Edge threshold (12%) — unchanged
- Window filter (2–7 days) — unchanged  
- Favorite-longshot bias (15¢ floor) — unchanged
- Kalshi market fetch — unchanged
- `_save_scan_result()` — unchanged (just add new fields to payload)

---

## Priority

| Item | Priority | Notes |
|------|----------|-------|
| Find CME AJAX endpoint | HIGH | Developer: network tab inspection |
| Switch FRED to DFEDTARU | HIGH | Simple URL change |
| Ensemble probability logic | HIGH | Core fix |
| Confidence formula update | HIGH | Important for signal quality |
| FRED sanity gate | MEDIUM | Advisory only, can be v2 |
| ToS review for LIVE | LOW | DEMO only — defer |

---

_Optimizer sign-off: This spec is complete for Developer handoff. QA should verify ensemble probability math and fallback branch coverage._

---

## Market Impact Ceiling

_Added 2026-03-13 per David/CEO question_

### 1. At What Account Size Does Market Impact Become a Concern?

**Answer: ~$3,000 for weather markets. ~$10,000 for crypto/FOMC markets.**

Kalshi market liquidity varies significantly by module:

| Module | Typical Open Interest (one side) | Thin market threshold | Impact concern starts |
|--------|-----------------------------------|-----------------------|-----------------------|
| Weather | $2,000–$10,000 | < $5k | **~$3,000 account** |
| Crypto | $20,000–$200,000 | < $30k | ~$10,000 account |
| Fed/FOMC | $10,000–$100,000 | < $20k | ~$8,000 account |

At current DEMO size ($400, max $50/trade), market impact is **zero** — we are an ant in these markets. But planning ahead matters. Here's why:

- Current entry: `min($25, 2.5% of capital)` → at $3,000 account, entry = $75 with max $150
- A $150 order against a $5,000-deep weather market = **3% of one-side liquidity** → price slippage starts here
- At $5,000 account: entry = $125, max $250 → up to **5% of thin weather market** → meaningful impact
- At $10,000 account: entry = $250, max $500 → **10% of thin weather market** → definitely moving prices

**Bottom line:** Build the impact check before going LIVE. We do not need it for DEMO.

---

### 2. Should We Add a Market Impact Check?

**Yes — but phased. Spread proxy now (cheap), depth check later (at scale).**

A full order book depth check is the gold standard, but it requires extra API calls per trade and Kalshi's public API may not always expose full depth. There is a cheaper proxy that already costs zero extra API calls.

**Phase 1 (implement now, before LIVE):** Bid/ask spread as liquidity proxy  
**Phase 2 (implement at $5,000+ account):** Open interest cap check  
**Phase 3 (implement at $10,000+ account):** Order book depth query

---

### 3. Simple Heuristics

#### Heuristic A — Bid/Ask Spread Proxy (Phase 1, zero extra API cost)

The spread is already fetched in every scan (`yes_ask`, `yes_bid`). A wide spread signals a thin, illiquid market where our order will move prices.

```python
# Already available on every market dict
spread_cents = yes_ask - yes_bid  # e.g., 52 - 48 = 4¢

# Liquidity tier from spread
if spread_cents <= 3:
    liquidity_tier = 'liquid'       # normal sizing
elif spread_cents <= 7:
    liquidity_tier = 'moderate'     # cap at 50% of normal size
else:
    liquidity_tier = 'thin'         # cap at $25 hard floor (minimum trade only)
```

This is a **conservative but free** check. Wide spreads are the market's own signal that participants are uncertain — we should be too.

#### Heuristic B — Open Interest Cap (Phase 2, one extra API call)

```python
# Kalshi markets return open_interest (in contracts/cents)
# Rule: our trade ≤ 5% of open interest on the side we're buying
max_trade_by_oi = open_interest_dollars * 0.05

# Apply as a ceiling on top of Kelly sizing
effective_max = min(kelly_size, max_trade_by_oi, MAX_PER_TICKER)
```

**5% of open interest** is a standard rule-of-thumb from equity markets adapted for thin prediction markets. It means:
- $10,000 OI market → max $500 trade (but our Kelly cap of $50 is lower anyway at current size)
- $2,000 OI market → max $100 trade (starts binding around $3,000+ account)

#### Never Use More Than These Hard Caps (All Phases)

| Account Size | Hard Trade Cap |
|--------------|---------------|
| < $2,500 | $50 (existing cap, no change) |
| $2,500–$5,000 | $100 |
| $5,000–$10,000 | $200, or 5% OI, whichever is lower |
| $10,000+ | 3% OI or depth-based, full dynamic check |

These tiers should be reviewed — not automatically activated. **David approves any increase in the hard trade cap.**

---

### 4. Dynamic vs Fixed Cap — Recommendation

**Fixed cap now. Hybrid dynamic at LIVE scale.**

| Phase | When | Method | Rationale |
|-------|------|--------|-----------|
| **DEMO** | Now | Fixed $50 hard cap (existing) | Account is $400. Zero impact risk. Don't over-engineer. |
| **Pre-LIVE** | Before first real-money trade | Add spread proxy check (Phase 1) | Free, already-fetched data, protects against entering thin markets |
| **LIVE < $5k** | Account $400–$5,000 | Spread proxy + $50 cap | Spread proxy catches thin markets; cap prevents outsized position |
| **LIVE $5k–$10k** | Account $5,000–$10,000 | Spread proxy + 5% OI cap | OI cap becomes the binding constraint in thin markets |
| **LIVE $10k+** | Account $10,000+ | Dynamic depth check + 3% OI | Full order book query per trade; worth the API overhead at this scale |

**The spread proxy is the highest-ROI defensive check to add before going LIVE.** It costs nothing (reuses existing data), catches thin markets immediately, and prevents the worst impact scenarios. Implement it in the pre-LIVE Developer pass.

---

### Implementation Note for Developer

The spread check should live in `bot/strategy.py` (Strategy Layer), not in individual module clients. It is module-agnostic — same logic applies to weather, crypto, and Fed markets.

```python
def apply_market_impact_ceiling(
    base_size: float,
    yes_ask: int,
    yes_bid: int,
    open_interest: float | None = None,
) -> tuple[float, str]:
    """
    Apply market impact ceiling to a proposed trade size.
    Returns (adjusted_size, reason_str).
    """
    spread = yes_ask - yes_bid  # in cents

    if spread <= 3:
        size = base_size  # liquid — no adjustment
        reason = "liquid"
    elif spread <= 7:
        size = min(base_size, base_size * 0.5)  # moderate — half size
        reason = f"moderate_spread({spread}¢)"
    else:
        size = min(base_size, 25.0)  # thin — floor at $25
        reason = f"thin_spread({spread}¢)_floored"

    # Phase 2: OI cap (when open_interest available)
    if open_interest is not None and open_interest > 0:
        oi_cap = open_interest * 0.05
        if size > oi_cap:
            size = oi_cap
            reason += f"_oi_cap({oi_cap:.0f})"

    return round(size, 2), reason
```

Add `market_impact_reason` to the trade log for post-DEMO review.

---

_Market Impact Ceiling section added 2026-03-13. Pre-LIVE action item: add spread proxy to strategy.py before first real-money deployment._
