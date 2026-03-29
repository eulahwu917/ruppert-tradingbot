# SPEC: crypto_intraday.py Sub-Module

**Author:** Architect  
**Date:** 2026-03-27  
**Status:** READY FOR DEV  

---

## Overview

New sub-module `crypto_intraday.py` to handle Kalshi crypto markets that settle within 2 hours (15-min and 1-hour windows). Completely separate from `run_crypto_scan()` in `main.py` which handles daily/weekly band markets.

**Key insight:** For 15-minute windows, the market price IS the best probability signal. Our log-normal model is calibrated for daily sigma; scaling it to 15-min windows introduces massive uncertainty. We should use Kalshi's implied probability + a momentum correction, NOT our own probability model.

---

## 1. Market Detection

### Function: `is_intraday_market(ticker: str, market_data: dict) -> bool`

A market is **intraday** if it settles in **< 2 hours** from now.

**Detection algorithm:**
```python
def is_intraday_market(ticker: str, market_data: dict) -> bool:
    """
    Return True if market settles in < 2 hours (intraday window).
    
    Uses close_time from market_data. Falls back to ticker parsing
    if close_time unavailable.
    """
    close_time = market_data.get('close_time', '')
    if not close_time:
        return False  # Can't determine settlement time
    
    try:
        close_dt = datetime.fromisoformat(close_time.replace('Z', '+00:00'))
        now = datetime.now(timezone.utc)
        hours_left = (close_dt - now).total_seconds() / 3600
        return 0 < hours_left < 2.0  # Settles in 0-2 hours
    except Exception:
        return False
```

**Ticker patterns for intraday markets:**
- `KXBTC-26MAR2817H1500` → BTC above/below at 3pm (1-hour window)
- `KXETH-26MAR2817-B1980` → ETH band at 5pm (may be 15-min or 1-hour)
- Parse settlement time from `close_time` field, NOT ticker string

---

## 2. Probability Model: MARKET-ANCHORED

### Decision: Use Market Price as Anchor

**Why NOT scale log-normal:**
- `sigma_15min = sigma_daily * sqrt(15/(24*60))` = 0.31% of price for BTC
- At $87,000 BTC, that's ±$270 expected movement
- But crypto can move 2-3% in 15 minutes during volatility spikes
- Our model underestimates tail risk on short windows

**Why USE market price:**
- Kalshi's market makers have real-time data, flow information, orderbook signals
- For 15-min windows, price discovery > model prediction
- The market IS the best 15-min probability estimate
- We add value via momentum correction, not probability replacement

### Function: `compute_intraday_edge(...)`

```python
def compute_intraday_edge(
    ticker: str,
    yes_ask: int,           # Kalshi YES ask in cents
    yes_bid: int,           # Kalshi YES bid in cents
    spot_price: float,      # Current BTC/ETH price
    series: str,            # 'KXBTC', 'KXETH', etc.
    strike: float,          # Strike price from market
    strike_type: str,       # 'greater', 'less', 'between'
    hours_left: float,      # Hours to settlement
    momentum_signal: dict,  # From crypto_client.get_btc_signal() etc.
) -> tuple[float, float, float]:
    """
    Compute edge for intraday crypto market.
    
    Returns:
        (edge, model_prob, confidence)
        
    Edge formula (market-anchored):
        market_prob = midpoint of bid/ask
        momentum_adj = ±3-5% based on 1h price change direction
        model_prob = market_prob + momentum_adj (clamped to [0.02, 0.98])
        edge = model_prob - market_prob  (will be small: ±3-5%)
        
    This is intentionally modest — we're not claiming to know better
    than the market on 15-min windows. We're just correcting for
    short-term momentum that may not be fully priced in.
    """
    # Market probability (use midpoint if bid exists)
    if yes_bid > 0:
        market_prob = ((yes_ask + yes_bid) / 2) / 100.0
    else:
        market_prob = yes_ask / 100.0
    
    # Momentum adjustment
    # 1h price change direction → ±3% base
    # Strong move (>1%) → ±5% adjustment
    change_1h = momentum_signal.get('change_1h', 0) or 0
    direction = momentum_signal.get('direction', 'NEUTRAL')
    
    # Determine if momentum favors YES or NO
    # For "greater" (above) markets: bullish = YES, bearish = NO
    # For "less" (below) markets: bearish = YES, bullish = NO
    # For "between" markets: momentum toward band center = YES
    
    momentum_adj = 0.0
    if strike_type == 'greater':  # YES if price > strike
        if direction == 'BULLISH':
            momentum_adj = 0.05 if abs(change_1h) > 1.0 else 0.03
        elif direction == 'BEARISH':
            momentum_adj = -0.05 if abs(change_1h) > 1.0 else -0.03
            
    elif strike_type in ('less', 'below'):  # YES if price < strike
        if direction == 'BEARISH':
            momentum_adj = 0.05 if abs(change_1h) > 1.0 else 0.03
        elif direction == 'BULLISH':
            momentum_adj = -0.05 if abs(change_1h) > 1.0 else -0.03
            
    elif strike_type == 'between':  # YES if price in band
        # Momentum toward band center helps
        band_center = strike  # Approximate
        dist_to_center = abs(spot_price - band_center) / spot_price
        if dist_to_center < 0.01:  # Already near center
            momentum_adj = 0.03  # Slight edge to YES
        elif dist_to_center > 0.02:  # Far from center
            momentum_adj = -0.03  # Slight edge to NO
    
    # Model probability (clamped)
    model_prob = max(0.02, min(0.98, market_prob + momentum_adj))
    
    # Edge (will be small for intraday)
    edge = model_prob - market_prob
    
    # Confidence: lower for intraday (we're less certain)
    # Base: 0.40 (vs 0.60 for daily)
    # Boost if strong momentum alignment
    confidence = 0.40
    if abs(momentum_adj) >= 0.05 and direction != 'NEUTRAL':
        confidence = 0.50
    
    return (round(edge, 4), round(model_prob, 4), round(confidence, 3))
```

