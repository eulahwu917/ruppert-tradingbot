# Dev Tasks — 2026-03-28b
_Issued by CEO. WS-first architecture. This is a significant refactor — take your time, QA each component separately._

---

## Overview

Replace all Kalshi market price REST polling with a shared WebSocket-first cache. Single persistent WS connection subscribed to ALL tickers, feeding a shared price cache that every module reads from. REST becomes fallback only.

**Three components to build:**
1. `market_cache.py` — shared price cache
2. `ws_feed.py` — persistent WS connection that populates the cache
3. Position tracker upgrade — WS-driven real-time exits (replaces 30-min polling)

Then wire all modules to use the cache.

---

## Component 1: `market_cache.py`

Shared in-memory price cache. All modules read from this instead of calling Kalshi REST for prices.

```python
# market_cache.py

import time, json, threading
from pathlib import Path

CACHE_FILE = Path('logs/price_cache.json')  # persistence across restarts
STALE_THRESHOLD = 60    # seconds — trigger REST fallback
PURGE_THRESHOLD = 300   # seconds — remove dead markets

_cache = {}         # {ticker: {bid, ask, updated_at, source}}
_lock = threading.Lock()

def update(ticker: str, bid: float, ask: float, source: str = 'ws'):
    """Called by WS feed on every ticker message."""
    with _lock:
        _cache[ticker] = {
            'bid': bid,
            'ask': ask,
            'updated_at': time.time(),
            'source': source,
        }

def get(ticker: str) -> dict | None:
    """Returns cache entry or None if not cached."""
    with _lock:
        return _cache.get(ticker)

def get_with_staleness(ticker: str) -> tuple[float | None, float | None, bool]:
    """Returns (bid, ask, is_stale). is_stale=True means use REST fallback."""
    entry = get(ticker)
    if not entry:
        return None, None, True
    age = time.time() - entry['updated_at']
    return entry['bid'], entry['ask'], age > STALE_THRESHOLD

def purge_stale():
    """Remove entries older than PURGE_THRESHOLD. Call periodically."""
    cutoff = time.time() - PURGE_THRESHOLD
    with _lock:
        dead = [t for t, e in _cache.items() if e['updated_at'] < cutoff]
        for t in dead:
            del _cache[t]

def persist():
    """Write cache to disk (call on graceful shutdown)."""
    with _lock:
        CACHE_FILE.parent.mkdir(exist_ok=True)
        CACHE_FILE.write_text(json.dumps(_cache))

def load():
    """Load cache from disk on startup (stale entries will fall back to REST naturally)."""
    if CACHE_FILE.exists():
        try:
            data = json.loads(CACHE_FILE.read_text())
            with _lock:
                _cache.update(data)
        except Exception:
            pass
```

---

## Component 2: `ws_feed.py`

Persistent WS connection. Subscribes to ALL ticker updates. Feeds `market_cache`. Also drives real-time exit checks.

```python
# ws_feed.py
# Run as: python ws_feed.py
# Or import and call run() from position_monitor --persistent
```

### Active series filter

Only cache tickers matching our active series. Everything else is discarded immediately.

```python
# Load from config — updateable without restart
ACTIVE_SERIES_PREFIXES = set([
    # Weather
    'KXHIGHT', 'KXHIGHNY', 'KXHIGHMI', 'KXHIGHCH',
    'KXHIGHDE', 'KXHIGHAT', 'KXHIGHLAX', 'KXHIGHAUS',
    'KXHIGHSE', 'KXHIGHSF', 'KXHIGHPH', 'KXHIGHLV',
    'KXHIGHSA', 'KXHIGHMIA',
    # Crypto hourly bands
    'KXBTC', 'KXETH', 'KXXRP', 'KXDOGE', 'KXSOL',
    # Crypto 15m direction
    'KXBTC15M', 'KXETH15M', 'KXXRP15M', 'KXDOGE15M',
    # Econ
    'KXCPI', 'KXPCE', 'KXJOBS', 'KXUNEMPLOYMENT', 'KXGDP',
    # Fed
    'KXFED', 'KXFOMC',
])

def is_relevant(ticker: str) -> bool:
    return any(ticker.upper().startswith(p) for p in ACTIVE_SERIES_PREFIXES)
```

Move `ACTIVE_SERIES_PREFIXES` to `config.py` as `WS_ACTIVE_SERIES` so it can be updated without touching code.

### WS connection loop

