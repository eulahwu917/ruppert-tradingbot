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

Usage: python position_monitor.py
"""
import sys
import os
import json
import uuid
import asyncio
import argparse
import logging
import math
from pathlib import Path
from datetime import date, datetime, timedelta, timezone
from typing import Optional

# Windows asyncio fix — must be set before any asyncio calls
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

# Ensure project root is on sys.path when running standalone
# Resolve workspace root and add to path (agents.ruppert.* + config shim)
_AGENTS_ROOT = Path(__file__).parent.parent.parent  # workspace/agents
_WORKSPACE_ROOT = _AGENTS_ROOT.parent               # workspace/
if str(_WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE_ROOT))

from agents.ruppert.env_config import get_paths as _get_paths
LOGS = _get_paths()['logs']
LOGS.mkdir(exist_ok=True)
LOGS_DIR = LOGS

import config
from scripts.event_logger import log_event
DRY_RUN = getattr(config, 'DRY_RUN', True)

from agents.ruppert.data_analyst.kalshi_client import KalshiClient
from agents.ruppert.data_scientist.logger import (
    log_trade, log_activity, acquire_exit_lock, release_exit_lock,
    normalize_entry_price, get_daily_exposure
)

logger = logging.getLogger(__name__)

# ─────────────────────────────── Constants ────────────────────────────────────

WS_ENABLED = True                    # Toggle WebSocket mode
WS_EVENT_LOOP_DURATION = 840         # 14 minutes (Task Scheduler runs every 30 min)
POLL_BACKSTOP_INTERVAL = 300         # 5 min polling backstop inside WS loop

# 15-min crypto direction series
CRYPTO_15M_SERIES = ['KXBTC15M', 'KXETH15M', 'KXXRP15M', 'KXDOGE15M']

# ─────────────────────────────── Helpers ──────────────────────────────────────

def ts():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def push_alert(level, message, ticker=None, pnl=None):
    """Log alert candidate event. Data Scientist decides if it's alertworthy."""
    log_event('ALERT_CANDIDATE', {
        'level': level,
        'message': message,
        'ticker': ticker,
        'pnl': pnl,
    })


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
        # No open position for this ticker — not an error, just nothing to settle
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
    
    log_event('SETTLEMENT', {
        'ticker': ticker,
        'side': side,
        'result': result,
        'pnl': round(pnl, 2),
        'entry_price': entry_price,
        'exit_price': exit_price,
        'contracts': contracts,
    })
    print(f"  [Settlement] {ticker} {side.upper()} → {result.upper()} | P&L=${pnl:+.2f}")
    push_alert('settle', f'SETTLED: {ticker} {side.upper()} → {result.upper()} | P&L=${pnl:+.2f}', ticker=ticker, pnl=pnl)


# ─────────────────────────────── Crypto Entry Evaluator ───────────────────────