### Justification

1. **Market-anchored approach respects price discovery**: Kalshi makers see flow we don't
2. **Momentum correction adds alpha**: Short-term moves often continue for 15-30 min
3. **Modest edge claims**: ±3-5% edge, not ±20%+ like daily markets
4. **Lower confidence**: Reflects genuine uncertainty on short windows
5. **Zero LLM cost**: Pure math + Kalshi API + Kraken price data

---

## 3. Entry Logic

### Entry Threshold: MIN_EDGE = 0.03 (3%)

**Why lower than daily (12%)?**
- Market price is more accurate for short windows
- We're only correcting for momentum, not replacing probabilities
- 3% edge × many trades = positive EV
- Higher frequency compensates for lower per-trade edge

### Position Sizing

```python
INTRADAY_MAX_POSITION = 25.0  # $25 max per intraday trade
INTRADAY_MIN_EDGE = 0.03      # 3% minimum edge
INTRADAY_MAX_DAILY = 100.0    # $100 max total intraday exposure per day
```

**Sizing formula:**
```python
def intraday_position_size(
    edge: float,
    capital: float,
    confidence: float,
    deployed_intraday: float,
) -> float:
    """
    Position size for intraday crypto trades.
    
    Smaller than daily due to:
    - Higher variance (shorter duration)
    - Lower confidence (market-anchored model)
    - Higher frequency (more trades)
    """
    # Kelly fraction: use LOWER tier (0.05 for conf 0.40-0.50)
    kf = 0.05 if confidence < 0.50 else 0.07
    
    # Simplified sizing: edge * capital * kf
    # For 3% edge, $10k capital, kf=0.05: $15
    raw_size = edge * capital * kf * 10  # 10x multiplier for small edges
    
    # Caps
    size = min(raw_size, INTRADAY_MAX_POSITION)  # $25 max
    size = min(size, INTRADAY_MAX_DAILY - deployed_intraday)  # Budget remaining
    
    return round(max(0, size), 2)
```

### Daily Cap Interaction

- **Intraday budget**: $100/day (separate from daily crypto cap of 7%)
- **Shares global crypto cap**: Total crypto (daily + intraday) ≤ $700/day
- **Implementation**: Track `deployed_intraday` separately in trade logs

---

## 4. Module Structure

### File: `crypto_intraday.py`

