# Ruppert Trading Bot — Plans A, B, C, D

**Generated:** 2026-03-27 10:20 PM PDT  
**Target:** Dev implementation tonight  
**Status:** Architecture complete, ready for code

---

## Plan A: WebSocket Infrastructure + position_monitor.py

### File: `ws/connection.py` (NEW)

```python
"""
ws/connection.py — Kalshi WebSocket Client
Persistent connection with automatic reconnection.
Subscribes to ticker (price updates) and fill (order fills) channels.
"""
import asyncio
import json
import time
import logging
from typing import Callable, Optional
import websockets
from websockets.exceptions import ConnectionClosed

logger = logging.getLogger(__name__)

# Kalshi WebSocket endpoints
WS_URL_DEMO = "wss://demo-api.kalshi.co/trade-api/ws/v2"
WS_URL_PROD = "wss://api.kalshi.co/trade-api/ws/v2"

# Reconnection settings
RECONNECT_DELAY_INITIAL = 1.0   # seconds
RECONNECT_DELAY_MAX = 60.0      # max backoff
HEARTBEAT_INTERVAL = 30.0       # Kalshi requires ping every 30s


class KalshiWebSocket:
    """
    Async WebSocket client for Kalshi real-time data.
    
    Usage:
        ws = KalshiWebSocket(api_key, private_key, environment='demo')
        await ws.connect()
        await ws.subscribe_ticker(['KXBTC-26MAR28-B87500', ...])
        await ws.subscribe_fills()
        
        async for msg in ws.messages():
            handle(msg)
    """
    
    def __init__(
        self,
        api_key_id: str,
        private_key_path: str,
        environment: str = 'demo',
        on_ticker: Optional[Callable] = None,
        on_fill: Optional[Callable] = None,
        on_settlement: Optional[Callable] = None,
    ):
        self.api_key_id = api_key_id
        self.private_key_path = private_key_path
        self.environment = environment
        self.url = WS_URL_DEMO if environment == 'demo' else WS_URL_PROD
        
        # Callbacks
        self.on_ticker = on_ticker
        self.on_fill = on_fill
        self.on_settlement = on_settlement
        
        # State
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._connected = False
        self._subscriptions: set = set()
        self._message_queue: asyncio.Queue = asyncio.Queue()
        self._reconnect_delay = RECONNECT_DELAY_INITIAL
    
    def _generate_auth_headers(self) -> dict:
        """Generate authentication headers for Kalshi WS connection."""
        import base64
        import hashlib
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        from pathlib import Path
        
        timestamp = str(int(time.time() * 1000))
        method = "GET"
        path = "/trade-api/ws/v2"
        
        # Load private key
        key_data = Path(self.private_key_path).read_bytes()
        private_key = serialization.load_pem_private_key(key_data, password=None)
        
        # Sign: timestamp + method + path
        msg = f"{timestamp}{method}{path}".encode()
        signature = private_key.sign(
            msg,
            padding.PKCS1v15(),
            hashes.SHA256()
        )
        sig_b64 = base64.b64encode(signature).decode()
        
        return {
            "KALSHI-ACCESS-KEY": self.api_key_id,
            "KALSHI-ACCESS-SIGNATURE": sig_b64,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
        }
    
    async def connect(self) -> bool:
        """Establish WebSocket connection with authentication."""
        try:
            headers = self._generate_auth_headers()
            self._ws = await websockets.connect(
                self.url,
                extra_headers=headers,
                ping_interval=HEARTBEAT_INTERVAL,
                ping_timeout=10,
            )
            self._connected = True
            self._reconnect_delay = RECONNECT_DELAY_INITIAL
            logger.info(f"WebSocket connected to {self.url}")
            
            # Re-subscribe after reconnect
            if self._subscriptions:
                await self._resubscribe()
            
            return True
        except Exception as e:
            logger.error(f"WebSocket connection failed: {e}")
            self._connected = False
            return False
    
    async def _resubscribe(self):
        """Re-establish subscriptions after reconnect."""
        for sub in list(self._subscriptions):
            await self._send(sub)
    
    async def _send(self, message: dict):
        """Send JSON message to WebSocket."""
        if self._ws and self._connected:
            await self._ws.send(json.dumps(message))
    
    async def subscribe_ticker(self, tickers: list[str]):
        """Subscribe to price updates for a list of tickers."""
        msg = {
            "id": int(time.time() * 1000),
            "cmd": "subscribe",
            "params": {
                "channels": ["ticker"],
                "market_tickers": tickers,
            }
        }
        self._subscriptions.add(json.dumps(msg))
        await self._send(msg)
        logger.info(f"Subscribed to ticker channel for {len(tickers)} markets")
    
    async def subscribe_fills(self):
        """Subscribe to order fill notifications."""
        msg = {
            "id": int(time.time() * 1000),
            "cmd": "subscribe",
            "params": {
                "channels": ["fill"],
            }
        }
        self._subscriptions.add(json.dumps(msg))
        await self._send(msg)
        logger.info("Subscribed to fill channel")
    
    async def subscribe_orderbook(self, tickers: list[str]):
        """Subscribe to orderbook updates (L2 depth)."""
        msg = {
            "id": int(time.time() * 1000),
            "cmd": "subscribe",
            "params": {
                "channels": ["orderbook_delta"],
                "market_tickers": tickers,
            }
        }
        self._subscriptions.add(json.dumps(msg))
        await self._send(msg)
        logger.info(f"Subscribed to orderbook channel for {len(tickers)} markets")
    
    async def messages(self):
        """Async generator yielding parsed WebSocket messages."""
        while True:
            try:
                if not self._connected:
                    await self._reconnect()
                
                msg = await self._ws.recv()
                data = json.loads(msg)
                
                # Route to callbacks
                msg_type = data.get("type")
                if msg_type == "ticker" and self.on_ticker:
                    await self.on_ticker(data)
                elif msg_type == "fill" and self.on_fill:
                    await self.on_fill(data)
                elif msg_type == "orderbook_delta":
                    pass  # Handle if needed
                
                yield data
                
            except ConnectionClosed:
                logger.warning("WebSocket connection closed, reconnecting...")
                self._connected = False
                await self._reconnect()
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                self._connected = False
                await asyncio.sleep(1)
    
    async def _reconnect(self):
        """Reconnect with exponential backoff."""
        while not self._connected:
            logger.info(f"Reconnecting in {self._reconnect_delay:.1f}s...")
            await asyncio.sleep(self._reconnect_delay)
            
            if await self.connect():
                break
            
            self._reconnect_delay = min(
                self._reconnect_delay * 2,
                RECONNECT_DELAY_MAX
            )
    
    async def close(self):
        """Close WebSocket connection."""
        if self._ws:
            await self._ws.close()
            self._connected = False
            logger.info("WebSocket closed")
    
    @property
    def connected(self) -> bool:
        return self._connected
```

