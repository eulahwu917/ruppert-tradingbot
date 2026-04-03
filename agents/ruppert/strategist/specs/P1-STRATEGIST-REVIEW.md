# P1 Issues — Strategist Domain Review
_Date: 2026-04-03_
_Author: Strategist_
_Scope: strategy.py, optimizer.py, prediction_scorer.py, brier_tracker.py, crypto_15m.py (signal logic only), autoresearch.py, polymarket_client.py_

---

## ⚠️ URGENT PRE-READ: Daily Module Status

**crypto_threshold_daily_btc: 3.4% WR on 145 trades | crypto_band_daily_btc: 6.6% WR on 178 trades**

These modules are not losing slowly — they are hemorrhaging. At 3–7% WR you are not funding a bad strategy, you are funding a near-random coin-flip with costs attached. See bottom section for full assessment and recommendation.

---

## P0 Escalation Candidates

| Issue | Current Priority | Recommended | Rationale |
|-------|-----------------|-------------|-----------|
| ISSUE-117 | P1 | **→ P0** | `vol_ratio=0` bypasses ALL Kelly shrinkage and returns full unscaled position. If any signal path delivers vol_ratio=0 (data miss), we're betting full Kelly. Active financial risk right now. |
| ISSUE-040 | P1 | **→ P0** | Domain mismatch kills the entire optimizer feedback loop. Every threshold stays frozen at global default forever. Combined with the daily module crisis, this is not a P1. |
| ISSUE-006 | P1 | **→ P0** | Every NO-side Brier score and win rate is inverted. The entire calibration pipeline is backwards for the dominant trade side (NO=87.6% of alpha). Scoring noise undermines any optimizer action. |

---

## Issues by Tier: Fix Now → Defer → Accept

### ── TIER 1: FIX NOW ──

| ID | Title | Domain File | Impact | Effort | Sequencing | Recommendation |
|----|-------|-------------|--------|--------|------------|----------------|
| **ISSUE-117** | `vol_ratio=0` bypasses Kelly shrinkage → full unscaled Kelly | `strategy.py` | **HIGH** | **Small** | None | **Fix Now** |
| **ISSUE-040** | Scorer writes `domain: "crypto_dir_15m_btc"`, optimizer detects `"crypto"` | `prediction_scorer.py`, `optimizer.py` | **HIGH** | **Small** | None | **Fix Now** |
| **ISSUE-006** | NO-side Brier/win-rate inverted | `prediction_scorer.py` | **HIGH** | **Small** | None | **Fix Now** |
| **ISSUE-114** | Signal weights not asserted to sum to 1.0 | `crypto_15m.py` | **HIGH** | **Small** | None | **Fix Now** |
| **ISSUE-129** | Near-zero OI delta → astronomical z-score spike | `crypto_15m.py` | **HIGH** | **Small** | None | **Fix Now** |
| **ISSUE-116** | Polymarket ETH alias matches EtherFi/Ethena/stETH | `polymarket_client.py` | **Medium** | **Small** | None | **Fix Now** |
| **ISSUE-104** | `_module_cap_missing` unassigned when `module=None` → NameError | `strategy.py` | **Medium** | **Small** | None | **Fix Now** |
| **ISSUE-089** | Polymarket `yes_price` semantic mismatch — "above $X" ≠ "bullish" | `polymarket_client.py` | **Medium** | **Medium** | Depends on daily module decision | **Fix Now** |
| **ISSUE-004** | `brier_tracker.py` hardcoded path → predictions go to wrong dir | `brier_tracker.py` | **Medium** | **Small** | None | **Fix Now** |
| **ISSUE-101** | `brier_tracker.score_prediction()` allows duplicate entries | `brier_tracker.py` | **Medium** | **Small** | None | **Fix Now** |

---

### ── TIER 2: FIX SOON (SPRINT QUEUE) ──

