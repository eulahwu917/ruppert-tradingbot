# crypto_1d Module — Architecture Proposal
**Date:** 2026-03-30  
**Author:** Strategist (Ruppert)  
**Status:** REVISED v2 — DS blockers and concerns resolved  
**Context:** Daily crypto price band trading on Kalshi (KXBTCD, KXETHD above/below series only)

> **Revision log:**  
> - v2 (2026-03-30): Resolved DS BLOCKER 1 (ticker collision), BLOCKER 2 (funding rate source), CONCERN 1 (OI caching spec), CONCERN 2 (Task Scheduler + capital contention), CONCERN 3 (config naming), CONCERN 4 (cross-module position guard). See §11 for full change summary.

---

## Executive Summary

The `crypto_1d` module targets daily Kalshi crypto markets (5pm EDT settlement via CF Benchmarks RTI). Unlike `crypto_15m` which exploits intraday microstructure signals in short windows, `crypto_1d` operates at a fundamentally different edge layer: **overnight dislocations, cross-exchange funding dynamics, and 24h momentum regime classification**. Signal design, entry timing, market selection, and sizing all differ materially from the 15m module.

**Key decisions in brief:**

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Signal stack | 24h momentum + funding rate + ATR band selection + OI regime | Microstructure (TFI/OBI) is noise at daily resolution |
| Entry timing | 09:30–11:30 ET (2-hour primary window) | Overnight gap is priced in; morning vol provides signal clarity |
| Market type | **Above/below (KXBTCD/KXETHD) ONLY** | Eliminates ticker collision with hourly crypto_only scanner (see §6) |
| Sizing | WINDOW_CAP_PCT = 0.05, CRYPTO_1D_DAILY_CAP_PCT = 0.15, per-ticker cap = 0.03 | Daily risk is 1 bet per asset per day; sizing must reflect this |
| Module fit | Parallel to crypto_15m, separate cap pool, shared infrastructure, explicit cross-module guard | No interference with existing 15m signals or hourly positions |
| Funding source | **Binance Futures via existing `_compute_funding_z_scores()`** | Reuses existing infrastructure; no new API client |

---

## 1. Market Structure

### Kalshi Daily Crypto Markets

| Series | Type | Settlement | Assets |
|--------|------|------------|--------|
| KXBTCD-YYMMDDHHMM | Above/below (YES = price above strike) | 5pm EDT daily (CF Benchmarks RTI, 60-sec average) | BTC |
| KXETHD-YYMMDDHHMM | Above/below | Same | ETH |

**`crypto_1d` trades KXBTCD and KXETHD only.** Band markets (KXBTC, KXETH) are exclusively owned by the hourly `crypto_only` scanner. SOL/XRP/DOGE daily above/below markets are deferred to Phase 2 pending liquidity review.

**Settlement mechanic:** Same CF Benchmarks RTI as 15m markets. The 5pm EDT close is a fixed daily event — we always know the exact time, meaning we can plan entry timing precisely.

**Liquidity character:** Seeded by Kalshi, thin secondary trading. Spreads are wider than 15m (expect 5–15c vs 3–8c). Book depth is shallower on a per-contract basis. This fundamentally constrains position sizing.

---

## 2. Signal Design

### Why 15m Signals Don't Work at Daily Timeframe

| 15m Signal | Daily Resolution Problem |
|------------|--------------------------|
| TFI (tape flow imbalance) | 24h trades → averages to noise; bursts during funding events don't predict EOD direction |
| OBI (order book imbalance) | Intraday microstructure; refreshes every few seconds; not predictive across a full trading day |
| MACD-5m | 5-min candlestick MACD captures hourly momentum, not daily regime |
| OI-delta | Useful at daily scale but needs different baseline and directionality framing |

### Proposed Signal Stack for crypto_1d

#### Signal 1: 24h Price Momentum (Weight: 0.30)
**Source:** OKX perpetual swap last price + Coinbase spot (existing infrastructure)  
**Computation:**
- `pct_24h = (current_price - price_24h_ago) / price_24h_ago`
- Normalize via 30-day rolling z-score of daily returns
- Strong momentum (z > 1.5) → bias toward continuation
- Mean-reversion signal when z > 3.0 (extreme extension)