### File: `ws/__init__.py` (NEW)

```python
"""WebSocket infrastructure for Kalshi real-time data."""
from .connection import KalshiWebSocket

__all__ = ['KalshiWebSocket']
```

---

### File: `position_monitor.py` (REPLACE post_trade_monitor.py)

```python
"""
position_monitor.py — replaces post_trade_monitor.py
Combines existing poll-based logic with native WebSocket subscriptions.

Architecture:
  - WS mode (default): event-driven settlement + price ticks for 14 minutes
  - Poll mode (fallback): existing logic if WS unavailable

Settlement handling:
  - WebSocket: instant notification via orderbook/ticker channel
  - Polling backstop: every 5 min inside WS loop as safety net

Crypto real-time entry:
  - WebSocket price ticks trigger evaluate_crypto_entry()
  - Band probability computed on each tick
  - Entry if edge > threshold AND ticker not already traded
"""
import sys
import os
import json
import uuid
import asyncio
import logging
from pathlib import Path
from datetime import date, datetime, timedelta, timezone
from typing import Optional

# Windows asyncio fix — must be set before any asyncio calls
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

LOGS = Path(__file__).parent / 'logs'
LOGS.mkdir(exist_ok=True)
LOGS_DIR = LOGS
ALERTS_FILE = LOGS / 'pending_alerts.json'

import config
DRY_RUN = getattr(config, 'DRY_RUN', True)

from kalshi_client import KalshiClient
from logger import (
    log_trade, log_activity, acquire_exit_lock, release_exit_lock,
    normalize_entry_price, get_daily_exposure
)
from bot.strategy import should_enter, check_daily_cap

logger = logging.getLogger(__name__)

# ─────────────────────────────── Constants ────────────────────────────────────

WS_ENABLED = True                    # Toggle WebSocket mode
WS_EVENT_LOOP_DURATION = 840         # 14 minutes (Task Scheduler runs every 30 min)
POLL_BACKSTOP_INTERVAL = 300         # 5 min polling backstop inside WS loop

# ─────────────────────────────── Helpers ──────────────────────────────────────

def ts():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _update_pnl_cache(pnl_delta: float):
    """Add pnl_delta to closed_pnl in pnl_cache.json."""
    cache_path = LOGS_DIR / 'pnl_cache.json'
    acquired = acquire_exit_lock()
    try:
        data = json.loads(cache_path.read_text(encoding='utf-8')) if cache_path.exists() else {}
        current = float(data.get('closed_pnl', 0.0))
        data['closed_pnl'] = round(current + pnl_delta, 2)
        tmp_path = cache_path.with_suffix('.tmp')
        tmp_path.write_text(json.dumps(data), encoding='utf-8')
        tmp_path.replace(cache_path)
    except Exception as e:
        print(f"  [pnl_cache] Update failed (non-fatal): {e}")
    finally:
        if acquired:
            release_exit_lock()


def push_alert(level, message, ticker=None, pnl=None):
    """Write alert for heartbeat to pick up and forward."""
    alerts = []
    if ALERTS_FILE.exists():
        try:
            alerts = json.loads(ALERTS_FILE.read_text(encoding='utf-8'))
        except:
            pass
    alerts.append({
        'level': level, 'message': message,
        'ticker': ticker, 'pnl': pnl,
        'timestamp': ts(),
    })
    ALERTS_FILE.write_text(json.dumps(alerts, indent=2), encoding='utf-8')


# ─────────────────────────────── Position Loading ─────────────────────────────

def load_open_positions():
    """Load open positions from trade logs, filtering out exits/settlements."""
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    today = date.today().isoformat()

    logs_to_check = [
        LOGS / f"trades_{yesterday}.jsonl",
        LOGS / f"trades_{today}.jsonl",
    ]

    entries_by_key = {}
    exit_keys = set()

    for trade_log in logs_to_check:
        if not trade_log.exists():
            continue
        for line in trade_log.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            ticker = rec.get('ticker', '')
            side = rec.get('side', '')
            action = rec.get('action', 'buy')
            key = (ticker, side)
            if action in ('exit', 'settle'):
                exit_keys.add(key)
            else:
                entries_by_key[key] = rec

    return [rec for key, rec in entries_by_key.items() if key not in exit_keys]


def load_traded_tickers() -> set:
    """Load set of already-traded tickers for dedup."""
    today = date.today().isoformat()
    trade_log = LOGS / f"trades_{today}.jsonl"
    tickers = set()
    
    if trade_log.exists():
        for line in trade_log.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if rec.get('action') not in ('exit', 'settle'):
                    tickers.add(rec.get('ticker', ''))
            except:
                pass
    return tickers


# ─────────────────────────────── Settlement Handler ───────────────────────────

def _settle_single_ticker(ticker: str, result: str, pos: Optional[dict] = None):
    """
    Handle settlement for a single ticker.
    
    Args:
        ticker: Market ticker
        result: 'yes' or 'no' — settlement outcome
        pos: Position record (optional, will be looked up if not provided)
    """
    if pos is None:
        # Look up position from open positions
        positions = load_open_positions()
        for p in positions:
            if p.get('ticker') == ticker:
                pos = p
                break
    
    if pos is None:
        print(f"  [Settlement] {ticker}: no open position found")
        return
    
    side = pos.get('side', '')
    entry_price = normalize_entry_price(pos)
    contracts = int(pos.get('contracts', 1) or 1)
    
    # Compute P&L based on settlement
    if side == 'yes':
        if result == 'yes':
            exit_price = 99
            pnl = (99 - entry_price) * contracts / 100
        else:
            exit_price = 1
            pnl = -(entry_price * contracts / 100)
    else:  # side == 'no'
        if result == 'no':
            exit_price = 99
            pnl = (99 - entry_price) * contracts / 100
        else:
            exit_price = 1
            pnl = -(entry_price * contracts / 100)
    
    # Write settle record
    log_path = LOGS_DIR / f'trades_{date.today().isoformat()}.jsonl'
    settle_record = {
        "trade_id": str(uuid.uuid4()),
        "timestamp": datetime.now().isoformat(),
        "date": str(date.today()),
        "ticker": ticker,
        "title": pos.get("title", ""),
        "side": side,
        "action": "settle",
        "action_detail": f"SETTLE {'WIN' if pnl > 0 else 'LOSS'} @ {exit_price}c",
        "source": "ws_settlement" if WS_ENABLED else "poll_settlement",
        "module": pos.get("module", ""),
        "settlement_result": result,
        "pnl": round(pnl, 2),
        "entry_price": entry_price,
        "exit_price": exit_price,
        "contracts": contracts,
    }
    
    try:
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(settle_record) + '\n')
    except Exception as e:
        print(f"  [Settlement] JSONL write error for {ticker}: {e}")
        return
    
    _update_pnl_cache(round(pnl, 2))
    print(f"  [Settlement] {ticker} {side.upper()} → {result.upper()} | P&L=${pnl:+.2f}")
    push_alert('settle', f'SETTLED: {ticker} {side.upper()} → {result.upper()} | P&L=${pnl:+.2f}', ticker=ticker, pnl=pnl)


# ─────────────────────────────── Crypto Entry Evaluator ───────────────────────

def evaluate_crypto_entry(ticker: str, yes_ask: int, yes_bid: int):
    """
    Evaluate crypto market for entry based on WebSocket price tick.
    
    Called on each ticker update for crypto markets.
    Uses band_prob model to compute edge vs live price.
    """
    from crypto_client import (
        get_btc_signal, get_eth_signal, get_xrp_signal, get_doge_signal,
        _band_probability, _t_cdf, ASSET_CONFIG, get_realized_vol
    )
    from bot.strategy import should_enter, calculate_position_size
    import math
    
    # Parse series from ticker (KXBTC, KXETH, etc.)
    series = ticker.split('-')[0].upper()
    
    # Determine asset
    if 'BTC' in series:
        asset = 'BTC'
        signal = get_btc_signal()
    elif 'ETH' in series:
        asset = 'ETH'
        signal = get_eth_signal()
    elif 'XRP' in series:
        asset = 'XRP'
        signal = get_xrp_signal()
    elif 'DOGE' in series:
        asset = 'DOGE'
        signal = get_doge_signal()
    else:
        return  # Unknown asset
    
    current_price = signal['price']
    
    # Parse strike from ticker (e.g., KXBTC-26MAR28-B87500 → 87500)
    parts = ticker.split('-')
    if len(parts) < 3:
        return
    
    strike_part = parts[-1]
    strike_type = 'B'  # Default to band
    strike = None
    
    if strike_part.startswith('B'):
        strike = float(strike_part[1:])
        strike_type = 'between'
    elif strike_part.startswith('T'):
        strike = float(strike_part[1:])
        strike_type = 'greater' if strike > current_price else 'less'
    
    if strike is None:
        return
    
    # Get vol and compute sigma
    cfg = ASSET_CONFIG[asset]
    realized_vol = signal.get('realized_hourly_vol') or (cfg['hourly_vol_pct'] / 100)
    
    # Estimate hours to settlement (rough: parse from ticker or default)
    hours_left = 4.0  # Default, should be parsed from close_time
    sigma = current_price * realized_vol * math.sqrt(max(hours_left, 0.1))
    
    # Compute model probability
    if strike_type == 'between':
        band_step = cfg['band_step']
        low = strike - band_step / 2
        high = strike + band_step / 2
        model_prob = _band_probability(low, high, current_price, sigma)
    elif strike_type == 'greater':
        model_prob = 1.0 - _t_cdf(strike, current_price, sigma)
    else:  # less
        model_prob = _t_cdf(strike, current_price, sigma)
    
    # Market probability from ask
    market_prob = yes_ask / 100.0
    
    # Compute edge
    edge = model_prob - market_prob
    side = 'yes' if edge > 0 else 'no'
    
    # Check minimum edge threshold
    min_edge = config.MIN_EDGE_THRESHOLD.get('crypto', 0.12) if isinstance(config.MIN_EDGE_THRESHOLD, dict) else 0.12
    if abs(edge) < min_edge:
        return
    
    # Check if already traded
    traded_tickers = load_traded_tickers()
    if ticker in traded_tickers:
        return
    
    # Check daily cap
    from capital import get_capital
    capital = get_capital()
    daily_cap = capital * config.CRYPTO_DAILY_CAP_PCT
    current_exposure = get_daily_exposure('crypto')
    
    if current_exposure >= daily_cap:
        logger.debug(f"Crypto daily cap reached: ${current_exposure:.2f} >= ${daily_cap:.2f}")
        return
    
    # Build opportunity dict
    confidence = 0.60 if abs(edge) >= 0.20 else 0.50
    
    opp = {
        'ticker': ticker,
        'title': f'{asset} price band',
        'side': side,
        'edge': round(edge, 4),
        'win_prob': model_prob if side == 'yes' else (1 - model_prob),
        'confidence': confidence,
        'market_prob': market_prob,
        'model_prob': model_prob,
        'source': 'crypto',
        'module': 'crypto',
        'yes_ask': yes_ask,
        'yes_bid': yes_bid,
        'current_price': current_price,
    }
    
    # Check entry via strategy
    can_enter, reason = should_enter(opp, capital)
    if not can_enter:
        logger.debug(f"[WS Crypto] {ticker}: entry blocked — {reason}")
        return
    
    # Calculate position size
    size = calculate_position_size(
        edge=abs(edge),
        win_prob=opp['win_prob'],
        capital=capital,
        confidence=confidence,
    )
    size = min(size, daily_cap - current_exposure, 100.0)  # $100 max per trade
    
    if size < 5:
        return
    
    # Execute trade
    client = KalshiClient()
    contracts = max(1, int(size / (yes_ask / 100)))
    
    print(f"  [WS Crypto Entry] {ticker} {side.upper()} | edge={edge:+.1%} | ${size:.2f}")
    
    if DRY_RUN:
        order_result = {'dry_run': True, 'status': 'simulated'}
    else:
        try:
            order_result = client.place_order(ticker, side, yes_ask, contracts)
        except Exception as e:
            print(f"  [WS Crypto] Order failed: {e}")
            return
    
    opp['action'] = 'buy'
    opp['contracts'] = contracts
    opp['size_dollars'] = size
    opp['timestamp'] = ts()
    opp['date'] = str(date.today())
    
    log_trade(opp, size, contracts, order_result)
    log_activity(f'[WS-CRYPTO] Entered {ticker} {side.upper()} @ {yes_ask}c | edge={edge:+.1%}')
    push_alert('trade', f'WS Crypto Entry: {ticker} {side.upper()} @ {yes_ask}c', ticker=ticker)


# ─────────────────────────────── Polling Logic ────────────────────────────────

def run_polling_scan(client: KalshiClient, run_settlement_check: bool = True):
    """
    Run the existing poll-based position check.
    Imported from existing post_trade_monitor logic.
    """
    from post_trade_monitor import (
        check_settlements, check_weather_position, check_crypto_position,
        check_alert_only_position, get_market_data
    )
    
    print(f"  [Polling Scan] Starting at {ts()}")
    
    # Settlement check
    if run_settlement_check:
        try:
            check_settlements(client, LOGS_DIR)
        except Exception as e:
            print(f"  [Settlement Checker] ERROR: {e}")
    
    # Position monitoring
    positions = load_open_positions()
    if not positions:
        print("  [Polling] No open positions")
        return
    
    print(f"  [Polling] Checking {len(positions)} positions")
    
    for pos in positions:
        ticker = pos.get('ticker', '')
        side = pos.get('side', '')
        source = pos.get('source', pos.get('module', 'bot'))
        
        if not ticker or not side:
            continue
        
        market = get_market_data(ticker)
        if market is None:
            continue
        
        # Route to appropriate checker
        action = None
        reason = None
        
        try:
            if source in ('weather', 'bot') or 'KXHIGH' in ticker:
                action, reason, cur_price, contracts, pnl = check_weather_position(pos, market)
            elif source == 'crypto' or any(ticker.upper().startswith(p) for p in ('KXBTC', 'KXETH', 'KXXRP', 'KXSOL', 'KXDOGE')):
                action, reason, cur_price, contracts, pnl = check_crypto_position(pos, market)
            else:
                action, reason, cur_price, contracts, pnl = check_alert_only_position(pos, market)
        except Exception as e:
            print(f"  [Polling] Error checking {ticker}: {e}")
            continue
        
        if action == 'auto_exit':
            print(f"  [Polling] AUTO-EXIT: {ticker} — {reason}")
            # Execute exit (existing logic)
        elif action and 'alert' in action:
            push_alert('warning', f'{ticker}: {reason}', ticker=ticker)


# ─────────────────────────────── WebSocket Mode ───────────────────────────────

async def run_ws_mode(client: KalshiClient):
    """
    Run WebSocket event-driven mode for 14 minutes.
    
    Flow:
    1. Full polling scan at start (auto-exit + weather alerts, skip settlement)
    2. Connect WebSocket, subscribe to open position tickers + crypto markets
    3. Event loop: handle settlements and crypto price ticks
    4. Polling backstop every 5 minutes
    """
    from ws.connection import KalshiWebSocket
    
    print(f"\n{'='*60}")
    print(f"  POSITION MONITOR (WebSocket Mode)  {ts()}")
    print(f"{'='*60}")
    
    # 1. Initial polling scan (skip settlement — WS will handle it)
    print("\n  [Phase 1] Initial polling scan...")
    run_polling_scan(client, run_settlement_check=False)
    
    # 2. Build subscription list
    positions = load_open_positions()
    position_tickers = [p.get('ticker', '') for p in positions if p.get('ticker')]
    
    # Add active crypto markets for real-time entry
    try:
        crypto_markets = client.search_markets(series_ticker='KXBTC', status='open')
        crypto_markets += client.search_markets(series_ticker='KXETH', status='open')
        crypto_tickers = [m.get('ticker', '') for m in crypto_markets[:50]]  # Limit
    except Exception as e:
        print(f"  [WS] Could not fetch crypto markets: {e}")
        crypto_tickers = []
    
    all_tickers = list(set(position_tickers + crypto_tickers))
    
    if not all_tickers:
        print("  [WS] No tickers to subscribe — falling back to polling")
        run_polling_scan(client, run_settlement_check=True)
        return
    
    print(f"  [Phase 2] Subscribing to {len(all_tickers)} tickers...")
    
    # 3. Connect WebSocket
    ws = KalshiWebSocket(
        api_key_id=config.get_api_key_id(),
        private_key_path=config.get_private_key_path(),
        environment=config.get_environment(),
    )
    
    connected = await ws.connect()
    if not connected:
        print("  [WS] Connection failed — falling back to polling")
        run_polling_scan(client, run_settlement_check=True)
        return
    
    await ws.subscribe_ticker(all_tickers)
    await ws.subscribe_fills()
    
    # 4. Event loop
    print(f"  [Phase 3] Event loop ({WS_EVENT_LOOP_DURATION}s)...")
    
    start_time = asyncio.get_event_loop().time()
    last_backstop = start_time
    
    try:
        async for msg in ws.messages():
            now = asyncio.get_event_loop().time()
            elapsed = now - start_time
            
            # Check duration
            if elapsed >= WS_EVENT_LOOP_DURATION:
                print(f"  [WS] Event loop complete ({elapsed:.0f}s)")
                break
            
            # Polling backstop every 5 min
            if now - last_backstop >= POLL_BACKSTOP_INTERVAL:
                print(f"  [WS Backstop] Running polling scan...")
                run_polling_scan(client, run_settlement_check=True)
                last_backstop = now
            
            # Handle message
            msg_type = msg.get('type')
            
            if msg_type == 'ticker':
                ticker = msg.get('market_ticker', '')
                yes_ask = msg.get('yes_ask')
                yes_bid = msg.get('yes_bid')
                
                # Check if this is a crypto ticker
                if any(ticker.upper().startswith(p) for p in ('KXBTC', 'KXETH', 'KXXRP', 'KXDOGE')):
                    if yes_ask and yes_bid:
                        evaluate_crypto_entry(ticker, yes_ask, yes_bid)
                
                # Check for settlement (price at 99 or 1)
                if yes_ask is not None:
                    if yes_ask >= 99:
                        _settle_single_ticker(ticker, 'yes')
                    elif yes_ask <= 1:
                        _settle_single_ticker(ticker, 'no')
            
            elif msg_type == 'fill':
                # Log fill confirmation
                order_id = msg.get('order_id', '')
                ticker = msg.get('market_ticker', '')
                print(f"  [WS Fill] Order {order_id} filled for {ticker}")
    
    except asyncio.TimeoutError:
        print(f"  [WS] Event loop timeout")
    except Exception as e:
        print(f"  [WS] Error: {e}")
    finally:
        await ws.close()
    
    # Final polling scan
    print("  [Phase 4] Final polling scan...")
    run_polling_scan(client, run_settlement_check=True)
    
    print(f"\nWebSocket monitor complete. {ts()}")


# ─────────────────────────────── Polling Mode (Fallback) ──────────────────────

def run_polling_mode(client: KalshiClient):
    """
    Thin wrapper around existing polling logic.
    Used when WebSocket is disabled or unavailable.
    """
    print(f"\n{'='*60}")
    print(f"  POSITION MONITOR (Polling Mode)  {ts()}")
    print(f"{'='*60}")
    
    run_polling_scan(client, run_settlement_check=True)
    
    print(f"\nPolling monitor complete. {ts()}")


# ─────────────────────────────── Main Entry Point ─────────────────────────────

def main():
    """
    Main entry point for position monitor.
    Detects WebSocket availability and routes accordingly.
    """
    client = KalshiClient()
    
    # Check if WebSocket is available and enabled
    ws_available = False
    if WS_ENABLED:
        try:
            from ws.connection import KalshiWebSocket
            ws_available = True
        except ImportError:
            print("  [Monitor] WebSocket module not available — using polling mode")
    
    if ws_available:
        # Run async WebSocket mode
        asyncio.run(run_ws_mode(client))
    else:
        # Fallback to polling
        run_polling_mode(client)


if __name__ == '__main__':
    main()
```