| ID | Title | Domain File | Impact | Effort | Sequencing | Recommendation |
|----|-------|-------------|--------|--------|------------|----------------|
| **ISSUE-057** | 15m Polymarket weight used for daily-scale trade | `crypto_threshold_daily.py` | **High** | **Small** | Daily module must remain active | **Fix Now if daily stays on** |
| **ISSUE-041** | `analyze_daily_cap_utilization()` double-counts closed trades | `optimizer.py` | **Medium** | **Small** | None | **Fix Soon** |
| **ISSUE-046** | `analyze_exit_timing()` reads nonexistent `exit_timestamp` field | `optimizer.py` | **Medium** | **Small** | None | **Fix Soon** |
| **ISSUE-005** | Optimizer globs `logs/` instead of `logs/trades/` → sees zero live trades | `optimizer.py` | **Medium** | **Small** | None | **Fix Soon** |
| **ISSUE-050** | Scorer only uses first buy leg for scale-in trades | `prediction_scorer.py` | **Low** | **Small** | ISSUE-006 fixed first | **Fix Soon** |
| **ISSUE-103** | Multi-day positions: scorer writes `null predicted_prob` when buy date ≠ settle date | `prediction_scorer.py` | **Medium** | **Small** | None | **Fix Soon** |
| **ISSUE-069** | `crypto_15m.py` fallback `getattr()` uses Phase 1 weights on config failure | `crypto_15m.py` | **Medium** | **Small** | None | **Fix Soon** |
| **ISSUE-105** | Window cap counter overcharged on trim | `strategy.py` | **Low** | **Small** | None | **Fix Soon** |
| **ISSUE-088** | `_resolve_condition_to_market` uncached → 300 sequential Gamma API calls | `polymarket_client.py` | **Medium** | **Medium** | None | **Fix Soon** |

---

### ── TIER 3: DEFER ──

| ID | Title | Domain File | Impact | Effort | Sequencing | Recommendation |
|----|-------|-------------|--------|--------|------------|----------------|
| **ISSUE-016** | Band module date filter skips same-day-settling contracts | `crypto_band_daily.py` | **High (if module active)** | **Small** | Depends on daily module decision | **Defer until daily pause/continue decided** |

---

## Detailed Annotations

---

### ISSUE-117 — `vol_ratio=0` bypasses Kelly shrinkage
**File:** `strategy.py` → `calculate_position_size()`
**Priority bump: P1 → P0**

**What's broken:**
```python
if vol_ratio > 0:
    kelly_size *= (1.0 / vol_ratio)
```
If `vol_ratio=0` (data miss), the condition is False and kelly_size is returned unscaled. This is the exact opposite of the intended fail-safe. Missing vol data should produce a *smaller* position or zero, not a full unscaled Kelly bet.

**Impact: HIGH.** Any signal path that delivers `vol_ratio=0` — whether through missing OKX candles, API timeout, or a module that doesn't populate this field — silently gets a maximum-sized position instead of a minimum-sized one. The Kelly formula on a good edge signal can push position_usd to the MAX_POSITION_PCT cap, but that's still the maximum when we have the least information. This is a risk management failure, not a data quality footnote.

**Effort: SMALL.** One-line guard: change `if vol_ratio > 0` to `if vol_ratio > 0 else return 0.0` (or shrink to a conservative default).

**Sequencing:** None. Fix independently.

**Recommendation: Fix Now. Bump to P0.**

---

### ISSUE-040 — Domain mismatch between scorer and optimizer
**Files:** `prediction_scorer.py`, `optimizer.py`
**Priority bump: P1 → P0**

**What's broken:**
`prediction_scorer.py` writes `domain: "crypto_dir_15m_btc"` (per-asset module name).
`optimizer.py`'s `detect_module()` does: `if "BTC" in t: return "crypto"`.

The optimizer never sees `"crypto_dir_15m_btc"` because it's generating the domain tag from the *ticker*, not reading the already-written `domain` field. And since `get_domain_trade_counts()` re-derives domain from ticker rather than reading the `domain` field in scored_predictions.jsonl, the two pipelines are speaking different languages.