```python
"""
Intraday Crypto Trading Module — 15-min and 1-hour Kalshi Markets

Handles ONLY crypto markets settling in < 2 hours.
Uses market-anchored probability model with momentum correction.

Completely separate from run_crypto_scan() in main.py (daily/weekly).
"""

from datetime import datetime, timezone
from typing import Optional
import config
from crypto_client import get_btc_signal, get_eth_signal, ASSET_CONFIG
from kalshi_client import KalshiClient
from logger import log_trade, log_activity, get_daily_exposure
from bot.strategy import check_open_exposure

# ─────────────────────────────── Constants ────────────────────────────────────

INTRADAY_THRESHOLD_HOURS = 2.0    # Markets < 2h to settlement = intraday
INTRADAY_MIN_EDGE = 0.03          # 3% minimum edge (lower than daily 12%)
INTRADAY_MAX_POSITION = 25.0      # $25 max per trade
INTRADAY_MAX_DAILY = 100.0        # $100 max total intraday/day
INTRADAY_MIN_HOURS = 0.10         # 6 min minimum (don't enter at last second)


def is_intraday_market(ticker: str, market_data: dict) -> bool:
    """Return True if market settles in < 2 hours (intraday window)."""
    ...

def get_hours_to_settlement(market_data: dict) -> float:
    """Parse hours to settlement from market close_time."""
    ...

def compute_intraday_edge(
    ticker: str,
    yes_ask: int,
    yes_bid: int,
    spot_price: float,
    series: str,
    strike: float,
    strike_type: str,
    hours_left: float,
    momentum_signal: dict,
) -> tuple[float, float, float]:
    """
    Compute edge for intraday crypto market.
    Returns: (edge, model_prob, confidence)
    """
    ...

def intraday_position_size(
    edge: float,
    capital: float,
    confidence: float,
    deployed_intraday: float,
) -> float:
    """Position size for intraday crypto trades."""
    ...

def should_enter_intraday(
    edge: float,
    confidence: float,
    hours_left: float,
    capital: float,
    deployed_intraday: float,
    open_position_value: float,
) -> tuple[bool, str, float]:
    """
    Decide whether to enter intraday position.
    Returns: (should_enter, reason, size)
    """
    ...

def run_intraday_scan(
    traded_tickers: set,
    open_position_value: float = 0.0,
    dry_run: bool = True,
) -> list[dict]:
    """
    Scan for intraday crypto opportunities and execute.
    
    Called by:
    1. Main scan loop (if enabled)
    2. WebSocket tick handler in position_monitor.py
    
    Returns: list of executed trade dicts
    """
    ...

def evaluate_intraday_entry(
    ticker: str,
    yes_ask: int,
    yes_bid: int,
    market_data: dict,
    traded_tickers: set,
    deployed_intraday: float,
    dry_run: bool = True,
) -> Optional[dict]:
    """
    Evaluate single market for intraday entry (called by WebSocket handler).
    Returns: trade dict if executed, None otherwise
    """
    ...
```

---

## 5. Separation from Daily Crypto Scanner

### In `main.py` `run_crypto_scan()`:

**Add filter to EXCLUDE intraday markets:**
```python
# At top of run_crypto_scan(), after fetching markets:
from crypto_intraday import is_intraday_market

# Filter OUT intraday markets (handled by crypto_intraday.py)
markets = [m for m in markets if not is_intraday_market(m.get('ticker', ''), m)]
```

### In `crypto_intraday.py` `run_intraday_scan()`:

**Filter to INCLUDE only intraday markets:**
```python
# Only process markets settling in < 2 hours
markets = [m for m in all_markets if is_intraday_market(m.get('ticker', ''), m)]
```

### Trade Logging

Both modules log through `log_trade()` with distinct `module` field:
- Daily: `module='crypto'`
- Intraday: `module='crypto_intraday'`

This enables separate P&L tracking, Brier scoring, and optimizer analysis.

---

## 6. Data Flow

### Flow 1: Scheduled Scan (every 30 min via Task Scheduler)

```
main.py run_full_scan()
    ├── run_crypto_scan()           # Daily markets only (filter out <2h)
    └── run_intraday_scan()         # NEW: Intraday markets only (filter in <2h)
```

### Flow 2: WebSocket Real-Time Entry

```
position_monitor.py WebSocket loop
    │
    ├── Receive ticker update: {market_ticker, yes_ask, yes_bid, close_time}
    │
    ├── is_intraday_market(ticker, {close_time: ...})
    │   ├── True → evaluate_intraday_entry()
    │   │           ├── compute_intraday_edge()
    │   │           ├── should_enter_intraday()
    │   │           └── execute trade if approved
    │   │
    │   └── False → existing evaluate_crypto_entry() (daily logic)
```

### Data Required from WebSocket