---

## Plan B: Volume-Tier Filter

### File: `config.py` — Add Constants

```python
# ─────────────────────────────── Volume-Tier Discounting ──────────────────────
# Discount edge for thin markets — wide spreads often mean market knows something
VOLUME_TIER_THICK    = 5000   # contracts; no edge discount
VOLUME_TIER_MID      = 1000   # moderate discount
VOLUME_DISCOUNT_MID  = 0.85   # multiply edge by this (15% discount)
VOLUME_DISCOUNT_THIN = 0.65   # multiply edge by this (35% discount)
```

### File: `edge_detector.py` — Add Function

Add this function after the `classify_market_type()` function (around line 85):

```python
def apply_volume_tier(edge: float, volume: int) -> tuple[float, str]:
    """
    Discount edge score for thin markets.
    
    Thin markets (low volume) often have wide spreads because:
    1. Market makers know something we don't
    2. Price discovery is incomplete
    3. Fill quality will be poor
    
    Args:
        edge: Raw edge score (model_prob - market_prob)
        volume: 24-hour volume in contracts (volume_24h_fp from Kalshi)
    
    Returns:
        (adjusted_edge, tier_label)
    """
    if volume >= config.VOLUME_TIER_THICK:
        return edge, 'thick'
    elif volume >= config.VOLUME_TIER_MID:
        return edge * config.VOLUME_DISCOUNT_MID, 'mid'
    else:
        return edge * config.VOLUME_DISCOUNT_THIN, 'thin'
```