**Impact: HIGH.** Per-domain threshold optimization is permanently blind. Every domain stays at global defaults regardless of actual performance data. This is the optimizer's central function — it can't do its job.

**Effort: SMALL.** Two options:
1. Align `detect_module()` to match scorer's `domain` field values (preferred — canonical names already established).
2. Have scorer write the short form that optimizer expects.

Either way, one small change in one function. Alignment with the B1 taxonomy (crypto_dir_15m_btc, etc.) is the right path.

**Sequencing:** None. But fix before next optimizer run.

**Recommendation: Fix Now. Bump to P0.**

---

### ISSUE-006 — NO-side Brier/win-rate inverted
**File:** `prediction_scorer.py`
**Priority bump: P1 → P0**

**What's broken:**
`prediction_scorer.py` derives outcome from `settlement_result` but never flips it for NO-side trades. For a NO trade, a YES settlement (contract resolved YES) means we *lost*, but the scorer records `outcome=1` (win). This inverts every Brier score and win rate for NO-side positions.

**Impact: HIGH.** NO-side trades are 87.6% of our alpha engine (from MEMORY). Every calibration metric for the dominant trade side is wrong. The Brier tracker, confidence tier analysis, and optimizer win-rate proposals are all computing against inverted outcomes. If we ever act on optimizer proposals, we're tuning in the wrong direction.

**Effort: SMALL.** Add a NO-side flip:
```python
if rec.get('side') == 'no' and _outcome is not None:
    _outcome = 1 - _outcome
```

**Sequencing:** Fix before any optimizer run. ISSUE-050 (scale-in scoring) depends on this.

**Recommendation: Fix Now. Bump to P0.**

---

### ISSUE-114 — Signal weights not asserted to sum to 1.0
**File:** `crypto_15m.py`
**Priority: P1 → keep P1, but fix immediately**

**What's broken:**
```python
W_TFI  = getattr(config, 'CRYPTO_15M_DIR_W_TFI',  0.42)
W_OBI  = getattr(config, 'CRYPTO_15M_DIR_W_OBI',  0.25)
W_MACD = getattr(config, 'CRYPTO_15M_DIR_W_MACD', 0.15)
W_OI   = getattr(config, 'CRYPTO_15M_DIR_W_OI',   0.18)
```
Current defaults: 0.42 + 0.25 + 0.15 + 0.18 = **1.00** ✓ — OK in default config.

But any config override that misses one weight (e.g., tuning W_TFI without updating W_OI) silently produces a composite score that doesn't map cleanly to a probability. The sigmoid still fires, but the z-score composite means something different — signal strength is rescaled without anyone noticing.

**Impact: HIGH** (conditional). Default weights are clean. But if a config change introduces an imbalance, the resulting P_directional is wrong in a silent, non-obvious way that won't show up in any diagnostic.

**Effort: SMALL.** Add at module load time:
```python
assert abs(W_TFI + W_OBI + W_MACD + W_OI - 1.0) < 1e-6, f"Signal weights sum to {W_TFI+W_OBI+W_MACD+W_OI:.4f} — must be 1.0"
```

**Sequencing:** None.

**Recommendation: Fix Now.**

---

### ISSUE-129 — Near-zero OI delta → astronomical z-score spike
**File:** `crypto_15m.py` → `fetch_oi_conviction()`

**What's broken:**
```python
oi_delta_pct = (curr_oi - prev_oi) / prev_oi
```
If `prev_oi` is near-zero (first interval after OI data starts populating, or after a market restart), the delta_pct explodes. The z-score clips to [-2, 2], so the OI z-score is pinned at ±2, giving OI 2× its normal influence on the composite.

**Impact: HIGH.** For the OI signal weight of 0.18, a z-score of +2 contributes 0.36 to `raw_score`, which is significant. On thin OKX markets (SOL, DOGE, XRP), this can trigger entries or edge calculations on essentially noise data.