```python
async def run_ws_feed():
    """Main WS feed loop. Connects once, runs indefinitely."""
    market_cache.load()  # restore from disk on startup
    
    reconnect_delay = 1
    
    while True:
        try:
            headers = build_auth_headers()  # reuse existing auth from ws/connection.py
            
            async with websockets.connect(
                'wss://api.elections.kalshi.com/trade-api/ws/v2',
                additional_headers=headers,
                ping_interval=30,
                ping_timeout=10,
            ) as ws:
                reconnect_delay = 1  # reset on successful connect
                log_activity('[WS Feed] Connected')
                
                # Subscribe to ALL ticker updates (no market_tickers filter)
                await ws.send(json.dumps({
                    'id': 1,
                    'cmd': 'subscribe',
                    'params': {'channels': ['ticker']}
                }))
                
                last_purge = time.time()
                
                async for raw in ws:
                    msg = json.loads(raw)
                    await handle_message(msg)
                    
                    # Periodic purge every 5 min
                    if time.time() - last_purge > 300:
                        market_cache.purge_stale()
                        last_purge = time.time()
        
        except Exception as e:
            log_activity(f'[WS Feed] Disconnected: {e} — reconnecting in {reconnect_delay}s')
            # On disconnect: REST-poll tracked positions to catch missed moves
            await recovery_poll_positions()
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 60)  # exponential backoff, max 60s
        
        finally:
            market_cache.persist()
```

### Message handler

```python
async def handle_message(msg: dict):
    msg_type = msg.get('type')
    
    if msg_type != 'ticker':
        return  # ignore fills, subscribed confirmations, etc.
    
    data = msg.get('msg', {})
    ticker = data.get('market_ticker', '')
    
    if not ticker or not is_relevant(ticker):
        return  # discard irrelevant markets
    
    # Extract prices (WS sends dollar values)
    yes_bid = data.get('yes_bid')   # may be None if no bids
    yes_ask = data.get('yes_ask')   # may be None if no asks
    
    if yes_bid is not None and yes_ask is not None:
        market_cache.update(ticker, yes_bid / 100, yes_ask / 100)
    
    # Check exit triggers for tracked positions
    await position_tracker.check_exits(ticker, yes_bid, yes_ask)
    
    # Route crypto 15m tickers to evaluate entry
    if any(ticker.upper().startswith(s) for s in CRYPTO_15M_SERIES):
        close_time = data.get('close_time')
        open_time = data.get('open_time')
        if yes_ask and yes_bid:
            try:
                from crypto_15m import evaluate_crypto_15m_entry
                evaluate_crypto_15m_entry(ticker, yes_ask, yes_bid, close_time, open_time)
            except Exception as e:
                logger.warning('[WS Feed] 15m eval error: %s', e)
    
    # Route crypto hourly band tickers
    elif any(ticker.upper().startswith(p) for p in ('KXBTC', 'KXETH', 'KXXRP', 'KXDOGE')):
        if yes_ask and yes_bid:
            evaluate_crypto_entry(ticker, yes_ask, yes_bid, data.get('close_time'))
```

---

## Component 3: Position Tracker (Real-time exits)

Replace the 30-min polling loop with WS-driven exit checks. When a tracked position's bid hits the exit threshold, exit immediately.

### `position_tracker.py`

```python
# position_tracker.py

TRACKER_FILE = Path('logs/tracked_positions.json')

# In-memory tracked positions
# {ticker: {quantity, side, entry_price, exit_thresholds: [{price, action}]}}
_tracked = {}

def add_position(ticker: str, quantity: int, side: str, entry_price: float):
    """Call after every trade execution."""
    # Standard exit thresholds from config
    if side == 'yes':
        thresholds = [
            {'price': config.EXIT_GAIN_THRESHOLD,  'action': 'sell_all'},   # 0.95 (95c)
            {'price': config.EXIT_GAIN_PCT * entry_price, 'action': 'sell_all'},  # 70% gain
        ]
    else:  # no
        thresholds = [
            {'price': 1.0 - config.EXIT_GAIN_THRESHOLD, 'action': 'sell_all'},
        ]
    
    _tracked[ticker] = {
        'quantity': quantity,
        'side': side,
        'entry_price': entry_price,
        'exit_thresholds': thresholds,
    }
    _persist()

def remove_position(ticker: str):
    """Call after exit execution."""
    _tracked.pop(ticker, None)
    _persist()

async def check_exits(ticker: str, yes_bid: int | None, yes_ask: int | None):
    """Called by WS feed on every tick for tracked tickers."""
    pos = _tracked.get(ticker)
    if not pos or yes_bid is None:
        return
    
    current_bid = yes_bid / 100
    
    for threshold in pos['exit_thresholds']:
        if current_bid >= threshold['price']:
            log_activity(f'[WS Exit] {ticker} hit {threshold["price"]:.0%} — exiting')
            await execute_exit(ticker, pos, current_bid)
            return

async def execute_exit(ticker: str, pos: dict, current_price: float):
    """Execute the exit order via REST."""
    try:
        client = KalshiClient()
        # sell position at market
        if not DRY_RUN:
            client.sell_position(ticker, pos['quantity'])
        
        pnl = (current_price - pos['entry_price']) * pos['quantity']
        log_activity(f'[WS EXIT] {ticker} {pos["side"].upper()} @ {current_price:.0%} P&L=${pnl:+.2f}')
        remove_position(ticker)
    except Exception as e:
        logger.error(f'[WS Exit] Execute failed for {ticker}: {e}')

async def recovery_poll_positions():
    """Call on WS disconnect — REST poll all tracked positions to catch missed moves."""
    client = KalshiClient()
    for ticker in list(_tracked.keys()):
        try:
            market = client.get_market(ticker)
            yes_bid = market.get('yes_bid')
            if yes_bid:
                await check_exits(ticker, yes_bid, market.get('yes_ask'))
        except Exception:
            pass
```