**Rationale:** At the daily timeframe, trend-following beats microstructure. Assets that moved >2% overnight tend to continue through settlement in trending regimes. This is the primary directional signal.

**Implementation:** OKX already provides daily candles (`bar=1D`, `limit=30`) — same endpoint used in `crypto_15m.py` for `_fetch_30d_avg_okx_vol`. Reuse.

#### Signal 2: Funding Rate Regime (Weight: 0.25)
**Source:** Binance Futures — existing `_compute_funding_z_scores()` in `crypto_client.py`

**⚠️ BLOCKER 2 RESOLVED:** The original proposal referenced OKX `/api/v5/public/funding-rate-history`. This is **replaced** with the existing Binance Futures funding rate infrastructure. No new API client or endpoint needed.

**Computation:**
- Fetch last 3 × 8h funding rate periods from Binance Futures history (already available via `_compute_funding_z_scores()`)
- `funding_24h_cumulative = rate_t0 + rate_t-8h + rate_t-16h`
- Z-score against 30-day rolling mean of daily cumulative funding (3 × daily 8h rates)
- Positive cumulative funding (longs paying shorts) → mild bearish pressure; market is overextended long
- Funding flip to strongly negative → potential short squeeze catalyst
- Use as a **regime classifier**: `funding_regime ∈ {bull_overheat, neutral, bear_overheat}`
- Risk filter R6: `|funding_24h_z| > 3.5` → skip entry (extreme funding, too noisy for directional bet)

**Implementation note for Dev:** `_compute_funding_z_scores()` currently returns per-period z-scores. Extend to also return `funding_24h_cumulative` (sum of last 3 rates). This is a small additive change to the existing function — no new Binance endpoints required.

#### Signal 3: Daily ATR Band Selector (Weight: 0.25)
**Source:** OKX daily OHLC candles (same endpoint, `bar=1D`)  
**Computation:**
- `ATR_14 = 14-day Average True Range` computed from daily candles
- `ATR_pct = ATR_14 / current_price` → normalized daily range expectation
- Use `ATR_pct` to:
  1. **Score above/below confidence:** If price + ATR_pct/2 still safely above strike → high above confidence
  2. **Size the trade:** High ATR days → smaller size (more uncertainty); low ATR → fuller size

**Rationale:** CF Benchmarks RTI averages 60 seconds around 5pm — daily ATR captures the expected range with high reliability. This is the signal that directly answers "which strike should I buy?" for KXBTCD/KXETHD above/below strikes.

**Implementation:** Reuse existing OKX candle fetch. ATR computation is simple — no new libraries.

#### Signal 4: Open Interest Regime (Weight: 0.20)
**Source:** OKX `/api/v5/public/open-interest` (existing in `crypto_15m.py`)  
**Computation (modified for daily):**
- `OI_delta_24h = (current_OI - OI_24h_ago) / OI_24h_ago`
- Cross with price direction: rising OI + rising price = genuine long interest; rising OI + falling price = short-building
- `OI_regime ∈ {long_buildup, short_buildup, unwind, neutral}`

**⚠️ CONCERN 1 RESOLVED — OI caching fully specified:**

**File path:** `environments/demo/logs/oi_1d_snapshot.json`

**File format:**
```json
{
  "BTC": {
    "oi": 285432.17,
    "timestamp": "2026-03-30T09:30:00Z"
  },
  "ETH": {
    "oi": 1843221.50,
    "timestamp": "2026-03-30T09:30:00Z"
  }
}
```

**First-run bootstrap:** If `oi_1d_snapshot.json` does not exist or has no entry for an asset, `OI_delta_24h = 0.0` and `OI_regime = neutral`. Write the current OI snapshot to file and proceed with the other 3 signals. Do not skip the trade on first run solely due to missing OI history.

**Staleness handling:** If `(now - snapshot.timestamp) > 26h`, treat OI signal as `neutral` (signal contribution = 0.0, weight redistributed proportionally across S1/S2/S3). Log a warning. This prevents stale data from silently biasing the signal.

**Write cadence:** Overwrite `oi_1d_snapshot.json` at the end of each `evaluate_crypto_1d_entry()` call (after entry decision), capturing the OI at time of evaluation. This ensures the 24h-old baseline is always the previous day's scan-time OI.

#### Ancillary Signals (Not Weighted — Used as Filters)