**Effort: SMALL.** Guard:
```python
if prev_oi < 1e-6:  # near-zero guard
    return {'oi_z': 0.0, 'stale': False, 'raw': 0.0, 'ts': last_ts}
```

**Sequencing:** None.

**Recommendation: Fix Now.**

---

### ISSUE-116 — Polymarket ETH alias matches EtherFi/Ethena/stETH
**File:** `polymarket_client.py` → `_ASSET_ALIASES`

**What's broken:**
```python
"ETH":  ["eth"],        # "eth" is a substring of "ethereum" — filter works
```
But `eth` is also a substring of `etherfi`, `ethena`, `steth`, `tether`, `together`, `health`, etc. The `_asset_in_title()` check is a substring match, not a word boundary match. ETH consensus signal can pull market data from entirely different assets.

**Impact: MEDIUM-HIGH.** ETH is one of the two highest-volume 15m assets. If the consensus market for ETH comes from an EtherFi or Ethena market, the signal direction is uncorrelated with ETH price movement. This is wrong signal contamination for a core asset.

**Effort: SMALL.** Add word-boundary check:
```python
"ETH": ["eth ", " eth", "ethereum"],  # space-padded to avoid substring hits
```
Or use regex word boundary in `_asset_in_title()`.

**Sequencing:** None.

**Recommendation: Fix Now.**

---

### ISSUE-089 — Polymarket `yes_price` semantic mismatch for daily modules
**File:** `polymarket_client.py` → `get_crypto_daily_consensus()`

**What's broken:**
The daily module uses `yes_price` from a Polymarket "Will BTC be above $X on date Y?" market. A YES_price of 0.70 means "70% chance price is above $X at close." Whether that means "bullish" depends on where $X is relative to current spot. If BTC is currently at $82K and the strike is $70K, yes_price=0.70 is essentially a baseline confidence, not a directional signal.

More critically: the yes_price for an "above $X" market where X is below spot is *always* high (>0.60), systematically biasing any downstream use of this as a "bullish consensus" signal toward YES entries.

**Impact: MEDIUM.** This is the root of ISSUE-057 amplified — not just the wrong timescale, but the wrong semantics entirely. A `yes_price=0.70` on "BTC above $70K" ≠ "70% chance BTC goes up today." It means "70% chance BTC stays above $70K by EOD," which is almost tautological if BTC is at $82K.

**Effort: MEDIUM.** The fix requires either (a) mapping strike price vs. current spot to interpret the signal correctly, or (b) restricting to "at-the-money" markets (yes_price closest to 0.50). The `_score_crypto_daily_market()` function already prefers price_distance from 0.50, which is the right instinct — but we need to actually validate whether the fetched market IS near-ATM before trusting the direction.

**Sequencing:** ISSUE-057 should be fixed simultaneously (same PR probably). Also depends on daily module decision.

**Recommendation: Fix Now if daily modules stay on; note in spec that the semantic interpretation needs explicit documentation and validation.**

---

### ISSUE-088 — Polymarket uncached API storm (300 sequential calls)
**File:** `polymarket_client.py` → `_resolve_condition_to_market`

**Note:** Looking at the actual polymarket_client.py code, I don't see `_resolve_condition_to_market()` — this function may live in a different file or may have been renamed. The *in-process cache* for `get_markets_by_keyword` and `get_crypto_consensus` already exists with 5-minute TTL. However, the keyword list `_CRYPTO_KEYWORDS` issues 2 keywords × 5 assets = 10 API calls per `get_crypto_consensus` call. If this is called per-market-tick (multiple times per 15m window per asset), the cache would prevent most calls, but the initial cold-start could still be expensive.

**Impact: MEDIUM.** With the current per-process cache, repeated calls within 5 minutes are free. The risk is: (a) if the process restarts frequently, cold-starts are expensive; (b) the "300 calls" described may apply to a different code path than what I'm reading. Needs Dev verification.