The WebSocket ticker message includes:
- `market_ticker`: ticker string
- `yes_ask`, `yes_bid`: current prices
- `close_time`: settlement time (ISO string)

**No additional API call needed** — `close_time` is already in the tick message.

If `close_time` is missing from WebSocket:
```python
# Fallback: fetch market data once per ticker (cache for session)
market_data = client.get_market(ticker)
close_time = market_data.get('close_time')
```

---

## 7. Integration with position_monitor.py

### Current State

`evaluate_crypto_entry()` already exists but uses the daily log-normal model.

### Required Changes

```python
# In position_monitor.py WebSocket message handler:

async for msg in ws.messages():
    if msg.get('type') == 'ticker':
        ticker = msg.get('market_ticker', '')
        yes_ask = msg.get('yes_ask')
        yes_bid = msg.get('yes_bid')
        close_time = msg.get('close_time')
        
        if any(ticker.upper().startswith(p) for p in ('KXBTC', 'KXETH', 'KXXRP', 'KXDOGE')):
            # Determine if intraday or daily
            from crypto_intraday import is_intraday_market, evaluate_intraday_entry
            
            if is_intraday_market(ticker, {'close_time': close_time}):
                # Route to intraday module
                trade = evaluate_intraday_entry(
                    ticker, yes_ask, yes_bid,
                    {'close_time': close_time},
                    traded_tickers, deployed_intraday, DRY_RUN
                )
                if trade:
                    executed_trades.append(trade)
            else:
                # Existing daily logic
                evaluate_crypto_entry(ticker, yes_ask, yes_bid, close_time)
```

---

## 8. Cost Confirmation

**LLM calls: ZERO**

All logic is:
- Kraken API for spot prices (free, no key)
- Kalshi API for market prices (already authenticated)
- Pure math for edge calculation

No OpenAI/Anthropic/etc. API calls.

---

## 9. Configuration Additions

Add to `config.py`:

```python
# ─── Intraday Crypto Settings ─────────────────────────────────────────────────
INTRADAY_ENABLED = True           # Master toggle
INTRADAY_MIN_EDGE = 0.03          # 3% min edge (lower than daily 12%)
INTRADAY_MAX_POSITION = 25.0      # $25 max per trade
INTRADAY_MAX_DAILY = 100.0        # $100 max total intraday/day
INTRADAY_THRESHOLD_HOURS = 2.0    # Markets < 2h = intraday
```

---

## 10. Testing Checklist

- [ ] `is_intraday_market()` correctly identifies <2h markets
- [ ] `compute_intraday_edge()` returns modest edges (±3-5%)
- [ ] `run_intraday_scan()` only processes intraday markets
- [ ] `run_crypto_scan()` excludes intraday markets
- [ ] WebSocket handler routes correctly based on settlement time
- [ ] Trade logs show `module='crypto_intraday'`
- [ ] Intraday budget tracked separately from daily crypto budget
- [ ] No LLM calls in any code path

---

## Open Questions for CEO

### Q1: Should we enable intraday trading in DEMO immediately?

**Recommendation:** YES. It's low risk ($25 max per trade, $100/day budget) and gives us data to validate the momentum-correction model.

### Q2: What's the right MIN_EDGE threshold?

**Options:**
- 3% (aggressive): More trades, more data, possibly lower quality
- 5% (moderate): Fewer trades, higher confidence
- 8% (conservative): Very few trades, high bar

**Recommendation:** Start at 3% in DEMO to maximize data collection. Tighten after 2 weeks of data review.

### Q3: Should intraday share the 7% crypto daily cap or have its own?

**Current spec:** Separate $100/day budget, BUT shares global 70% exposure cap.

**Alternative:** Add intraday to the 7% crypto cap ($700 × 7% = $49, but that's very small for many trades).

**Recommendation:** Keep separate $100/day for now. Revisit after seeing trade frequency.

---

## Summary for Dev

| Component | Action |
|-----------|--------|
| `crypto_intraday.py` | NEW file — implement per spec |
| `main.py` | Add filter in `run_crypto_scan()` to exclude <2h markets |
| `position_monitor.py` | Route WebSocket ticks to intraday module if <2h settlement |
| `config.py` | Add INTRADAY_* constants |
| Trade logs | Use `module='crypto_intraday'` |

**Priority:** P2 (nice-to-have for data collection; not blocking anything)

**Estimated effort:** 3-4 hours implementation + 1 hour testing
