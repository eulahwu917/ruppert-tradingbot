# crypto_1d Module — Implementation Spec
**Date:** 2026-03-30  
**Author:** Trader (Ruppert)  
**Based on:** Strategist Architecture Proposal v2 (`agents/ruppert/strategist/proposals/crypto_1d_architecture_2026-03-30.md`)  
**Status:** READY FOR DEV  
**David approval note:** BTC, ETH, and SOL approved from day one. All three included in scope below (SOL deferred to Phase 2 in code-path, but config supports it).

---

## Overview

This spec describes all code changes required to implement the `crypto_1d` daily crypto trading module. The module trades Kalshi daily above/below markets (KXBTCD, KXETHD, KXSOLD) using 4 daily-scale signals, running as a separate module from `crypto_15m` and the hourly `crypto_only` band scanner.

**Assets in scope:** BTC, ETH (Phase 1, live at launch); SOL (Phase 2 — config wired, execution code-gated)  
**Markets in scope:** KXBTCD, KXETHD only (Phase 1); KXSOLD (Phase 2)  
**Markets explicitly excluded:** KXBTC, KXETH, KXSOL band series (owned by `crypto_only` scanner)

---

## File 1: `agents/ruppert/trader/crypto_1d.py` (NEW FILE)

**BEFORE:** File does not exist.

**AFTER:** New file implementing the full `crypto_1d` module. Full pseudocode and structure below.

### Module Structure

```python
"""
crypto_1d.py — Daily crypto above/below trading module.

Trades KXBTCD (BTC above/below) and KXETHD (ETH above/below) on Kalshi.
Uses 4 daily-scale signals: 24h momentum, funding rate regime, ATR band
selector, and OI regime (disk-persisted 24h snapshot).

Entry windows:
  Primary:   09:30–11:30 ET
  Secondary: 13:30–14:30 ET (gated by global exposure and 1.5× edge)
  No entry after 15:00 ET (2h before 17:00 settlement)

Run via: python ruppert_cycle.py crypto_1d
Triggered by: Ruppert-Crypto1D Windows Task Scheduler task
"""
```

### Constants (at module top)

```python
ASSETS_PHASE1 = ['BTC', 'ETH']   # Phase 1: live at launch (David approved)
ASSETS_PHASE2 = ['SOL']          # Phase 2: after 20-trade calibration
KALSHI_SERIES = {
    'BTC': 'KXBTCD',
    'ETH': 'KXETHD',
    'SOL': 'KXSOLD',   # Phase 2, wired but gated
}
OKX_SYMBOLS = {
    'BTC': 'BTC-USDT-SWAP',
    'ETH': 'ETH-USDT-SWAP',
    'SOL': 'SOL-USDT-SWAP',
}
BINANCE_SYMBOLS = {
    'BTC': 'BTCUSDT',
    'ETH': 'ETHUSDT',
    'SOL': 'SOLUSDT',
}
OI_SNAPSHOT_PATH = Path('environments/demo/logs/oi_1d_snapshot.json')
DECISION_LOG_PATH = Path('environments/demo/logs/decisions_1d.jsonl')

PRIMARY_WINDOW_START_ET   = '09:30'
PRIMARY_WINDOW_END_ET     = '11:30'
SECONDARY_WINDOW_START_ET = '13:30'
SECONDARY_WINDOW_END_ET   = '14:30'
NO_ENTRY_AFTER_ET         = '15:00'
```

---

### Function: `fetch_daily_candle(symbol: str, lookback: int = 30) -> list[dict]`

**Purpose:** Fetch daily OHLCV candles from OKX for momentum and ATR computation.

**Implementation details:**
- Use OKX REST endpoint: `GET /api/v5/market/candles?instId={symbol}&bar=1D&limit={lookback}`
- Returns list of dicts: `[{'ts': int, 'open': float, 'high': float, 'low': float, 'close': float, 'vol': float}, ...]`
- Sorted oldest-first for downstream computation
- Reuses existing OKX API client infrastructure (same base URL used in `crypto_client.py` / `crypto_15m.py`)
- Raises on HTTP error; caller logs and falls back

**Approximate size:** ~20 lines

---

### Function: `compute_atr(ohlc_data: list[dict], period: int = 14) -> float`

**Purpose:** Compute ATR-14 from daily OHLC data.

**Implementation details:**
- Standard True Range: `TR = max(high - low, |high - prev_close|, |low - prev_close|)`
- ATR = simple average of last `period` TR values
- Returns `ATR_pct = ATR / current_price` (normalized to price)
- ATR_pct_z = z-score of ATR_pct against 30-day rolling (used for sizing modifier)
- Pure Python, no new dependencies

**Approximate size:** ~20 lines

---

### Function: `compute_s1_momentum(candles: list[dict]) -> dict`

**Purpose:** Compute Signal 1 — 24h price momentum.

**Returns:**
```python
{
    'pct_24h': float,        # (current - prev_close) / prev_close
    'z_score': float,        # z-score vs 30-day rolling daily returns
    'regime': str,           # 'strong_up' | 'weak_up' | 'neutral' | 'weak_down' | 'strong_down' | 'extreme_up' | 'extreme_down'
    'raw_score': float,      # directional contribution: positive = bullish
}
```

**Logic:**
- `pct_24h = (candles[-1]['close'] - candles[-2]['close']) / candles[-2]['close']`
- Compute 30-day daily returns from candles; z-score pct_24h against that
- `z > 3.0` → `extreme_up` (mean-reversion signal — reduce directional confidence)
- `z > 1.5` → `strong_up`
- `z > 0.5` → `weak_up`
- `|z| <= 0.5` → `neutral`
- (symmetric for down)
- `raw_score` = z_score clamped to [-2, 2], then scaled to [-1, 1]
- Weight = 0.30