**Effort: MEDIUM.** Verify where the 300-call storm occurs. The cache already exists — may be as simple as extending TTL or ensuring cache is shared across call sites.

**Sequencing:** None.

**Recommendation: Fix Soon — verify first whether current caching handles this or if there's a separate call site.**

---

### ISSUE-057 — 15m Polymarket weight used for daily-scale trade
**File:** `crypto_threshold_daily.py`

**What's broken:**
The daily threshold module imports and uses `get_crypto_consensus()` (15m short-window markets, 5-min cache) as part of its signal stack. The 15m consensus price for "Will BTC be up in the next 15 min?" is not correlated with the "Will BTC be above $X today?" question the daily module is trading. This is signal timescale contamination — noise injection.

**Impact: HIGH** (if daily modules remain active). 15m volatility consensus in a daily position is directionally meaningless. If the Polymarket weight is non-trivial (ISSUE says 20%), this could be actively hurting daily module performance.

**Effort: SMALL.** Switch to `get_crypto_daily_consensus()` — already implemented in polymarket_client.py as of recent work. One import change.

**Sequencing:** Must decide whether to pause daily modules first. If we pause them, fix anyway before re-enabling.

**Recommendation: Fix Now if daily stays on. Fix before re-enable if we pause.**

---

### ISSUE-005 — Optimizer globs `logs/` instead of `logs/trades/`
**File:** `optimizer.py` → `load_trades()`

**What's broken:**
```python
LOGS_DIR.glob("trades_*.jsonl"),
```
Looking at the actual optimizer.py code, `load_trades()` globs `LOGS_DIR` (= `logs/`). Post-migration, trade files live in `logs/trades/`. So the optimizer's trade load returns zero records. Every analysis — win rates, confidence tiers, sizing, cap utilization — runs against an empty dataset.

**Impact: MEDIUM.** The optimizer is effectively dead as a feedback mechanism. All six analyses return empty/zero. This matters more as trade volume grows, and urgently blocks any optimizer-based signal tuning for the daily modules crisis.

**Effort: SMALL.** Change `LOGS_DIR.glob(...)` to `(LOGS_DIR / "trades").glob(...)`. One-line fix.

**Sequencing:** Fix before ISSUE-040 (domain alignment), since fixing the path first verifies the full pipeline.

**Recommendation: Fix Soon.**

---

### ISSUE-041 — `analyze_daily_cap_utilization()` double-counts closed trades
**File:** `optimizer.py`

**What's broken:**
The function sums `size_dollars` for all records matching the date. If a trade has both a `buy` record AND an `exit`/`settle` record (both on the same day), `size_dollars` gets counted twice. The cap utilization figure is 2× actual.

**Impact: MEDIUM.** Produces false FLAG signals ("cap underutilized") when it's actually being utilized normally. Any proposal to "relax MIN_EDGE to increase cap utilization" generated by the optimizer is potentially wrong.

**Effort: SMALL.** Filter to `action='buy'` or `action='open'` only before summing.

**Sequencing:** None.

**Recommendation: Fix Soon.**

---

### ISSUE-046 — `analyze_exit_timing()` reads nonexistent `exit_timestamp`
**File:** `optimizer.py`

**What's broken:**
```python
exit_ts = t.get("exit_timestamp")
```
The field is `exit_timestamp` but the actual log schema uses a different field name (likely just `timestamp` on the exit record). Result: `exit_timestamp` always returns None, `hold_times` list is always empty, exit timing analysis always returns count=0.

**Impact: MEDIUM.** Exit timing optimization is permanently blind. The "avg hold time" metric — which is the primary signal for whether we should implement a time-based exit rule — is always "no data."

**Effort: SMALL.** Check actual schema field name in exit records and fix the key.

**Sequencing:** None.

**Recommendation: Fix Soon.**

---

### ISSUE-004 — `brier_tracker.py` writes to hardcoded path
**File:** `brier_tracker.py`