### Wire to trade execution

In `main.py`, `crypto_client.py`, `economics_scanner.py` — anywhere a trade is executed, add:

```python
from position_tracker import add_position
add_position(ticker, contracts, side, entry_price_dollars)
```

---

## Module Integration

### How modules use the cache

Each module's existing market-price REST calls get replaced with a cache read + REST fallback:

```python
# Before (REST):
market = client.get_market(ticker)
yes_ask = market['yes_ask']

# After (cache-first):
import market_cache
bid, ask, is_stale = market_cache.get_with_staleness(ticker)
if is_stale:
    market = client.get_market(ticker)  # REST fallback
    ask = market.get('yes_ask_dollars', 0) * 100
    market_cache.update(ticker, market.get('yes_bid_dollars', 0), market.get('yes_ask_dollars', 0), source='rest')
else:
    ask = round(ask * 100)
```

Build a helper `get_market_price(ticker) -> (yes_bid_cents, yes_ask_cents)` that encapsulates the cache read + REST fallback. All modules call this helper, not the cache directly.

### Files to modify for integration

- `edge_detector.py` — weather market price reads
- `economics_scanner.py` — econ market price reads
- `fed_client.py` — fed market price reads
- `crypto_client.py` — crypto market price reads
- `position_monitor.py` — remove the old WS loop (replaced by `ws_feed.py`)
- `post_trade_monitor.py` — deprecate polling loop (replaced by position tracker)

Do NOT delete `post_trade_monitor.py` yet — keep as fallback. Add a comment: "Deprecated: WS position tracker handles exits in real-time. This runs as a safety net."

---

## `ws_feed.py` as the single entry point

`ws_feed.py` becomes the new `position_monitor.py --persistent`. It:
1. Loads price cache from disk
2. Connects WS, subscribes to all tickers
3. Routes messages: cache updates, exit checks, crypto entry evaluation
4. Runs until shutdown

Update Task Scheduler:
- Replace `Ruppert-WS-Persistent` action from `position_monitor.py --persistent` to `ws_feed.py`

---

## Config additions

Add to `config.py`:
```python
WS_ACTIVE_SERIES = [
    'KXHIGHT', 'KXHIGHNY', 'KXHIGHMI', 'KXHIGHCH', 'KXHIGHDE',
    'KXHIGHAT', 'KXHIGHLAX', 'KXHIGHAUS', 'KXHIGHSE', 'KXHIGHSF',
    'KXHIGHPH', 'KXHIGHLV', 'KXHIGHSA', 'KXHIGHMIA',
    'KXBTC', 'KXETH', 'KXXRP', 'KXDOGE', 'KXSOL',
    'KXBTC15M', 'KXETH15M', 'KXXRP15M', 'KXDOGE15M',
    'KXCPI', 'KXPCE', 'KXJOBS', 'KXUNEMPLOYMENT', 'KXGDP',
    'KXFED', 'KXFOMC',
]
WS_CACHE_STALE_SECONDS = 60
WS_CACHE_PURGE_SECONDS = 300
```

---

## QA Checklist

- [ ] `market_cache.py` — thread-safe reads/writes, persist/load cycle works
- [ ] `ws_feed.py` — connects, subscribes to all, receives messages, updates cache
- [ ] Filter: relevant tickers cached, irrelevant tickers discarded
- [ ] Cache staleness: stale entries trigger REST fallback correctly
- [ ] Position tracker: adds/removes positions, check_exits fires on threshold
- [ ] Exit execution: DRY_RUN respected, P&L logged, position removed
- [ ] Recovery poll: fires on WS disconnect, catches any missed exits
- [ ] Weather scan reads from cache (verify with log — should show `source=ws`)
- [ ] Crypto reads from cache
- [ ] `post_trade_monitor.py` kept as safety net, not deleted
- [ ] Task Scheduler updated to `ws_feed.py`
- [ ] Existing behavior unchanged in DEMO dry-run

---

## Build order

1. `market_cache.py` — standalone, no dependencies
2. `position_tracker.py` — depends on market_cache, config, kalshi_client
3. `ws_feed.py` — depends on both above + existing auth from ws/connection.py
4. Module integration (edge_detector, economics_scanner, etc.)
5. Task Scheduler update + smoke test

Do NOT try to build all at once. Build and QA each component before moving to the next.