**Overnight Gap Signal:**
- `gap_pct = (open_price_today - close_price_yesterday) / close_price_yesterday`
- If `|gap_pct| > ATR_pct × 0.5` → gap event detected
- Large gaps: bias toward mean reversion in strike selection (settlement tends to partially close gaps by 5pm)
- Source: OKX daily candles; no new infrastructure

**Polymarket 24h Crypto Markets (Exploratory):**
- Status: **Deferred to Phase 2.** Implement after core module is live.

**On-Chain Data (Not Recommended for v1):**
- Decision: Skip for v1. The existing OKX + Coinbase + Binance funding stack is sufficient.

### Signal Architecture Summary

```
crypto_1d Signal Stack
├── S1: 24h Momentum (OKX daily candle, z-scored)                weight=0.30
├── S2: Funding Rate Regime (Binance Futures, 24h cumulative)    weight=0.25
├── S3: ATR Strike Selector (OKX daily OHLC, 14-day ATR)        weight=0.25
├── S4: OI Regime (OKX OI snapshot, disk-persisted 24h delta)   weight=0.20
└── Filters (no weight, gate only)
    ├── Overnight Gap Detector (OKX daily candle)
    ├── CF Benchmarks Settlement Proxy (Coinbase spot at entry)
    └── [Phase 2] Polymarket 24h divergence nudge
```

**Composite score → P_settlement_above (for above/below markets)**

---

## 3. Entry Timing

### Analysis

The 5pm EDT settlement creates a well-defined daily event horizon. Unlike 15m markets where entry timing is driven by window-opening, 1d markets are always open — the question is **when signals are most reliable during the day**.

**Key insight:** The overnight move is already reflected in price by 9am. After 9:30am ET (US equity open), crypto tends to correlate with equity risk sentiment — this is when daily direction is often "decided." The 2pm–4pm ET range is post-lunch drift; 4:30–4:55pm ET is the settlement window where CF Benchmarks averaging begins.

### Proposed Entry Windows

**Primary Window: 09:30 – 11:30 ET (2-hour)**
- Overnight gap is fully priced in
- US equity market is open → crypto/equity correlation provides directional confirmation
- ATR-based strike selection is most reliable: the full day's range context is available
- Funding rate for the day's first 8h period is established
- **This is where we expect the cleanest edge**

**Secondary Window: 13:30 – 14:30 ET (1-hour, conditional)**
- Post-lunch re-entry if signals strengthened or a large move clarified direction
- Only enter if primary window was skipped OR position was closed early
- Stricter edge threshold: `MIN_EDGE × CRYPTO_1D_SECONDARY_EDGE_MULT (1.5×)` for secondary entries

**⚠️ CONCERN 2 RESOLVED — Capital contention at secondary window:**

13:30 ET = 10:30 AM PDT. The existing `crypto_only` 10am PDT scan fires at 13:00 ET — only 30 minutes before our secondary window opens. Both modules may be seeking capital simultaneously.

**Resolution:** The secondary window will be **gated by global exposure**:
```python
# Before secondary window entry:
global_exposure_pct = get_total_active_wager_pct()  # across ALL modules
if global_exposure_pct > 0.50:
    # Skip secondary window — capital is already deployed
    log("crypto_1d secondary skipped: global exposure {:.1%} > 50%".format(global_exposure_pct))
    return

# Additionally: secondary window already requires 1.5× edge threshold
# Combined effect: high-bar edge + available capital = only cleanest setups enter
```

This is a hard skip (not a size reduction) when global exposure exceeds 50%. The 1.5× edge threshold remains in effect even when exposure is below 50%.

**No Entry After: 15:00 ET**
- 2 hours before 5pm settlement
- Minimum hours to settlement gate: `MIN_HOURS_ENTRY['crypto_1d'] = 2.0h` (hard cutoff at 15:00 maps to exactly 2h before 17:00 settlement)

**Implementation:**
```python
CRYPTO_1D_PRIMARY_ENTRY_START_ET  = '09:30'
CRYPTO_1D_PRIMARY_ENTRY_END_ET    = '11:30'
CRYPTO_1D_SECONDARY_ENTRY_START   = '13:30'
CRYPTO_1D_SECONDARY_ENTRY_END     = '14:30'
CRYPTO_1D_NO_ENTRY_AFTER_ET       = '15:00'
CRYPTO_1D_SECONDARY_SKIP_EXPOSURE = 0.50   # skip secondary if global exposure >= this
```