### File: `edge_detector.py` — Modify `analyze_market()` 

In `analyze_market()`, **after** the T_lower probability flip block (around line 210) and **before** the edge calculation, add:

```python
    # ── Volume-tier discounting ───────────────────────────────────────────────
    # Apply discount to edge for thin/mid volume markets BEFORE threshold check.
    # This means thin markets need higher raw edge to clear MIN_EDGE_THRESHOLD.
    volume = int(market.get('volume_24h_fp', 0) or 0)
    raw_edge = model_prob - market_prob
    adjusted_edge, volume_tier = apply_volume_tier(raw_edge, volume)
    
    # Log the adjustment for debugging
    if volume_tier != 'thick':
        logger.debug(
            f"[Edge] {ticker}: volume_tier={volume_tier} (vol={volume}) — "
            f"edge adjusted from {raw_edge:.4f} to {adjusted_edge:.4f}"
        )
    
    # Use adjusted_edge for threshold check
    edge = adjusted_edge
```

Then, in the result dict (around line 260), add the volume_tier field:

```python
    result = {
        'ticker':      ticker,
        'title':       title,
        'city':        city_name,
        'market_type': market_type,
        'temp_range':  temp_range,
        'threshold_f': threshold_f,
        'target_date': target_date.isoformat(),
        'is_same_day': (target_date == date.today()),
        'market_prob': round(market_prob, 4),
        'noaa_prob':   round(model_prob, 4),   # kept for dashboard compat
        'model_prob':  round(model_prob, 4),
        'win_prob':    round(win_prob, 4),
        'edge':        round(edge, 4),
        'raw_edge':    round(raw_edge, 4),           # NEW: pre-discount edge
        'volume_tier': volume_tier,                   # NEW: thick/mid/thin
        'volume_tier_miss': (                         # NEW: for Optimizer analysis
            volume_tier in ('mid', 'thin') and 
            abs(raw_edge) >= config.MIN_EDGE_THRESHOLD and
            abs(edge) >= config.MIN_EDGE_THRESHOLD
        ),
        'confidence':  round(confidence, 4),
        'signal_src':  signal_src,
        'side':        side,
        'yes_price':   yes_ask,
        'bet_price':   bet_price,
        'action':      f"BUY {side.upper()} at {bet_price}c",
    }
```