def evaluate_crypto_entry(ticker: str, yes_ask: int, yes_bid: int, close_time: str = None):
    """
    Evaluate crypto market for entry based on WebSocket price tick.
    
    Called on each ticker update for crypto markets.
    Uses band_prob model to compute edge vs live price.
    """
    from agents.ruppert.trader.crypto_client import (
        get_btc_signal, get_eth_signal, get_xrp_signal, get_doge_signal,
        _band_probability, _t_cdf, ASSET_CONFIG, compute_composite_confidence
    )
    from agents.ruppert.strategist.strategy import should_enter, calculate_position_size
    from agents.ruppert.data_scientist.capital import get_capital, get_buying_power
    
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
    strike_type = 'between'  # Default to band
    strike = None
    
    if strike_part.startswith('B'):
        try:
            strike = float(strike_part[1:])
        except ValueError:
            return
        strike_type = 'between'
    elif strike_part.startswith('T'):
        try:
            strike = float(strike_part[1:])
        except ValueError:
            return
        strike_type = 'greater' if strike > current_price else 'less'
    else:
        return
    
    # Get vol and compute sigma
    cfg = ASSET_CONFIG[asset]
    realized_vol = signal.get('realized_hourly_vol') or (cfg['hourly_vol_pct'] / 100)
    
    # Parse hours to settlement from close_time if provided
    hours_left = 4.0  # Default fallback
    if close_time:
        try:
            close_dt = datetime.fromisoformat(close_time.replace('Z', '+00:00'))
            now = datetime.now(timezone.utc)
            hours_left = max((close_dt - now).total_seconds() / 3600, 0.1)
        except:
            pass
    
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
    min_edge = getattr(config, 'CRYPTO_MIN_EDGE_THRESHOLD', 0.12)
    if abs(edge) < min_edge:
        return
    
    # Check if already traded
    traded_tickers = load_traded_tickers()
    if ticker in traded_tickers:
        return
    
    # Check daily cap
    capital = get_capital()
    daily_cap = capital * config.CRYPTO_DAILY_CAP_PCT
    current_exposure = get_daily_exposure('crypto')
    
    if current_exposure >= daily_cap:
        logger.debug(f"Crypto daily cap reached: ${current_exposure:.2f} >= ${daily_cap:.2f}")
        return
    
    # Build opportunity dict
    confidence = compute_composite_confidence(edge, yes_ask, yes_bid, hours_left)
    
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
        'hours_to_settlement': hours_left,
    }
    
    # Compute open_position_value for strategy gate (same pattern as main.py)
    _total = get_capital()
    _bp = get_buying_power()
    opp['open_position_value'] = max(0.0, _total - _bp)

    # Check entry via strategy
    deployed_today = get_daily_exposure()
    decision = should_enter(opp, capital, deployed_today, module='crypto', module_deployed_pct=0.0, traded_tickers=None)
    if not decision['enter']:
        reason = decision['reason']
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
    bet_price = yes_ask if side == 'yes' else (100 - yes_ask)
    contracts = max(1, int(size / (bet_price / 100)))
    
    print(f"  [WS Crypto Entry] {ticker} {side.upper()} | edge={edge:+.1%} | ${size:.2f}")
    
    if DRY_RUN:
        order_result = {'dry_run': True, 'status': 'simulated'}
    else:
        try:
            order_result = client.place_order(ticker, side, bet_price, contracts)
        except Exception as e:
            print(f"  [WS Crypto] Order failed: {e}")
            return
    
    opp['action'] = 'buy'
    opp['contracts'] = contracts
    opp['size_dollars'] = size
    opp['timestamp'] = ts()
    opp['date'] = str(date.today())
    opp['scan_price'] = bet_price
    
    log_trade(opp, size, contracts, order_result)
    log_activity(f'[WS-CRYPTO] Entered {ticker} {side.upper()} @ {bet_price}c | edge={edge:+.1%}')
    log_event('TRADE_EXECUTED', {
        'ticker': ticker,
        'side': side,
        'size': size,
        'contracts': contracts,
        'price': bet_price,
        'dry_run': DRY_RUN,
    })
    push_alert('trade', f'WS Crypto Entry: {ticker} {side.upper()} @ {bet_price}c', ticker=ticker)


# ─────────────────────────────── Polling Logic ────────────────────────────────

def get_market_data(ticker: str) -> dict | None:
    """Fetch current market data from Kalshi API. Returns dict or None."""
    try:
        _client = KalshiClient()
        result = _client.get_market(ticker)
        return result if result else None
    except Exception:
        return None