**Entry trigger mechanism:** `crypto_1d` uses a **scheduled scan approach**:
- Run a full signal computation scan at 09:30 ET and again at 13:30 ET (secondary gated by exposure check)
- If signal meets threshold → evaluate and enter
- Use REST (not WS) for daily markets — polling rate 1 scan per entry window is sufficient

**⚠️ CONCERN 2 RESOLVED — Task Scheduler:**

A new dedicated Windows Task Scheduler task `Ruppert-Crypto1D` must be created. This is **separate** from the existing `Ruppert-CryptoOnly` task.

| Task | Trigger | Action |
|------|---------|--------|
| `Ruppert-CryptoOnly` (existing) | 10:00 AM PDT daily | Runs hourly crypto scanner (band markets) |
| `Ruppert-Crypto1D` (NEW) | 09:30 AM ET + 13:30 AM ET daily | Runs `crypto_1d.evaluate()` for BTC and ETH |

The 13:30 ET (10:30 PDT) secondary trigger fires 30 min after `Ruppert-CryptoOnly`. `Ruppert-Crypto1D` checks `get_total_active_wager_pct()` and skips if exposure > 50%.

---

## 4. Market Selection: Above/Below Only

### Decision: KXBTCD and KXETHD Exclusively

**⚠️ BLOCKER 1 RESOLVED — Ticker collision eliminated:**

The original proposal listed band markets (KXBTC, KXETH) as "opportunistic." DS correctly flagged that the existing `crypto_only` scanner already handles KXBTC and KXETH hourly band markets — including 5pm EDT settlement markets. Two modules entering the same contract is not acceptable.

**Resolution:** `crypto_1d` trades **only KXBTCD (BTC above/below) and KXETHD (ETH above/below)**. Band series (KXBTC, KXETH) are **off-limits** for `crypto_1d`. No exceptions.

This clean separation means:
- `crypto_only` owns all KXBTC / KXETH range band contracts
- `crypto_1d` owns all KXBTCD / KXETHD above/below contracts
- No overlapping tickers; no shared contract risk

The "opportunistic bands" language from v1 is removed entirely.

### Strike Selection for KXBTCD / KXETHD

- Compute `P_above(strike)` using: price + momentum signal + ATR
- Enter strike where `P_above(strike) - market_ask_above` is maximized and meets MIN_EDGE
- Prefer strikes 1-2 steps OTM from current price (better liquidity, still directional)
- Never enter strikes where `P_above < 0.15` or `P_above > 0.85` (too far OTM/ITM to have edge vs spread)

---

## 5. Sizing and Risk Framework

### Key Differences from 15m

| Parameter | crypto_15m | crypto_1d | Rationale |
|-----------|-----------|-----------|-----------|
| Opportunities per day (per asset) | ~90 windows | 1-2 entries | Far fewer shots; each matters more |
| Time to know if wrong | 15 minutes | Hours (until 5pm) | Can't rapidly iterate |
| Capital per trade | Small (daily cap spread over many trades) | Larger per trade | Must allocate meaningfully to matter |
| Drawdown visibility | Visible in hours | Committed until 5pm | Sizing must be conservative |

### Proposed Cap Structure

**⚠️ CONCERN 3 RESOLVED — Config naming confirmed:**

```python
# crypto_1d cap parameters (separate pool from crypto_15m)
# NOTE: CRYPTO_1D_DAILY_CAP_PCT is the correct name (not DAILY_WAGER_CAP_PCT)

# Per-entry caps
CRYPTO_1D_WINDOW_CAP_PCT      = 0.05   # max 5% of capital per entry (any single strike)
CRYPTO_1D_PER_ASSET_CAP_PCT   = 0.03   # max 3% of capital per asset per day

# Daily aggregate cap for this module
CRYPTO_1D_DAILY_CAP_PCT       = 0.15   # max 15% of capital total across all crypto_1d per day
                                        # Window and per-asset caps are self-enforced inside the module

# Secondary window capital contention gate
CRYPTO_1D_SECONDARY_SKIP_EXPOSURE = 0.50  # skip secondary if global exposure >= 50%

# Minimum and maximum position sizes
CRYPTO_1D_MIN_POSITION_USD    = 10.0   # don't bother below $10
CRYPTO_1D_MAX_POSITION_USD    = 200.0  # hard cap per entry (liquidity constraint)

# Edge thresholds
CRYPTO_1D_MIN_EDGE            = 0.08   # primary window minimum edge
CRYPTO_1D_SECONDARY_EDGE_MULT = 1.5   # 1.5× edge required for secondary window entries
CRYPTO_1D_BAND_MIN_EDGE       = 0.15   # (reserved for future band support; not used in v1)

# Circuit breaker
CRYPTO_1D_CIRCUIT_BREAKER_N   = 3     # halt after 3 consecutive complete losses
```