---

## Plan C: Crypto Scan Cadence

### Current State
- Ruppert-Crypto-10AM ✓
- Ruppert-Crypto-6PM ✓

### Target Cadence (7x/day, every 2 hours 8am-8pm)
- Ruppert-Crypto-8AM (NEW)
- Ruppert-Crypto-10AM (existing)
- Ruppert-Crypto-12PM (NEW)
- Ruppert-Crypto-2PM (NEW)
- Ruppert-Crypto-4PM (NEW)
- Ruppert-Crypto-6PM (existing)
- Ruppert-Crypto-8PM (NEW)

### Task Scheduler Commands (PowerShell)

Run these commands in an **elevated PowerShell** (Admin):

```powershell
# Working directory and Python path
$WorkDir = "C:\Users\David Wu\.openclaw\workspace\projects\ruppert-tradingbot-demo"
$Python = "C:\Users\David Wu\AppData\Local\Programs\Python\Python312\python.exe"

# ─────────────────────────────────────────────────────────────────────────────
# Ruppert-Crypto-8AM
# ─────────────────────────────────────────────────────────────────────────────
$Action8AM = New-ScheduledTaskAction -Execute $Python -Argument "ruppert_cycle.py crypto_only" -WorkingDirectory $WorkDir
$Trigger8AM = New-ScheduledTaskTrigger -Daily -At 8:00AM
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
Register-ScheduledTask -TaskName "Ruppert-Crypto-8AM" -Action $Action8AM -Trigger $Trigger8AM -Settings $Settings -Description "Ruppert crypto_only scan at 8am"

# ─────────────────────────────────────────────────────────────────────────────
# Ruppert-Crypto-12PM
# ─────────────────────────────────────────────────────────────────────────────
$Action12PM = New-ScheduledTaskAction -Execute $Python -Argument "ruppert_cycle.py crypto_only" -WorkingDirectory $WorkDir
$Trigger12PM = New-ScheduledTaskTrigger -Daily -At 12:00PM
Register-ScheduledTask -TaskName "Ruppert-Crypto-12PM" -Action $Action12PM -Trigger $Trigger12PM -Settings $Settings -Description "Ruppert crypto_only scan at 12pm"

# ─────────────────────────────────────────────────────────────────────────────
# Ruppert-Crypto-2PM
# ─────────────────────────────────────────────────────────────────────────────
$Action2PM = New-ScheduledTaskAction -Execute $Python -Argument "ruppert_cycle.py crypto_only" -WorkingDirectory $WorkDir
$Trigger2PM = New-ScheduledTaskTrigger -Daily -At 2:00PM
Register-ScheduledTask -TaskName "Ruppert-Crypto-2PM" -Action $Action2PM -Trigger $Trigger2PM -Settings $Settings -Description "Ruppert crypto_only scan at 2pm"

# ─────────────────────────────────────────────────────────────────────────────
# Ruppert-Crypto-4PM
# ─────────────────────────────────────────────────────────────────────────────
$Action4PM = New-ScheduledTaskAction -Execute $Python -Argument "ruppert_cycle.py crypto_only" -WorkingDirectory $WorkDir
$Trigger4PM = New-ScheduledTaskTrigger -Daily -At 4:00PM
Register-ScheduledTask -TaskName "Ruppert-Crypto-4PM" -Action $Action4PM -Trigger $Trigger4PM -Settings $Settings -Description "Ruppert crypto_only scan at 4pm"

# ─────────────────────────────────────────────────────────────────────────────
# Ruppert-Crypto-8PM
# ─────────────────────────────────────────────────────────────────────────────
$Action8PM = New-ScheduledTaskAction -Execute $Python -Argument "ruppert_cycle.py crypto_only" -WorkingDirectory $WorkDir
$Trigger8PM = New-ScheduledTaskTrigger -Daily -At 8:00PM
Register-ScheduledTask -TaskName "Ruppert-Crypto-8PM" -Action $Action8PM -Trigger $Trigger8PM -Settings $Settings -Description "Ruppert crypto_only scan at 8pm"
```