def run_polling_scan(client: KalshiClient, run_settlement_check: bool = True):
    """
    Run the existing poll-based position check.
    Reuses check logic from post_trade_monitor.
    """
    # Import position check functions from existing module
    from post_trade_monitor import (
        check_settlements, check_weather_position, check_crypto_position,
        check_alert_only_position
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
        
        # Skip settled markets
        if market.get('status') in ('finalized', 'settled'):
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
            # Note: actual exit execution is handled by existing run_monitor()
        elif action and 'alert' in action:
            push_alert('warning', f'{ticker}: {reason}', ticker=ticker)
        elif action:
            print(f"  [Polling] {ticker}: {action} — {reason}")


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
    try:
        from ws.connection import KalshiWebSocket
    except ImportError as e:
        print(f"  [WS] Import failed: {e} — falling back to polling")
        run_polling_mode(client)
        return
    
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
    crypto_tickers = []
    try:
        for series in ['KXBTC', 'KXETH'] + CRYPTO_15M_SERIES:
            markets = client.get_markets(series_ticker=series, status='open', limit=5 if series in CRYPTO_15M_SERIES else 25)
            crypto_tickers.extend([m.get('ticker', '') for m in markets])
    except Exception as e:
        print(f"  [WS] Could not fetch crypto markets: {e}")

    all_tickers = list(set(filter(None, position_tickers + crypto_tickers)))
    
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
    settled_tickers = set()  # Avoid re-settling
    
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
                close_time = msg.get('close_time')
                open_time = msg.get('open_time')

                # Route 15-min crypto direction tickers to new evaluator
                if any(ticker.upper().startswith(s) for s in CRYPTO_15M_SERIES):
                    if yes_ask and yes_bid:
                        try:
                            from agents.ruppert.trader.crypto_15m import evaluate_crypto_15m_entry
                            evaluate_crypto_15m_entry(ticker, yes_ask, yes_bid, close_time, open_time)
                        except Exception as e:
                            logger.warning('[WS] 15m crypto eval error: %s', e)
                # Hourly band crypto tickers → existing evaluator
                elif any(ticker.upper().startswith(p) for p in ('KXBTC', 'KXETH', 'KXXRP', 'KXDOGE')):
                    if yes_ask and yes_bid:
                        evaluate_crypto_entry(ticker, yes_ask, yes_bid, close_time)

                # Check for settlement (price at 99 or 1)
                if yes_ask is not None and ticker not in settled_tickers:
                    if yes_ask >= 99:
                        _settle_single_ticker(ticker, 'yes')
                        settled_tickers.add(ticker)
                    elif yes_ask <= 1:
                        _settle_single_ticker(ticker, 'no')
                        settled_tickers.add(ticker)
            
            elif msg_type == 'fill':
                # Log fill confirmation
                order_id = msg.get('order_id', '')
                ticker = msg.get('market_ticker', '')
                print(f"  [WS Fill] Order {order_id} filled for {ticker}")
    
    except asyncio.TimeoutError:
        print(f"  [WS] Event loop timeout")
    except Exception as e:
        print(f"  [WS] Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await ws.close()
    
    # Final polling scan
    print("  [Phase 4] Final polling scan...")
    run_polling_scan(client, run_settlement_check=True)
    
    print(f"\nWebSocket monitor complete. {ts()}")


# ─────────────────────────────── Persistent WS Mode ──────────────────────────

PERSISTENT_MARKET_HOUR_START = 6   # 6 AM local
PERSISTENT_MARKET_HOUR_END   = 23  # 11 PM local
PERSISTENT_RESUB_INTERVAL    = 900 # re-fetch crypto tickers every 15 min


def _in_market_hours() -> bool:
    """Return True if current local hour is within 6AM–11PM."""
    return PERSISTENT_MARKET_HOUR_START <= datetime.now().hour < PERSISTENT_MARKET_HOUR_END


async def run_persistent_ws_mode():
    """
    Persistent WebSocket session that runs continuously during market hours.
    Separate from the 15-min polling task — this is the real-time crypto entry path.

    Lifecycle:
      - Connects WS and subscribes to active crypto markets
      - Processes ticker events for real-time crypto entry
      - Re-fetches ticker list every 15 min (markets open/close)
      - Reconnects automatically on disconnect
      - Exits cleanly outside market hours (6AM–11PM)
    """
    try:
        from ws.connection import KalshiWebSocket, WS_AVAILABLE
        if not WS_AVAILABLE:
            print("  [Persistent WS] websockets package not installed — exiting")
            return
    except ImportError as e:
        print(f"  [Persistent WS] Import failed: {e}")
        return

    print(f"\n{'='*60}")
    print(f"  PERSISTENT WS SESSION — {ts()}")
    print(f"  Market hours: {PERSISTENT_MARKET_HOUR_START}:00–{PERSISTENT_MARKET_HOUR_END}:00")
    print(f"{'='*60}\n")
    log_activity('[WS] Persistent WebSocket session started')

    client = KalshiClient()

    while _in_market_hours():
        # Build subscription list from active crypto markets
        crypto_tickers = []
        try:
            for series in ['KXBTC', 'KXETH'] + CRYPTO_15M_SERIES:
                markets = client.get_markets(series_ticker=series, status='open', limit=5 if series in CRYPTO_15M_SERIES else 25)
                crypto_tickers.extend([m.get('ticker', '') for m in markets])
        except Exception as e:
            print(f"  [Persistent WS] Could not fetch crypto markets: {e}")

        crypto_tickers = list(set(filter(None, crypto_tickers)))
        if not crypto_tickers:
            print(f"  [Persistent WS] No crypto tickers — sleeping 60s")
            await asyncio.sleep(60)
            continue

        print(f"  [WS] Connecting ({len(crypto_tickers)} tickers)...")

        ws = KalshiWebSocket(
            api_key_id=config.get_api_key_id(),
            private_key_path=config.get_private_key_path(),
            environment=config.get_environment(),
        )

        connected = await ws.connect()
        if not connected:
            print(f"  [Persistent WS] Connection failed — retry in 30s")
            log_activity('[WS] Connection failed, retrying in 30s')
            await asyncio.sleep(30)
            continue

        await ws.subscribe_ticker(crypto_tickers)
        print(f"  [WS] Connected and subscribed at {ts()}")
        log_activity(f'[WS] Connected, subscribed to {len(crypto_tickers)} crypto tickers')

        last_resub = asyncio.get_event_loop().time()

        try:
            async for msg in ws.messages():
                # Exit outside market hours
                if not _in_market_hours():
                    print(f"  [Persistent WS] Outside market hours — shutting down")
                    break

                now = asyncio.get_event_loop().time()

                # Periodically re-fetch ticker list
                if now - last_resub >= PERSISTENT_RESUB_INTERVAL:
                    new_tickers = []
                    try:
                        for series in ['KXBTC', 'KXETH'] + CRYPTO_15M_SERIES:
                            markets = client.get_markets(series_ticker=series, status='open', limit=5 if series in CRYPTO_15M_SERIES else 25)
                            new_tickers.extend([m.get('ticker', '') for m in markets])
                    except Exception:
                        pass
                    new_tickers = list(set(filter(None, new_tickers)))
                    added = set(new_tickers) - set(crypto_tickers)
                    if added:
                        await ws.subscribe_ticker(list(added))
                        print(f"  [WS] Re-subscribed, added {len(added)} new tickers")
                    crypto_tickers = new_tickers
                    last_resub = now

                # Handle ticker messages for crypto entry
                msg_type = msg.get('type')
                if msg_type == 'ticker':
                    ticker = msg.get('market_ticker', '')
                    yes_ask = msg.get('yes_ask')
                    yes_bid = msg.get('yes_bid')
                    close_time = msg.get('close_time')
                    open_time = msg.get('open_time')

                    # Route 15-min direction tickers to new evaluator
                    if any(ticker.upper().startswith(s) for s in CRYPTO_15M_SERIES):
                        if yes_ask and yes_bid:
                            try:
                                from agents.ruppert.trader.crypto_15m import evaluate_crypto_15m_entry
                                evaluate_crypto_15m_entry(ticker, yes_ask, yes_bid, close_time, open_time)
                            except Exception as e:
                                logger.warning('[Persistent WS] 15m crypto eval error: %s', e)
                    # Hourly band tickers → existing evaluator
                    elif any(ticker.upper().startswith(p) for p in ('KXBTC', 'KXETH', 'KXXRP', 'KXDOGE')):
                        if yes_ask and yes_bid:
                            evaluate_crypto_entry(ticker, yes_ask, yes_bid, close_time)

        except Exception as e:
            print(f"  [Persistent WS] Error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            await ws.close()

        if _in_market_hours():
            print(f"  [Persistent WS] Disconnected — reconnecting in 5s...")
            await asyncio.sleep(5)

    print(f"\n  [Persistent WS] Session ended at {ts()}")
    log_activity('[WS] Persistent WebSocket session ended (outside market hours)')


# ─────────────────────────────── Polling Mode (Fallback) ──────────────────────

def run_polling_mode(client: KalshiClient):
    """
    Thin wrapper around existing polling logic.
    Used when WebSocket is disabled or unavailable.
    """
    from post_trade_monitor import run_monitor
    
    print(f"\n{'='*60}")
    print(f"  POSITION MONITOR (Polling Mode)  {ts()}")
    print(f"{'='*60}")
    
    # Delegate to existing run_monitor() which handles everything
    run_monitor()
    
    print(f"\nPolling monitor complete. {ts()}")


# ─────────────────────────────── Main Entry Point ─────────────────────────────

def main():
    """
    Main entry point for position monitor.

    Modes:
      --persistent   Continuous WS session during market hours (6AM-11PM).
                     Separate from the polling task — run as its own scheduled task.
      (default)      14-min WS event loop, used by the 15-min polling task.
    """
    parser = argparse.ArgumentParser(description='Ruppert Position Monitor')
    parser.add_argument('--persistent', action='store_true',
                        help='Run persistent WS session (market hours only)')
    args = parser.parse_args()

    if args.persistent:
        # Delegate to ws_feed.py — the new persistent WS-first architecture.
        # ws_feed.py handles: market_cache, position_tracker, crypto entry routing.
        try:
            from agents.ruppert.data_analyst.ws_feed import run
            print("  [Monitor] Delegating to ws_feed.py (WS-first architecture)")
            run()
            return
        except ImportError as e:
            print(f"  [Monitor] ws_feed import failed ({e}) — falling back to legacy persistent mode")
        if not _in_market_hours():
            print(f"  [Persistent WS] Outside market hours ({PERSISTENT_MARKET_HOUR_START}:00–{PERSISTENT_MARKET_HOUR_END}:00) — exiting")
            return
        asyncio.run(run_persistent_ws_mode())
        return

    client = KalshiClient()

    # Check if WebSocket is available and enabled
    ws_available = False
    if WS_ENABLED:
        try:
            from ws.connection import KalshiWebSocket, WS_AVAILABLE
            ws_available = WS_AVAILABLE
        except ImportError:
            print("  [Monitor] WebSocket module not available — using polling mode")

    if ws_available:
        # Run async WebSocket mode
        print("  [Monitor] Starting WebSocket mode...")
        asyncio.run(run_ws_mode(client))
    else:
        # Fallback to polling
        print("  [Monitor] WebSocket not available — using polling mode")
        run_polling_mode(client)


if __name__ == '__main__':
    main()