---

### Function: `compute_s2_funding(asset: str) -> dict`

**Purpose:** Compute Signal 2 — funding rate regime via Binance Futures.

**Returns:**
```python
{
    'funding_24h_cumulative': float,   # sum of last 3 × 8h funding rates
    'funding_24h_z': float,            # z-score vs 30-day rolling mean of daily cumulative rates
    'regime': str,                     # 'bull_overheat' | 'neutral' | 'bear_overheat'
    'raw_score': float,                # directional contribution (negative funding = bearish pressure)
    'filter_skip': bool,               # True if |funding_24h_z| > 3.5 (risk filter R6)
}
```

**Implementation:**
- Call existing `_compute_funding_z_scores()` in `crypto_client.py`
- **Extension required in `crypto_client.py`:** Add `funding_24h_cumulative` to return value by summing last 3 × 8h Binance Futures funding rates for the asset
- Compute z-score of the 24h cumulative against 30-day rolling baseline (fetch 30+ periods from Binance history)
- `|funding_24h_z| > 3.5` → `filter_skip = True` (risk filter R6; log and skip trade)
- Positive cumulative funding (longs paying) → mild bearish signal
- Weight = 0.25

**Dev note:** Do NOT add a new Binance API client. Extend `_compute_funding_z_scores()` to accept `return_cumulative=True` parameter or add a thin wrapper. Confirm exact signature with crypto_client.py before implementing.

---

### Function: `compute_s3_atr_band(asset: str, candles: list[dict], current_price: float) -> dict`

**Purpose:** Compute Signal 3 — ATR band selector and strike confidence.

**Returns:**
```python
{
    'ATR_14': float,
    'ATR_pct': float,         # ATR_14 / current_price
    'ATR_pct_z': float,       # z-score vs 30-day rolling ATR_pct
    'above_confidence': float, # 0.0–1.0: P(price above strike by settlement)
    'atr_size_mult': float,   # sizing multiplier: 0.5–1.2
    'high_vol_day': bool,     # ATR_pct > 3% (BTC) or 4% (ETH/SOL)
}
```

**Logic:**
- `ATR_pct_z > 1.0` → `atr_size_mult = clamp(1.0 - (ATR_pct_z - 1.0) * 0.15, 0.5, 1.2)`
- `ATR_pct_z <= 0` → scale up toward 1.2
- High-vol threshold: 3% for BTC, 4% for ETH, 5% for SOL
- Weight = 0.25

---

### Function: `cache_oi_snapshot(asset: str, current_oi: float) -> dict`

**Purpose:** Read/write `oi_1d_snapshot.json` for OI regime computation.

**Read behavior:**
- Load `OI_SNAPSHOT_PATH` if it exists
- If file missing or no entry for asset → return `{'oi': None, 'timestamp': None, 'bootstrap': True}`
- If `(now - snapshot.timestamp) > 26h` → return `{'oi': snapshot.oi, 'stale': True, 'timestamp': snapshot.timestamp}`

**Write behavior:**
- Called at end of `evaluate_crypto_1d_entry()`, AFTER entry decision
- Overwrites entry for the asset with current OI + current timestamp
- Creates file with proper JSON structure if it doesn't exist

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

**First-run bootstrap:** If `bootstrap=True`, proceed with `OI_delta_24h = 0.0`, `OI_regime = neutral`. Write snapshot at end of eval. Do NOT skip the trade solely due to missing OI history.

**Staleness:** If `stale=True`, set `OI_regime = neutral`, log warning, redistribute OI weight (0.20) proportionally to S1/S2/S3.

**Approximate size:** ~25 lines

---

### Function: `compute_s4_oi_regime(asset: str, current_oi: float) -> dict`

**Purpose:** Compute Signal 4 — OI regime from 24h snapshot delta.

**Returns:**
```python
{
    'OI_delta_24h': float,      # (current - snapshot) / snapshot; 0.0 on bootstrap
    'OI_regime': str,           # 'long_buildup' | 'short_buildup' | 'unwind' | 'neutral'
    'raw_score': float,         # directional contribution
    'weight_override': float,   # 0.0 if stale (weight redistributed to S1/S2/S3)
}
```

**Logic:**
- Fetch current OI from OKX `/api/v5/public/open-interest` (existing endpoint in `crypto_15m.py`)
- Call `cache_oi_snapshot(asset, current_oi)` to get baseline
- `OI_delta_24h = (current_oi - baseline_oi) / baseline_oi`
- Cross with S1 momentum direction:
  - Rising OI + rising price → `long_buildup` (bullish confirmation)
  - Rising OI + falling price → `short_buildup` (bearish confirmation)
  - Falling OI + either direction → `unwind` (signal dampening)
  - Otherwise → `neutral`
- `raw_score`: `long_buildup` = +0.5, `short_buildup` = -0.5, `unwind` = 0.0, `neutral` = 0.0 (scaled by OI delta magnitude)
- Weight = 0.20 (or 0.0 if stale, redistributed)

---

### Function: `compute_composite_score(s1, s2, s3, s4) -> dict`

**Purpose:** Combine 4 signals into a composite directional score.

**Returns:**
```python
{
    'raw_composite': float,      # weighted sum of raw_scores
    'P_above': float,            # sigmoid(raw_composite) → P(price above strike at settlement)
    'direction': str,            # 'above' | 'below' | 'no_trade'
    'confidence': float,         # 0.0–1.0 (derived from |raw_composite|)
    'skip_reason': str | None,   # reason if no_trade
}
```