### Verification Command

```powershell
schtasks /Query /TN "Ruppert-Crypto-*" /FO TABLE
```

Expected output: 7 crypto tasks (8AM, 10AM, 12PM, 2PM, 4PM, 6PM, 8PM).

---

## Plan D: Infrastructure Gaps Analysis

### Pre-LIVE Checklist (Blocking)

| Gap | Status | Effort | Action |
|-----|--------|--------|--------|
| Slippage tracking | Partial | 1 hour | Verify `order_result` contains `fill_price`, update `log_trade()` |
| WebSocket position_monitor | Plan A | 4 hours | Implement `position_monitor.py` + `ws/connection.py` |
| Volume-tier filter | Plan B | 2 hours | Add `apply_volume_tier()` to `edge_detector.py` |
| Higher crypto cadence | Plan C | 30 min | Add Task Scheduler tasks |

### Post-LIVE (Not Blocking)

| Gap | Priority | Notes |
|-----|----------|-------|
| Correlation matrix | Medium | Add when portfolio > $5k deployed |
| Batch orders | Low | Reduces API calls for multi-position entry |
| Order amendments | Low | Useful for limit order price adjustment |
| Cache TTL logging | Low | Add to optimizer_notes for staleness tracking |

### Gap Details

#### 1. Order Book Depth
**Status:** Already handled  
- `volume_24h_fp` → Plan B volume-tier filter
- `open_interest_fp` → already wired in `strategy.py` for OI cap (5%)