**What's broken:**
```python
_LOGS_DIR = Path(__file__).parent / "logs"
_PRED_FILE = _LOGS_DIR / "predictions.jsonl"
_SCORED_FILE = _LOGS_DIR / "scored_predictions.jsonl"
```
This hardcodes paths relative to the brier_tracker.py file location (`environments/demo/logs/`). In production, `prediction_scorer.py` uses `get_paths()['logs']` (the proper env-config path), but `brier_tracker.py` is writing to a different location. The two scoring pipelines are writing to different files.

**Impact: MEDIUM.** brier_tracker's `log_prediction()` and `score_prediction()` calls accumulate in the wrong location. The optimizer's `load_scored_predictions()` reads from the correct path and won't see brier_tracker's data. Calibration is split between two files.

**Effort: SMALL.** Import `get_paths()` from env_config and replace hardcoded paths.

**Sequencing:** None. Fix independently.

**Recommendation: Fix Now.**

---

### ISSUE-101 — `brier_tracker.score_prediction()` allows duplicate entries
**File:** `brier_tracker.py`

**What's broken:**
`score_prediction()` searches `predictions.jsonl` for the last unscored prediction for a ticker. If called twice for the same settlement (e.g., by two different code paths), it finds the same unscored prediction both times and writes two scored entries to `scored_predictions.jsonl`. The sample count inflates.

**Impact: MEDIUM.** Inflated Brier sample count makes the calibration look more reliable than it is. If the Bonferroni threshold check relies on N, a 2× inflated N increases false positives.

**Effort: SMALL.** Check `scored_predictions.jsonl` before writing: if the ticker is already scored with the same `ts`, skip.

**Sequencing:** Fix alongside ISSUE-004 (same file).

**Recommendation: Fix Now.**

---

### ISSUE-104 — `_module_cap_missing` unassigned when `module=None`
**File:** `strategy.py` → `should_enter()`

**What's broken:**
```python
if module is not None:
    _module_key = module.upper() + '_DAILY_CAP_PCT'
    _module_cap = getattr(config, _module_key, None)
    _module_cap_missing = _module_cap is None
    ...
```
The variable `_module_cap_missing` is only assigned inside the `if module is not None` block. Later in the function:
```python
if module is not None and _module_cap_missing:
    _result['warning'] = ...
```
This is safe IF Python doesn't see `_module_cap_missing` without the outer check. But if the code path ever changes or a linter/static analyzer runs, this is a latent NameError. More importantly, any direct call with `module=None` where downstream code accidentally references `_module_cap_missing` will raise NameError.

**Impact: MEDIUM.** Not currently crashing in known paths (the second reference is also gated by `module is not None`). But it's a trap waiting to spring.

**Effort: SMALL.** Initialize `_module_cap_missing = False` before the block.

**Sequencing:** None.