**Weights:**
```python
w = {
    'S1': 0.30,
    'S2': 0.25,
    'S3': 0.25,
    'S4': 0.20,  # 0.0 if stale; redistribute proportionally to S1/S2/S3
}
```

**Logic:**
- If `s2['filter_skip']` → return `{direction: 'no_trade', skip_reason: 'extreme_funding'}`
- `raw_composite = sum(w[sig] * signals[sig]['raw_score'] for sig in signals)`
- `P_above = sigmoid(raw_composite * 3.0)` (scale factor 3.0 maps ±1 raw to ~95% / ~5%)
- `confidence = abs(raw_composite)` clamped to [0, 1]
- `direction = 'above'` if `P_above > 0.5 + MIN_EDGE/2`, `'below'` if `P_above < 0.5 - MIN_EDGE/2`, else `'no_trade'`

---

### Function: `discover_1d_markets(asset: str) -> list[dict]`

**Purpose:** Discover available KXBTCD / KXETHD / KXSOLD above/below markets on Kalshi.

**Implementation:**
- Use `KalshiClient.get_markets_metadata(series=KALSHI_SERIES[asset], status='open')`
- Filter to markets expiring today at 17:00 ET (CF Benchmarks settlement)
- Enrich with orderbook via `KalshiClient.enrich_orderbook(m)`
- Filter: `yes_ask >= 5` and `yes_ask <= 95`; spread ≤ 12c; book depth ≥ $300
- Return list sorted by absolute edge descending

**Approximate size:** ~35 lines

---

### Function: `select_best_strike(asset: str, P_above: float, markets: list[dict]) -> dict | None`

**Purpose:** Pick the best above/below strike given model P_above estimate.

**Logic:**
- For each market in `markets`:
  - Parse implied strike from ticker
  - If `P_above > 0.5`: we want to buy YES above a strike below current price
    - `model_yes_prob = P_above` for strikes near current price
    - Prefer strikes 1-2 steps OTM (better liquidity, still directional)
    - `edge = model_yes_prob - (yes_ask / 100)`
  - If `P_above < 0.5`: we want to buy YES below a strike above current price (or buy NO above)
    - `edge = (no_ask / 100) - (1 - P_above)` adjusted for direction
- Skip if `P_above < 0.15` or `P_above > 0.85` (too far from edge zone)
- Return market dict with highest edge that meets `CRYPTO_1D_MIN_EDGE`
- Return `None` if no qualifying strike found

**Approximate size:** ~45 lines

---

### Function: `_cross_module_guard(asset: str, settlement_date: str) -> bool`

**Purpose:** Block entry if any other module holds an active position in any contract for this asset's daily series.

**Returns:** `True` = safe to enter, `False` = blocked

**Implementation:**
```python
def _cross_module_guard(asset: str, settlement_date: str) -> bool:
    """
    Returns True (safe to enter) if no other module holds an active position
    in any contract for this asset's daily settlement.

    Checks position_tracker for active positions tagged with:
    - asset matching (BTC, ETH, or SOL)
    - settlement_date matching today's date
    - module != 'crypto_1d'

    If any such position exists → return False (do not enter).
    """
    from agents.ruppert.data_scientist.position_tracker import get_active_positions
    active = get_active_positions(asset=asset, settlement_date=settlement_date)
    for pos in active:
        if pos.get('module') != 'crypto_1d':
            log(f"crypto_1d cross-module guard: {asset} blocked by {pos['module']} "
                f"position in {pos.get('market_id', '?')}")
            return False
    return True
```

**Note for Dev:** `get_active_positions()` must support `asset=` and `settlement_date=` kwargs. If position_tracker does not currently support these filters, add them. This function must run **before** edge evaluation — not after.

**Approximate size:** ~25 lines

---

### Function: `compute_position_size(capital: float, P_win: float, cost_cents: int, ATR_pct_z: float) -> float`

**Purpose:** Compute Half-Kelly position size with ATR modifier.

```python
def compute_position_size(capital, P_win, cost_cents, ATR_pct_z):
    cost = cost_cents / 100
    kelly_full = (P_win - cost) / (cost * (1 - cost))
    kelly_half = kelly_full / 2

    # ATR modifier
    atr_mult = max(0.5, min(1.2, 1.0 - (ATR_pct_z - 1.0) * 0.15))

    position_usd = kelly_half * capital * atr_mult
    position_usd = min(position_usd, capital * config.CRYPTO_1D_WINDOW_CAP_PCT)
    position_usd = min(position_usd, config.CRYPTO_1D_MAX_POSITION_USD)
    position_usd = max(position_usd, 10.0)   # CRYPTO_1D_MIN_POSITION_USD
    return round(position_usd, 2)
```

---

### Function: `_log_decision(asset: str, window: str, signals: dict, decision: str, reason: str, market_id: str = None, size_usd: float = None)`

**Purpose:** Append a structured entry to `decisions_1d.jsonl`.