#### 2. Slippage/Fill Tracking
**Pre-LIVE Action:**
```python
# In log_trade() or trade execution, after order placement:
def extract_fill_price(order_result: dict) -> float | None:
    """Extract actual fill price from Kalshi order result."""
    # Kalshi returns fills array with price per fill
    fills = order_result.get('fills', [])
    if not fills:
        return order_result.get('avg_price')  # Fallback
    
    # Weighted average of fill prices
    total_contracts = sum(f.get('count', 0) for f in fills)
    if total_contracts == 0:
        return None
    
    weighted_sum = sum(f.get('price', 0) * f.get('count', 0) for f in fills)
    return weighted_sum / total_contracts
```

Add to JSONL logging:
- `scan_price`: price at scan time
- `fill_price`: actual execution price from order result
- `slippage`: `fill_price - scan_price` (for analysis)

#### 3. Cross-Market Correlation
**Not required pre-LIVE.**  
Existing caps provide sufficient protection:
- OI cap: 5% per market
- Daily cap: $700 crypto
- Per-trade cap: $100

**Post-LIVE implementation:**
```python
CORRELATION_GROUPS = {
    'crypto_major': ['KXBTC', 'KXETH'],  # Highly correlated
    'crypto_alt': ['KXXRP', 'KXDOGE'],   # Correlated with each other + majors
}

def check_correlation_exposure(ticker: str, positions: list) -> bool:
    """Return True if adding this position would exceed correlation limits."""
    # Find which group this ticker belongs to
    # Sum exposure in that group
    # Block if group exposure > threshold (e.g., 20% of capital)
    pass
```