**`MIN_HOURS_ENTRY` addition for `strategy.py`:**
```python
MIN_HOURS_ENTRY = {
    'crypto_15m': 0.04,   # existing
    'crypto_1d':  2.0,    # NEW — hard cutoff at 15:00 ET = 2h before 17:00 settlement
}
```

This entry appears in `strategy.py` (or wherever `MIN_HOURS_ENTRY` is defined), not `config.py`. Dev to confirm file location. The `0.10` value in v1 was a per-trade buffer; the correct interpretation for `MIN_HOURS_ENTRY` is the no-entry gate, which maps to `CRYPTO_1D_NO_ENTRY_AFTER_ET = '15:00'` → 2.0h before 17:00 settlement.

### Sizing Logic: Half-Kelly with ATR Modifier

```python
# Base: Half-Kelly (same as 15m)
kelly_full = (P_win - cost) / (cost * (1 - cost))
kelly_half = kelly_full / 2

# ATR modifier: reduce size on high-vol days
# ATR_pct > 3% (BTC) → scale down by 0.7x
# ATR_pct < 1% (BTC) → scale up by 1.2x (capped)
atr_multiplier = clamp(1.0 - (ATR_pct_z - 1.0) * 0.15, 0.5, 1.2)

position_usd = min(
    kelly_half * capital * atr_multiplier,
    capital * CRYPTO_1D_WINDOW_CAP_PCT,        # 5% of capital
    CRYPTO_1D_MAX_POSITION_USD,                 # $200 hard cap
)
position_usd = max(position_usd, CRYPTO_1D_MIN_POSITION_USD)

# Per-asset daily cap check (self-enforced inside module)
if asset_daily_wager[asset] + position_usd > capital * CRYPTO_1D_PER_ASSET_CAP_PCT:
    position_usd = trim or skip
```

### Risk Filters

| Filter | 15m Version | 1d Version |
|--------|------------|-----------|
| R1: Extreme vol | 5m range vs 30d avg | ATR_pct > 4% of price (extreme) → skip |
| R2: Wide spread | >8c → skip | >12c → skip (daily markets have inherently wider spreads) |
| R3: Thin Kalshi book | <$100 depth | <$300 depth (larger position sizes require more depth) |
| R4: Thin OKX volume | <25% of 30d avg | Not applied (daily vol always sufficient by morning) |
| R5: Stale data | TFI/OBI stale | 24h candle >6h old → skip (unexpected for daily) |
| R6: Extreme funding | \|fr_z\| > 3.0 | \|funding_24h_z\| > 3.5 (wider tolerance; daily funding can spike) |
| R7: Low conviction | \|raw_score\| < 0.05 | \|raw_score\| < 0.10 (stricter given higher per-trade stake) |
| R8: Session drawdown | >5% capital loss today | >8% capital loss today from crypto_1d specifically |
| R9: Macro event | ±30 min of CPI/Fed/FOMC | Same; also check 5pm EST for any scheduled announcements |
| R10: Basis risk | Coinbase/OKX >0.15% | Same |
| R11: Settlement proximity | Inherent in no-entry-after-15:00 gate | Skip if CF Benchmarks RTI index shows abnormal spread vs spot |
| R12: OI staleness | n/a | If `oi_1d_snapshot.json` entry >26h old → OI signal = neutral; log warning |
| R13: Secondary exposure | n/a | If global_exposure_pct > 50% during secondary window → skip entirely |

---

## 6. Cross-Module Isolation

### ⚠️ BLOCKER 1 + CONCERN 4 RESOLVED — Full separation architecture

**Ticker-level isolation:**