**Format** (mirrors decisions_15m.jsonl pattern):
```json
{
  "ts": "2026-03-30T09:31:45Z",
  "asset": "BTC",
  "window": "primary",
  "market_id": "KXBTCD-2603301700",
  "decision": "ENTER",
  "reason": "composite=0.62 P_above=0.73 edge=0.12 size=$45.00",
  "signals": {
    "S1": {"regime": "strong_up", "raw_score": 0.70},
    "S2": {"regime": "neutral", "raw_score": -0.12, "funding_24h_z": 0.8},
    "S3": {"ATR_pct": 0.021, "ATR_pct_z": -0.3, "atr_size_mult": 1.1},
    "S4": {"OI_regime": "long_buildup", "OI_delta_24h": 0.042, "raw_score": 0.50}
  },
  "composite": 0.62,
  "P_above": 0.73,
  "edge": 0.12,
  "size_usd": 45.00,
  "module": "crypto_1d"
}
```

---

### Function: `evaluate_crypto_1d_entry(asset: str, window: str = 'primary') -> dict`

**Purpose:** Main entry point — run all signals, apply risk filters, place order if qualified.

**Returns:** `{'entered': bool, 'ticker': str | None, 'size_usd': float, 'reason': str}`

**Full pseudocode:**

```python
def evaluate_crypto_1d_entry(asset: str, window: str = 'primary') -> dict:
    # 0. Validate asset
    if asset not in ASSETS_PHASE1:
        return skip('asset_not_in_phase1')

    # 1. Cross-module guard (runs before any signal computation)
    today_settlement = get_today_settlement_date()   # e.g. '2026-03-30'
    if not _cross_module_guard(asset, today_settlement):
        return skip('cross_module_guard')

    # 2. Capital / cap checks
    capital = get_capital()
    asset_daily_deployed = get_daily_exposure(module='crypto_1d', asset=asset)
    if asset_daily_deployed >= capital * config.CRYPTO_1D_PER_ASSET_CAP_PCT:
        return skip('per_asset_daily_cap')

    total_1d_deployed = get_daily_exposure(module='crypto_1d')
    if total_1d_deployed >= capital * config.CRYPTO_1D_DAILY_CAP_PCT:
        return skip('daily_cap_reached')

    # Secondary window: global exposure gate
    if window == 'secondary':
        global_exposure_pct = get_total_active_wager_pct()
        if global_exposure_pct >= config.CRYPTO_1D_SECONDARY_MAX_EXPOSURE_PCT:
            log(f"crypto_1d secondary skipped: global exposure {global_exposure_pct:.1%} >= 50%")
            return skip('secondary_global_exposure')

    # 3. Fetch market data
    candles = fetch_daily_candle(OKX_SYMBOLS[asset], lookback=30)
    if len(candles) < 15:
        return skip('insufficient_candle_data')
    current_price = candles[-1]['close']

    # 4. Compute signals
    s1 = compute_s1_momentum(candles)
    s2 = compute_s2_funding(asset)
    s3 = compute_s3_atr_band(asset, candles, current_price)
    current_oi = fetch_okx_oi(OKX_SYMBOLS[asset])
    s4 = compute_s4_oi_regime(asset, current_oi)

    # 5. Risk filters
    if s2['filter_skip']:
        _log_decision(asset, window, signals={}, decision='SKIP', reason='R6_extreme_funding')
        return skip('R6_extreme_funding')
    if s3['ATR_pct'] > 0.04:   # R1: extreme volatility
        _log_decision(asset, window, signals={}, decision='SKIP', reason='R1_extreme_vol')
        return skip('R1_extreme_vol')

    # 6. Composite score
    composite = compute_composite_score(s1, s2, s3, s4)
    if composite['direction'] == 'no_trade':
        _log_decision(asset, window, {s1, s2, s3, s4}, 'SKIP', composite['skip_reason'])
        return skip(composite['skip_reason'])

    # 7. MIN_EDGE check (stricter for secondary window)
    min_edge = config.CRYPTO_1D_MIN_EDGE
    if window == 'secondary':
        min_edge = config.CRYPTO_1D_MIN_EDGE * config.CRYPTO_1D_SECONDARY_EDGE_MULT  # = 0.12

    # 8. Discover markets and select strike
    markets = discover_1d_markets(asset)
    if not markets:
        return skip('no_markets_available')

    best = select_best_strike(asset, composite['P_above'], markets)
    if best is None or best['edge'] < min_edge:
        _log_decision(asset, window, {s1, s2, s3, s4}, 'SKIP', f'edge={best and best["edge"]:.3f} < min={min_edge}')
        return skip('insufficient_edge')

    # 9. Additional risk filters on selected market
    spread = best.get('yes_ask', 50) + best.get('no_ask', 50) - 100
    if spread > 12:   # R2: wide spread
        return skip('R2_wide_spread')
    if best.get('book_depth_usd', 0) < 300:   # R3: thin book
        return skip('R3_thin_book')

    # 10. Compute size
    side = 'yes' if composite['direction'] == 'above' else 'no'
    cost_cents = best.get('yes_ask') if side == 'yes' else best.get('no_ask')
    P_win = composite['P_above'] if side == 'yes' else (1 - composite['P_above'])
    size_usd = compute_position_size(capital, P_win, cost_cents, s3['ATR_pct_z'])

    # Per-asset cap trim
    remaining = capital * config.CRYPTO_1D_PER_ASSET_CAP_PCT - asset_daily_deployed
    size_usd = min(size_usd, remaining)
    if size_usd < 10.0:
        return skip('size_below_minimum')

    # 11. Place order
    contracts = max(1, int(size_usd / cost_cents * 100))
    actual_cost = round(contracts * cost_cents / 100, 2)
    market_id = best['ticker']

    trade_opp = {
        'ticker': market_id,
        'title': best.get('title', market_id),
        'side': side,
        'action': 'buy',
        'yes_price': best.get('yes_ask'),
        'market_prob': best.get('yes_ask', 50) / 100,
        'edge': best['edge'],
        'confidence': composite['confidence'],
        'size_dollars': actual_cost,
        'contracts': contracts,
        'source': 'crypto_1d',
        'module': 'crypto_1d',
        'asset': asset,
        'window': window,
        'scan_price': cost_cents,
        'fill_price': cost_cents,
        'note': f"crypto_1d {asset} {window} P_above={composite['P_above']:.2f} edge={best['edge']:.2f}",
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'date': str(date.today()),
    }
    trade_opp['strategy_size'] = actual_cost

    from agents.ruppert.trader.trader import Trader
    dry_run = config.DRY_RUN
    result = Trader(dry_run=dry_run).execute_opportunity(trade_opp)

    # 12. Post-trade: write OI snapshot
    cache_oi_snapshot(asset, current_oi)

    # 13. Log decision
    signals_dict = {'S1': s1, 'S2': s2, 'S3': s3, 'S4': s4}
    _log_decision(
        asset=asset, window=window, signals=signals_dict,
        decision='ENTER', market_id=market_id, size_usd=actual_cost,
        reason=f"composite={composite['raw_composite']:.2f} P_above={composite['P_above']:.2f} "
               f"edge={best['edge']:.2f} size=${actual_cost:.2f}"
    )

    if result:
        return {'entered': True, 'ticker': market_id, 'size_usd': actual_cost,
                'reason': 'trade_executed'}
    else:
        return {'entered': False, 'ticker': market_id, 'size_usd': 0,
                'reason': 'execute_failed'}
```