**Recommendation: Fix Now (it's 1 line, negligible risk).**

---

### ISSUE-103 — Multi-day positions: scorer writes `null predicted_prob`
**File:** `prediction_scorer.py`

**What's broken:**
The scorer matches buy records by `(ticker, date)` key. For multi-day positions, the buy date is, say, 2026-04-01, but the settle record date is 2026-04-02. The key lookup `buy_index.get((ticker, settle_date))` fails, returning `{}`. No predicted_prob → `_brier = None` → calibration record is useless.

**Impact: MEDIUM.** Daily crypto modules frequently hold overnight. Every overnight position contributes a null calibration record. The Brier sample is systematically biased toward same-day (15m) trades.

**Effort: SMALL.** Build buy_index keyed by ticker alone (or by both, with ticker-only fallback): `buy_index[ticker] = rec` (most recent buy). This handles overnight holds correctly.

**Sequencing:** Fix after ISSUE-006 (NO-side flip) — same module, do together.

**Recommendation: Fix Soon.**

---

### ISSUE-050 — Scorer uses only first buy leg for scale-ins
**File:** `prediction_scorer.py`

**What's broken:**
For a position that has multiple buy records (scale-in), the scorer uses the first `buy_index` match only. The average probability across legs would give a more accurate Brier score for the position as a whole.

**Impact: LOW.** Scale-ins are relatively rare. The bias is small. More importantly, we need ISSUE-006 fixed first — if NO-side is inverted, averaging inverted scores produces double-wrong results.

**Effort: SMALL.** Change buy_index to store a list and average probabilities.

**Sequencing:** ISSUE-006 must be fixed first.

**Recommendation: Fix Soon (after ISSUE-006).**

---

### ISSUE-069 — `crypto_15m.py` fallback `getattr()` uses Phase 1 weights
**File:** `crypto_15m.py`

**What's broken:**
The weights at module load time use `getattr(config, ..., default)`. The default values in the code are the old Phase 1 weights:
```python
W_TFI  = getattr(config, 'CRYPTO_15M_DIR_W_TFI',  0.42)  # default
W_OBI  = getattr(config, 'CRYPTO_15M_DIR_W_OBI',  0.25)
...
```
If the config import fails silently, the signal weights revert to Phase 1 without any log warning or assert failure. Combined with ISSUE-114 (no weight sum assertion), this would produce a wrong composite signal silently.

**Impact: MEDIUM.** Config import failures are rare but not impossible (module load order issues on startup, especially with the circular import risk in the agents directory). The consequence is wrong signal weights for an entire session.

**Effort: SMALL.** Add an explicit log warning if fallback is used: `logger.warning('[crypto_15m] Config import failed — using fallback weights. W_TFI=...')`

**Sequencing:** Fix with ISSUE-114 in same PR.

**Recommendation: Fix Soon.**

---

### ISSUE-105 — Window cap counter overcharged on position trim
**File:** `strategy.py` (and `crypto_15m.py` internal cap logic)

**What's broken:**
When a position is trimmed to fit within the window cap (e.g., `position_usd = trimmed`), the reservation code still adds the pre-trim amount to `_window_exposure`. This means valid trades in the same window are blocked sooner than necessary.

**Impact: LOW.** The cost is foregone trades in the same window — not a loss, just missed opportunity. At current capital scale this is a few dollars.

**Effort: SMALL.** Ensure the reservation uses the post-trim amount.

**Sequencing:** None.

**Recommendation: Fix Soon.**

---

### ISSUE-016 — Band module date filter skips same-day-settling contracts
**File:** `crypto_band_daily.py`

**What's broken:**
The date filter in crypto_band_daily excludes contracts settling today. But "today" IS the target — the band module is designed to trade same-day crypto price range contracts. This filter inverts the module's purpose.

**Impact: HIGH** (if module active). If this is correct, the band module never trades the contracts it was built for. 178 losing trades at 6.6% WR might partially be explained by trading tomorrow's contracts (different risk profile) instead of today's.

**Effort: SMALL.** Remove or invert the date filter.

**Sequencing:** Depends on daily module pause decision. If we pause daily modules, investigate this as part of root cause analysis before re-enabling.

**Recommendation: Defer — tied to daily module decision. Investigate as part of pause/restart analysis.**

---

## Downgrade Recommendations

No issues in the focused list should be downgraded from P1. The issues not in Strategist domain (dashboard, settlement, position_tracker) remain correctly prioritized as P1 by the original list.

---

## Daily Module Assessment: Pause or Fix?

### The Data

- **crypto_threshold_daily_btc**: 3.4% WR on 145 trades
- **crypto_band_daily_btc**: 6.6% WR on 178 trades
- **Total losses**: Substantial. At even $5/trade avg size: ~$1,100 lost on threshold, ~$1,660 lost on band.

### The Hypothesis Stack

**Why these could be infrastructure bugs (fixable P1s):**
1. **ISSUE-017** (P1, not my domain): NO-side orders use wrong price → orders fill at wrong cost or don't fill. If this causes systematically poor fills, WR would be suppressed.
2. **ISSUE-016** (my domain): Band module filters out same-day contracts → may be trading the wrong universe.
3. **ISSUE-057** (my domain): 15m Polymarket noise injected into daily signal → pollution.
4. **ISSUE-089** (my domain): "Above $X" semantics always biases toward YES → NO-side signal corrupted.
5. **ISSUE-053** (P1, not my domain): Daily cap race condition doubles effective cap → potential overtrading.

**Why these might be fundamentally broken signals (not fixable via P1s):**
1. At 3.4% and 6.6% WR, you are not just in a drawdown — you are flipping coins with costs. Random coin flips produce ~50% WR. Getting 3-7% requires *actively bad signal* or *structural execution problems*.
2. The threshold module's signal may be based on price level prediction (threshold models) that don't have genuine edge on daily BTC volatility markets. Unlike the 15m module which uses rich real-time microstructure data (TFI, OBI, MACD, OI), the daily modules' signal quality is unclear to me without reading their code.
3. The crypto band module has a plausible structural problem (ISSUE-016) that might explain most losses — but 6.6% WR is still extreme even if we're trading the wrong expiry.

### My Read

**These look more like structural execution + signal mismatch problems than pure infrastructure bugs.**

The P1 fixes (ISSUE-017, ISSUE-016, ISSUE-057) should help, but I don't expect them to recover 40–50 WR% from where these modules currently sit. The WR pattern is too extreme to explain with pricing bugs and Polymarket noise alone.

### Recommendation: **PAUSE BOTH DAILY MODULES NOW**

**Rationale:**
1. At 3.4% and 6.6% WR, each additional trade is negative expected value at essentially any edge threshold. We are paying to collect loss data.
2. The P1 fixes for these modules (ISSUE-016, ISSUE-017, ISSUE-057) can be verified before re-enable.
3. Pausing does not prevent us from shadow-running to collect data. We can run the modules in DRY_RUN and analyze their signal outputs without placing orders.
4. The 15m module is not affected by this pause. Our primary alpha engine (crypto_dir_15m) remains running.
5. Re-enable criteria should be: all P1 fixes deployed + 50+ shadow trades analyzed + WR in shadow mode > 45%.

**If David decides to keep them running:** Fix ISSUE-017 first (not my domain, but the highest immediate execution fix), then ISSUE-057 and ISSUE-016 immediately after. Add a loss circuit breaker specific to each daily module (ISSUE-090 direction).

---

## Summary: Top 10 Actions

| Priority | Issue | Action | Owner |
|----------|-------|--------|-------|
| 1 | **PAUSE daily modules** | Set DRY_RUN=True for crypto_threshold_daily and crypto_band_daily immediately | CEO → David decision |
| 2 | **ISSUE-117** | Fix vol_ratio=0 Kelly bypass → P0 | Dev sprint |
| 3 | **ISSUE-006** | Fix NO-side outcome inversion | Dev sprint |
| 4 | **ISSUE-040** | Align scorer domain names with optimizer detect_module | Dev sprint |
| 5 | **ISSUE-114** | Assert signal weights sum to 1.0 | Dev sprint |
| 6 | **ISSUE-129** | Guard near-zero OI delta | Dev sprint |
| 7 | **ISSUE-004 + ISSUE-101** | Fix brier_tracker paths and dedup | Dev sprint |
| 8 | **ISSUE-116** | Fix ETH alias substring matching | Dev sprint |
| 9 | **ISSUE-005 + ISSUE-041 + ISSUE-046** | Fix optimizer data pipeline (path, double-count, field names) | Dev sprint |
| 10 | **ISSUE-057 + ISSUE-089** | Fix Polymarket signal timescale and semantics (if daily modules restart) | Dev sprint (pre-re-enable) |

---

_Written by: Strategist_
_Reviewed: All 19 targeted issues plus daily module assessment_
_Next step: CEO review → David decision on daily module pause → Dev sprint scoping_