`crypto_1d` operates exclusively on KXBTCD and KXETHD tickers. `crypto_only` operates on KXBTC and KXETH band tickers. These are **different Kalshi contract series** and will never collide at the ticker level under this architecture.

**Cross-module position guard:**

`load_traded_tickers()` is **module-scoped** — it returns tickers traded by the calling module within the current session. It does NOT provide global cross-module awareness.

**Fix required:** Before placing any `crypto_1d` order, the module must call a cross-module check:

```python
def _cross_module_guard(asset: str, kalshi_market_id: str) -> bool:
    """
    Returns True (safe to enter) if no other module holds an active position
    in any contract for this asset's daily series.
    
    Checks position_tracker for active positions tagged with:
    - asset matching (BTC or ETH)
    - settlement_date matching today
    - module != 'crypto_1d'
    
    If any such position exists → return False (do not enter).
    """
    active = position_tracker.get_active_positions(
        asset=asset,
        settlement_date=today_settlement_date()
    )
    for pos in active:
        if pos['module'] != 'crypto_1d':
            log(f"crypto_1d cross-module guard: {asset} blocked by {pos['module']} "
                f"position in {pos['market_id']}")
            return False
    return True
```

This guard runs **before** edge evaluation. If the hourly scanner has an active KXBTC or KXETH position for today's settlement, `crypto_1d` will not enter any above/below position on the same asset for the same day. Capital concentration risk trumps signal quality.

**Separation summary:**

| Module | Tickers | Guard |
|--------|---------|-------|
| `crypto_only` | KXBTC, KXETH (bands) | Existing `load_traded_tickers()` |
| `crypto_1d` | KXBTCD, KXETHD (above/below) | Ticker-level isolation + `_cross_module_guard()` |

---

## 7. Module Architecture and Integration

### File Structure

```
agents/ruppert/trader/
├── crypto_15m.py          ← existing; no changes needed
├── crypto_1d.py           ← NEW: main module file
└── crypto_client.py       ← shared; minor additions (daily candle helpers, funding_24h_cumulative)

agents/ruppert/data_analyst/
└── kalshi_client.py       ← shared; needs daily market discovery support

environments/demo/config.py ← add CRYPTO_1D_* constants (see §5)
environments/demo/logs/
├── decisions_1d.jsonl     ← separate decision log (mirrors decisions_15m.jsonl)
└── oi_1d_snapshot.json    ← OI baseline cache (see §2, Signal 4)
```

### Task Scheduler Configuration

```
Task: Ruppert-Crypto1D
Triggers:
  - Daily at 09:30 AM Eastern Time
  - Daily at 13:30 PM Eastern Time
Action: [path to python] [path to ruppert_cycle.py] --mode crypto_1d
Conditions: Run only if network is available
Settings: Do not run if task is already running
```

Note: Eastern Time handles EST/EDT automatically if configured via Windows time zone (not UTC offset). Confirm scheduler is set to ET zone, not UTC.

### How crypto_1d Fits in the Main Loop

**`ruppert_cycle.py` integration:**

```python
# Existing crypto_15m: driven by WebSocket ticker events
if is_15m_ticker(ticker):
    evaluate_crypto_15m_entry(...)

# New crypto_1d: driven by scheduled time-based evaluation
# Called by Ruppert-Crypto1D task at 09:30 ET (primary) and 13:30 ET (secondary)
if is_crypto_1d_entry_time():
    window = get_current_1d_window()  # 'primary' or 'secondary'
    if window == 'secondary':
        if get_total_active_wager_pct() >= CRYPTO_1D_SECONDARY_SKIP_EXPOSURE:
            log("crypto_1d secondary window skipped: global exposure too high")
            return
    for asset in ['BTC', 'ETH']:
        evaluate_crypto_1d_entry(asset, window=window)
```

**Design choice:** `crypto_1d` does NOT use WebSocket for entry decisions. REST calls at scan time. Daily signals don't benefit from sub-second update rates.

### Shared Infrastructure Reuse