**Note on `get_active_positions()`:** Implementation may need to search today's trade log plus position_tracker state. Dev to confirm interface before coding.

---

## File 2: `environments/demo/config.py` — New Constants

**BEFORE:** File contains `CRYPTO_15M_*` constants and `MIN_HOURS_ENTRY` dict without `crypto_1d` entry.

**AFTER:** Add the following block immediately after the `CRYPTO_15M_*` constants block (after `CRYPTO_15M_FALLBACK_MIN_REMAINING` line):

```python
# ── Daily Crypto Above/Below (crypto_1d: KXBTCD / KXETHD / KXSOLD) ──────────
# Separate cap pool from crypto_15m. Trades daily above/below at 09:30 ET (primary)
# and 13:30 ET (secondary, gated by global exposure).
CRYPTO_1D_DAILY_CAP_PCT            = 0.15   # 15% of capital/day total across all crypto_1d
CRYPTO_1D_WINDOW_CAP_PCT           = 0.05   # 5% of capital per single entry
CRYPTO_1D_PER_ASSET_CAP_PCT        = 0.03   # 3% of capital per asset per day
CRYPTO_1D_MAX_POSITION_USD         = 200.0  # hard cap per entry (liquidity constraint)
CRYPTO_1D_MIN_EDGE                 = 0.08   # primary window minimum edge (8%)
CRYPTO_1D_SECONDARY_MIN_EDGE       = 0.12   # 1.5× minimum edge for secondary window entries
CRYPTO_1D_SECONDARY_MAX_EXPOSURE_PCT = 0.50 # skip secondary window if global exposure >= 50%
```

**ALSO:** Add `'crypto_1d': 2.0` to the `MIN_HOURS_ENTRY` dict:

**BEFORE:**
```python
MIN_HOURS_ENTRY = {
    'default':    0.5,
    'crypto_15m': 0.04,   # 2.4 min remaining — allows all primary + secondary window entries
}
```

**AFTER:**
```python
MIN_HOURS_ENTRY = {
    'default':    0.5,
    'crypto_15m': 0.04,   # 2.4 min remaining — allows all primary + secondary window entries
    'crypto_1d':  2.0,    # hard cutoff at 15:00 ET = 2h before 17:00 settlement
}
```

**Note on `CRYPTO_1D_SECONDARY_MIN_EDGE`:** This constant is the computed value (0.08 × 1.5 = 0.12). The multiplier 1.5 is implicit. If Dev prefers to compute it dynamically via `CRYPTO_1D_MIN_EDGE * 1.5` in the module code, the separate constant can be omitted — but defining it explicitly makes it tunable by Optimizer without code changes.

---

## File 3: `agents/ruppert/trader/main.py` — Add `run_crypto_1d_scan()`

**BEFORE:** File contains `run_crypto_scan()` function but no `run_crypto_1d_scan()`.

**AFTER:** Add the following function after `run_crypto_scan()` and before `run_fed_scan()`:

```python
# ─── CRYPTO 1D MODULE ─────────────────────────────────────────────────────────

def run_crypto_1d_scan(dry_run=True, traded_tickers=None, open_position_value=0.0):
    """
    Run the daily crypto above/below scan (crypto_1d module).
    Evaluates BTC and ETH (Phase 1) for KXBTCD / KXETHD above/below entries.
    Entry windows: 09:30–11:30 ET (primary), 13:30–14:30 ET (secondary).
    Returns list of executed trade dicts.
    """
    if traded_tickers is None:
        traded_tickers = set()

    log_activity("[Crypto1D] Starting daily above/below scan...")
    executed = []

    try:
        from agents.ruppert.trader.crypto_1d import evaluate_crypto_1d_entry, ASSETS_PHASE1
        from agents.ruppert.data_scientist.capital import get_capital as _get_cap
        from agents.ruppert.data_scientist.logger import get_daily_exposure as _get_daily_exp

        # Determine current window
        import pytz
        from datetime import datetime as _dt
        _now_et = _dt.now(pytz.timezone('America/New_York'))
        _time_str = _now_et.strftime('%H:%M')

        if _time_str >= '09:30' and _time_str <= '11:30':
            window = 'primary'
        elif _time_str >= '13:30' and _time_str <= '14:30':
            window = 'secondary'
        else:
            log_activity(f"[Crypto1D] Outside entry windows (current ET: {_time_str}) — skipping")
            return []

        # No-entry-after gate
        if _time_str >= '15:00':
            log_activity(f"[Crypto1D] No-entry gate: {_time_str} ET >= 15:00 — skipping")
            return []

        # Capital / daily cap check
        try:
            _capital = get_capital()
            _1d_deployed = _get_daily_exp(module='crypto_1d')
            _1d_cap = _capital * config.CRYPTO_1D_DAILY_CAP_PCT
        except Exception as _ce:
            log_activity(f"[Crypto1D] Capital check error: {_ce} — using fallback")
            _capital = getattr(config, 'CAPITAL_FALLBACK', 10000.0)
            _1d_deployed = 0.0
            _1d_cap = _capital * getattr(config, 'CRYPTO_1D_DAILY_CAP_PCT', 0.15)

        if _1d_deployed >= _1d_cap:
            log_activity(f"[Crypto1D] Daily cap reached (${_1d_deployed:.2f} / ${_1d_cap:.0f}) — skipping")
            return []

        # Evaluate each Phase 1 asset
        for asset in ASSETS_PHASE1:
            ticker_key = f'crypto_1d_{asset}'
            if ticker_key in traded_tickers:
                log_activity(f"[Crypto1D] {asset} already evaluated this cycle — skipping")
                continue

            result = evaluate_crypto_1d_entry(asset=asset, window=window)
            traded_tickers.add(ticker_key)

            if result.get('entered'):
                log_activity(
                    f"[Crypto1D] ENTERED {asset} {result.get('ticker')} "
                    f"${result.get('size_usd', 0):.2f} ({window} window)"
                )
                executed.append({
                    'asset': asset,
                    'ticker': result.get('ticker'),
                    'size_dollars': result.get('size_usd', 0),
                    'module': 'crypto_1d',
                    'window': window,
                })
            else:
                log_activity(f"[Crypto1D] SKIP {asset}: {result.get('reason', '?')}")

    except Exception as e:
        log_activity(f"[Crypto1D] ERROR: {e}")
        import traceback
        traceback.print_exc()

    log_activity(f"[Crypto1D] Scan complete — {len(executed)} trade(s) executed")
    return executed
```

**Implementation notes:**
- The `pytz` import is consistent with existing ET-aware time handling elsewhere in the system. If `pytz` is not available, use `zoneinfo` (`from zoneinfo import ZoneInfo; ZoneInfo('America/New_York')`).
- `ticker_key = f'crypto_1d_{asset}'` prevents the same asset from being re-evaluated multiple times if `run_crypto_1d_scan()` is called more than once per cycle. It does not conflict with actual Kalshi ticker keys (which would be `KXBTCD-YYMMDDHHMM`).
- Dev note: `traded_tickers` dedup uses `crypto_1d_BTC` / `crypto_1d_ETH` synthetic keys, not actual market IDs, because the market ID is only known after discover/select step inside `evaluate_crypto_1d_entry()`.

---

## File 4: `environments/demo/ruppert_cycle.py` — Add `crypto_1d` Mode

**BEFORE:** `run_cycle()` dispatch block contains: `check`, `econ_prescan`, `weather_only`, `crypto_only`, `report`, `full`, `smart`.

**AFTER:** Add a new mode handler function and dispatch entry.

### New function (add after `run_crypto_only_mode()`):

```python
def run_crypto_1d_mode(state):
    """
    crypto_1d mode: daily above/below scan for KXBTCD / KXETHD.
    Runs at 09:30 ET (primary window) and 13:30 ET (secondary window, gated by exposure).
    Returns {'crypto_1d_trades': int}.
    """
    print("\n[crypto_1d] Running daily crypto above/below scan...")
    _1d_count = 0
    try:
        from agents.ruppert.trader.main import run_crypto_1d_scan as _run_1d
        _1d_results = _run_1d(
            dry_run=state.dry_run,
            traded_tickers=state.traded_tickers,
            open_position_value=state.open_position_value,
        )
        _1d_count = len(_1d_results) if _1d_results else 0
        if _1d_count:
            print(f"  {_1d_count} crypto_1d trade(s) executed")
            for t in _1d_results:
                print(f"    {t.get('asset')} {t.get('ticker')} ${t.get('size_dollars', 0):.2f}")
        else:
            print("  No crypto_1d entries placed this window")
    except Exception as _e:
        print(f"  crypto_1d error: {_e}")
        import traceback; traceback.print_exc()

    print(f"\ncrypto_1d done — {_1d_count} trade(s). {ts()}")

    # Scan summary notification
    try:
        _tz_pdt = _get_local_tz()
        _time_str = datetime.now(_tz_pdt).strftime('%I:%M %p')
        import time as _time
        _tz_abbr = 'PDT' if _time.localtime().tm_isdst > 0 else 'PST'
        try:
            _capital  = get_capital()
            _deployed = get_daily_exposure()
            _bp       = get_buying_power()
            _cap_line = f'${_capital:.2f} | Deployed: ${_deployed:.2f} | BP: ${_bp:.2f}'
        except Exception:
            _cap_line = 'N/A'
        _scan_msg = (
            f'\U0001f4ca Ruppert Scan \u2014 {_time_str} {_tz_abbr}\n\n'
            f'\u20bf Crypto 1D (daily above/below)\n'
            f'{_1d_count} trade(s) placed\n\n'
            f'\U0001f4b0 Capital: {_cap_line}'
        )
        log_event('SCAN_COMPLETE', {
            'mode': 'crypto_1d',
            'crypto_1d_trades': _1d_count,
            'summary': _scan_msg,
        })
        if _1d_count > 0:
            send_telegram(_scan_msg)
            log_activity('[SCAN NOTIFY] crypto_1d summary sent via Telegram')
        push_alert('info', _scan_msg)
        print('  Scan summary sent via Telegram.')
    except Exception as _notify_ex:
        print(f'  Scan notify error (non-fatal): {_notify_ex}')

    return {'crypto_1d_trades': _1d_count}
```