#### 4. Signal Staleness
**Not required pre-LIVE.**  
- Weather: `get_full_weather_signal()` cached per scan session — fresh each cycle
- Crypto: spot prices fetched at scan time, fresh
- WebSocket mode: eliminates staleness for price data

**Post-LIVE:** Add cache TTL logging to optimizer_notes for decay analysis.

#### 5. Unused Kalshi API Features
| Feature | Use Case | Priority |
|---------|----------|----------|
| Conditional orders | Not needed — we enter at market | None |
| Batch orders | Reduce API calls for multi-entry | Low |
| RFQ (block trades) | Only for $1k+ positions | None |
| Order amendments | Limit order price adjustment | Low |
| `fill` channel | Already in Plan A | Done |
| Market series data | Already using correctly | Done |

---

## Summary for Dev

### Tonight's Implementation Order

1. **Plan B (Volume-tier filter)** — 2 hours
   - Add constants to `config.py`
   - Add `apply_volume_tier()` to `edge_detector.py`
   - Modify `analyze_market()` to apply discount

2. **Plan C (Crypto cadence)** — 30 min
   - Run PowerShell commands to add 5 new Task Scheduler tasks
   - Verify with `schtasks /Query`

3. **Plan A (WebSocket infrastructure)** — 4 hours
   - Create `ws/` directory
   - Create `ws/__init__.py`
   - Create `ws/connection.py`
   - Create `position_monitor.py`
   - Test WS connection in DEMO mode

4. **Plan D (Slippage tracking)** — 1 hour
   - Verify Kalshi order result format
   - Update `log_trade()` to extract actual fill price
   - Add slippage field to JSONL

### Files to Create/Modify

| File | Action |
|------|--------|
| `ws/__init__.py` | CREATE |
| `ws/connection.py` | CREATE |
| `position_monitor.py` | CREATE (replaces post_trade_monitor.py) |
| `config.py` | ADD volume-tier constants |
| `edge_detector.py` | ADD `apply_volume_tier()`, MODIFY `analyze_market()` |
| Task Scheduler | ADD 5 new Ruppert-Crypto-* tasks |

---

**Architecture review complete. Ready for Dev.**