| Component | Reuse? | Notes |
|-----------|--------|-------|
| OKX API client | ✅ Full reuse | Same `OKX_API` base URL; add `bar=1D` candle calls |
| Coinbase price | ✅ Full reuse | `fetch_coinbase_price()` from crypto_15m |
| Binance funding rate | ✅ Extended reuse | `_compute_funding_z_scores()` from crypto_client; add `funding_24h_cumulative` return value |
| Kalshi order placement | ✅ Full reuse | `KalshiClient.place_order()` unchanged |
| position_tracker | ✅ Full reuse | Add 1d positions with `module='crypto_1d'` tag; used by cross-module guard |
| capital.py / logger.py | ✅ Full reuse | Same cap tracking; separate daily wager pool via `module` tag |
| strategy gate | ✅ Partial reuse | Add `MIN_HOURS_ENTRY['crypto_1d'] = 2.0` |
| decisions log | 🔄 Parallel file | `decisions_1d.jsonl` (separate from `decisions_15m.jsonl`) |

### New Components Needed

1. **`fetch_daily_candle(symbol, lookback=30)`** — OKX daily OHLC candles; simple wrapper (~20 lines)
2. **`compute_atr(ohlc_data, period=14)`** — ATR computation; pure Python, no deps (~15 lines)
3. **`funding_24h_cumulative(symbol)`** — Extend `_compute_funding_z_scores()` to return sum of last 3 × 8h Binance rates (~10 lines delta)
4. **`cache_oi_snapshot(symbol)`** — Write/read `oi_1d_snapshot.json`; bootstrap on first run; staleness check at >26h (~20 lines)
5. **`discover_1d_markets(asset)`** — Kalshi market discovery for KXBTCD/KXETHD series (~30 lines)
6. **`select_best_strike(asset, P_above_fn, market_list)`** — Scan available strikes, compute edge for each, pick best (~40 lines)
7. **`evaluate_crypto_1d_entry(asset, window)`** — Main entry point with cross-module guard (~160 lines)
8. **`_cross_module_guard(asset, kalshi_market_id)`** — Cross-module position check via position_tracker (~25 lines)

**Total new code estimate:** ~320 lines. Simple compared to crypto_15m.py (no rolling windows, no EWM, no per-second OBI snapshots).

---

## 8. Asset Priority and Rollout

### Phase 1: BTC + ETH Only
- Most liquid Kalshi daily above/below markets
- Most established signal infrastructure (OKX, Coinbase, Binance)
- Target: 20 live trades before expanding

### Phase 2: Add SOL
- SOL has daily above/below markets but thinner liquidity
- Funding rates for SOL are more volatile — needs wider filters
- Include only after Phase 1 calibration data available

### Phase 3: XRP + DOGE (Optional)
- Very thin Kalshi liquidity; high spread risk
- Decision: defer indefinitely pending liquidity check

---

## 9. What We Deliberately Skip

**Band markets (v1 and beyond):** `crypto_1d` does not trade band markets. The hourly scanner owns that series. Clean separation is worth more than opportunistic band edge.

**On-chain data (v1):** Requires paid API keys. Deferred.

**Polymarket divergence (v1):** Deferred to Phase 2.

**Options market signals (IV, skew):** Deribit implied volatility deferred to Phase 3.

**OKX funding history endpoint:** Explicitly replaced by Binance Futures funding via existing infrastructure.

---

## 10. Risk Summary

| Risk | Severity | Mitigation |
|------|----------|------------|
| Thin liquidity → wide spread at fill | High | MIN_SPREAD filter, MAX_POSITION_USD=$200, prefer OTM strikes |
| Wrong direction → full loss | High | ATR confirmation, MIN_EDGE=0.08, per-asset daily cap 3% |
| Correlated losses (all assets move together) | Medium | DAILY_CAP_PCT=15%; BTC+ETH only in Phase 1 |
| Macro surprise between entry and 5pm | Medium | R9 macro filter; no entries after 15:00 ET |
| Settlement slippage (CF RTI vs spot) | Low | CF RTI is 60s average; negligible vs daily signal error |
| Module interference with crypto_only | **Eliminated** | KXBTCD/KXETHD only + `_cross_module_guard()` |
| Capital contention at secondary window | Medium | Skip secondary if global exposure > 50% |
| OI stale data bias | Low | >26h staleness → neutral; logged |
| First-run OI bootstrap | Low | Signal = 0.0/neutral; other 3 signals carry full weight |

---

## 11. Open Questions for David

1. **Asset scope:** Start with BTC + ETH only (safer, recommended), or include SOL from day one?

2. **Primary window timing:** 09:30–11:30 ET (current proposal). If David prefers a Europe-session entry (~06:00–08:00 ET), the overnight move is fresher but less corroborating equity context.