### Dispatch addition in `run_cycle()`:

**BEFORE** (in the dispatch section):
```python
        elif mode == 'report':
            summary = run_report_mode(state)
        elif mode == 'full':
```

**AFTER:**
```python
        elif mode == 'report':
            summary = run_report_mode(state)
        elif mode == 'crypto_1d':
            summary = run_crypto_1d_mode(state)
        elif mode == 'full':
```

### Module docstring update:

**BEFORE** (top of `ruppert_cycle.py`):
```python
"""
Ruppert Autonomous Trading Cycle
Runs on schedule via Windows Task Scheduler.
Modes:
  full          — scan + positions + smart money + execute (7am, 3pm)
  check         — positions only (10pm)
  smart         — smart money refresh only (lightweight)
  econ_prescan  — position check + econ scan only, skip if no release today (5am)
  weather_only  — position check + weather scan only (7pm)
  crypto_only   — position check + crypto scan only (10am, 6pm)
  report        — 7am P&L summary + loss detection
"""
```

**AFTER:**
```python
"""
Ruppert Autonomous Trading Cycle
Runs on schedule via Windows Task Scheduler.
Modes:
  full          — scan + positions + smart money + execute (7am, 3pm)
  check         — positions only (10pm)
  smart         — smart money refresh only (lightweight)
  econ_prescan  — position check + econ scan only, skip if no release today (5am)
  weather_only  — position check + weather scan only (7pm)
  crypto_only   — position check + crypto scan only (10am, 6pm)
  crypto_1d     — daily crypto above/below scan only (09:30 ET, 13:30 ET)
  report        — 7am P&L summary + loss detection
"""
```

---

## File 5: Task Scheduler — `Ruppert-Crypto1D` Task

**BEFORE:** No `Ruppert-Crypto1D` task exists.

**AFTER:** Two triggers on the new task: 09:30 AM ET and 13:30 PM ET daily.

### Registration PowerShell Snippet

Run this once on David's machine as Administrator to register the task. Adjust paths as needed:

```powershell
# ─── Ruppert-Crypto1D Task Registration ───────────────────────────────────────
# Adjust these variables to match actual paths on David's machine

$PythonExe   = "C:\Users\David Wu\AppData\Local\Programs\Python\Python311\python.exe"
$CycleScript = "C:\Users\David Wu\.openclaw\workspace\environments\demo\ruppert_cycle.py"
$WorkDir     = "C:\Users\David Wu\.openclaw\workspace\environments\demo"
$TaskName    = "Ruppert-Crypto1D"
$TaskPath    = "\Ruppert\"

# Build action
$Action = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "$CycleScript crypto_1d" `
    -WorkingDirectory $WorkDir

# Build two triggers: 09:30 ET and 13:30 ET
# NOTE: Time zone must be set to Eastern Time (ET handles both EST and EDT automatically)
$Trigger1 = New-ScheduledTaskTrigger -Daily -At "09:30AM"
$Trigger2 = New-ScheduledTaskTrigger -Daily -At "01:30PM"

# Settings
$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -MultipleInstances IgnoreNew `
    -RunOnlyIfNetworkAvailable `
    -StartWhenAvailable

# Register
Register-ScheduledTask `
    -TaskName $TaskName `
    -TaskPath $TaskPath `
    -Action $Action `
    -Trigger $Trigger1, $Trigger2 `
    -Settings $Settings `
    -RunLevel Highest `
    -Force

Write-Host "Task '$TaskName' registered successfully."
Write-Host "IMPORTANT: Verify task trigger timezone is set to Eastern Time in Task Scheduler UI."
Write-Host "Open Task Scheduler > Ruppert > Ruppert-Crypto1D > Properties > Triggers > Edit each trigger."
Write-Host "Check 'Synchronize across time zones' if triggers show UTC."
```

### Critical: Eastern Time Zone Verification

PowerShell's `New-ScheduledTaskTrigger` creates triggers in the **local machine timezone**. If David's machine is set to Pacific Time (PDT), the times above MUST be adjusted:

| Target (ET) | Pacific Time (PDT, UTC-7) | UTC |
|-------------|--------------------------|-----|
| 09:30 ET    | 06:30 AM PDT             | 13:30 UTC |
| 13:30 ET    | 10:30 AM PDT             | 17:30 UTC |

**Recommended approach:** Since David's machine runs Pacific Time, register triggers at **06:30 AM** and **10:30 AM** (PDT). During winter (PST/EST), adjust to 06:30 AM / 10:30 AM PST → which maps to 09:30 ET / 13:30 ET correctly since both shift by 1 hour.

**Alternative:** Use UTC triggers and hard-code `13:30` and `17:30` UTC. Set `Synchronize across time zones` in the trigger. This handles DST automatically.