3. **Daily cap:** 15% of capital per day (`CRYPTO_1D_DAILY_CAP_PCT = 0.15`). At $5,000 capital = $750/day max across all crypto_1d trades. Increase to 20% if faster exposure buildup is desired.

4. **Secondary window:** Current design gates secondary on global exposure >50% and 1.5× edge. Alternatively, skip secondary entirely in v1 for simplicity. Recommend keeping it but deferring to David.

5. **DRY_RUN initial period:** Recommend 7-day dry run in DEMO before live capital deployment. The daily signal stack is untested — calibration data needed before committing capital.

---

## 12. Implementation Checklist (For Dev Spec)

**New files:**
- [ ] `crypto_1d.py` — main module (~320 lines)
- [ ] `environments/demo/logs/oi_1d_snapshot.json` — created on first run by `cache_oi_snapshot()`

**New functions (in `crypto_client.py` or `crypto_1d.py`):**
- [ ] `fetch_daily_candle(symbol, lookback=30)`
- [ ] `compute_atr(ohlc_data, period=14)`
- [ ] `funding_24h_cumulative(symbol)` — extend existing `_compute_funding_z_scores()` in `crypto_client.py`
- [ ] `cache_oi_snapshot(symbol)` — read/write `oi_1d_snapshot.json` with bootstrap + staleness logic
- [ ] `discover_1d_markets(asset)` — Kalshi KXBTCD/KXETHD discovery only
- [ ] `select_best_strike(asset, P_above_fn, market_list)`
- [ ] `evaluate_crypto_1d_entry(asset, window)` — includes cross-module guard
- [ ] `_cross_module_guard(asset, kalshi_market_id)` — blocks entry if other module has same-asset same-day position

**Config / strategy changes:**
- [ ] `config.py` — add all `CRYPTO_1D_*` constants (see §5); confirm `CRYPTO_1D_DAILY_CAP_PCT` naming
- [ ] `strategy.py` — add `MIN_HOURS_ENTRY['crypto_1d'] = 2.0`
- [ ] `ruppert_cycle.py` — scheduled 09:30 / 13:30 ET trigger with secondary exposure gate

**Infrastructure:**
- [ ] Windows Task Scheduler: create `Ruppert-Crypto1D` task (09:30 ET + 13:30 ET, ET timezone)
- [ ] Decision log: `decisions_1d.jsonl`
- [ ] Module tag: `'module': 'crypto_1d'` on all `log_trade()` calls

**Explicitly NOT needed:**
- ~~OKX funding rate history endpoint~~ (use Binance Futures via existing `_compute_funding_z_scores()`)
- ~~KXBTC / KXETH band market support~~ (crypto_only owns those)
- ~~Any new API clients~~ (Binance, OKX, Coinbase all existing)

---

## 13. Change Log (v1 → v2)

| Item | v1 | v2 |
|------|----|----|
| Market type | Above/below primary + bands opportunistic | **Above/below ONLY (KXBTCD/KXETHD)** |
| Funding source | OKX `/api/v5/public/funding-rate-history` | **Binance Futures via existing `_compute_funding_z_scores()`** |
| OI caching | "Simple JSON addition" (underspecified) | **Full spec: path, format, bootstrap, staleness (>26h → neutral)** |
| Task Scheduler | Mentioned but unspecified | **`Ruppert-Crypto1D` task, ET timezone, secondary gated by exposure** |
| Secondary window capital contention | Not addressed | **Skip secondary if `get_total_active_wager_pct() >= 0.50`** |
| Daily cap config name | `CRYPTO_1D_DAILY_WAGER_CAP_PCT` | **`CRYPTO_1D_DAILY_CAP_PCT`** |
| `MIN_HOURS_ENTRY` | Not in config | **`MIN_HOURS_ENTRY['crypto_1d'] = 2.0`** |
| `load_traded_tickers()` scope | Not addressed | **Module-scoped; added `_cross_module_guard()` for cross-module protection** |
| Asset scope | BTC, ETH, SOL, XRP, DOGE (phased) | **Phase 1: BTC + ETH only (KXBTCD/KXETHD); others deferred** |

---

*Generated by Ruppert Strategist subagent | 2026-03-30 | v2 — DS blockers resolved*