**Existing task for reference:** `Ruppert-CryptoOnly` fires at 10:00 AM PDT (13:00 ET). The secondary window trigger at 10:30 AM PDT (13:30 ET) fires 30 minutes later — `crypto_1d` checks global exposure and skips if already ≥50%.

---

## Supporting Changes Required in `crypto_client.py`

**BEFORE:** `_compute_funding_z_scores()` returns per-period z-scores only.

**AFTER:** Extend to optionally return `funding_24h_cumulative` (sum of last 3 × 8h Binance Futures funding rates).

**Minimal change:**

```python
def _compute_funding_z_scores(symbol: str, return_cumulative: bool = False) -> dict:
    """
    Existing: per-period z-scores.
    New (return_cumulative=True): also returns funding_24h_cumulative and funding_24h_z.
    """
    # ... existing implementation ...

    if return_cumulative:
        # Last 3 × 8h rates
        last_3_rates = [r['fundingRate'] for r in funding_history[-3:]]
        funding_24h_cumulative = sum(last_3_rates)
        # 30-day baseline: group history into daily triplets, compute mean
        daily_cumulative_rates = [
            sum(funding_history[i:i+3])
            for i in range(0, len(funding_history) - 2, 3)
        ]
        mean_30d = sum(daily_cumulative_rates) / len(daily_cumulative_rates) if daily_cumulative_rates else 0
        std_30d  = (sum((x - mean_30d)**2 for x in daily_cumulative_rates) / len(daily_cumulative_rates))**0.5 if len(daily_cumulative_rates) > 1 else 1e-8
        funding_24h_z = (funding_24h_cumulative - mean_30d) / std_30d if std_30d > 0 else 0.0

        existing_result['funding_24h_cumulative'] = funding_24h_cumulative
        existing_result['funding_24h_z'] = funding_24h_z

    return existing_result
```

**This is a backward-compatible additive change.** All existing callers pass `return_cumulative=False` (default) and are unaffected.

---

## New Files / Artifacts Created at Runtime

| File | Created by | Contents |
|------|-----------|---------|
| `environments/demo/logs/oi_1d_snapshot.json` | `cache_oi_snapshot()` on first run | OI baseline per asset with timestamp |
| `environments/demo/logs/decisions_1d.jsonl` | `_log_decision()` on every evaluation | Structured log of all entry evaluations |

Both files are write-created on first run. The `logs/` directory already exists.

---

## Implementation Checklist

### New Files
- [ ] `agents/ruppert/trader/crypto_1d.py` — core module (~330 lines)

### Modified Files
- [ ] `environments/demo/config.py` — add `CRYPTO_1D_*` constants block + `MIN_HOURS_ENTRY['crypto_1d'] = 2.0`
- [ ] `agents/ruppert/trader/main.py` — add `run_crypto_1d_scan()` after `run_crypto_scan()`
- [ ] `environments/demo/ruppert_cycle.py` — add `run_crypto_1d_mode()` function + dispatch entry + docstring update
- [ ] `agents/ruppert/trader/crypto_client.py` — extend `_compute_funding_z_scores()` with `return_cumulative` param

### Infrastructure
- [ ] Register `Ruppert-Crypto1D` Windows Task Scheduler task (06:30 AM PDT + 10:30 AM PDT triggers)
- [ ] Verify trigger timezone maps correctly to ET (09:30 + 13:30)

### Not Required
- ~~New Binance API client~~ — extend existing `_compute_funding_z_scores()`
- ~~New OKX API client~~ — reuse existing base URL and candle endpoint
- ~~KXBTC / KXETH band market support~~ — `crypto_only` owns those
- ~~OKX funding rate history endpoint~~ — replaced by Binance Futures via existing infrastructure

---

## Key Spec Decisions Summary

| Decision | Spec Choice | Rationale |
|----------|-------------|-----------|
| Assets at launch | BTC + ETH (Phase 1); SOL Phase 2 | David approved all 3; Phase 1 limits risk while calibrating signals |
| Signal S2 source | Binance Futures via `_compute_funding_z_scores()` extension | No new API client; backward-compatible additive change |
| OI first-run behavior | Bootstrap neutral (don't skip trade) | Signal = 0.0; other 3 signals carry full weight; safer than blocking first N trades |
| OI staleness threshold | >26h → neutral, log warning, redistribute weight | Prevents stale data from silently biasing direction |
| Cross-module guard | Pre-signal-computation check via `get_active_positions()` | Runs before any API calls; hard block, not just log |
| Secondary window gate | Hard skip (not size reduction) when global exposure ≥50% | Consistent with Strategist v2; avoids partial sizing confusion |
| `CRYPTO_1D_SECONDARY_MIN_EDGE` | 0.12 (explicit constant, not computed) | Tunable by Optimizer without code changes |
| Task Scheduler triggers | Pacific Time (PDT) adjustments for David's machine | His machine is PDT; triggers at 06:30 AM + 10:30 AM PDT = 09:30 + 13:30 ET |
| `funding_24h_cumulative` | Additive param to existing function (`return_cumulative=True`) | Zero breakage to existing callers |
| `traded_tickers` dedup key | `crypto_1d_BTC` / `crypto_1d_ETH` synthetic keys | Actual market ID is only known after `discover_1d_markets()`; prevents double-eval |
| Decision log | `decisions_1d.jsonl` (separate from `decisions_15m.jsonl`) | Clean separation; mirrors existing pattern |
| Position tagging | `'module': 'crypto_1d'` on all trade records | Required for per-module daily cap accounting and cross-module guard |

---

*Generated by Ruppert Trader subagent | 2026-03-30*
