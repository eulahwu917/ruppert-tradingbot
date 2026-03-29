"""
ws_feed.py — Persistent WebSocket feed for Kalshi market data
Single WS connection subscribed to ALL tickers, feeding market_cache.
Replaces position_monitor.py --persistent as the real-time data path.

Run as: python ws_feed.py
Or import and call run() from another module.

Architecture:
  1. Loads price cache from disk
  2. Connects WS, subscribes to all tickers (no market_tickers filter)
  3. Routes messages: cache updates, exit checks, crypto entry evaluation
  4. Runs until shutdown (Ctrl+C)
"""

import sys
import os
import asyncio
import json
import time
import logging
from datetime import datetime
from pathlib import Path

# Resolve workspace root and add to path for env_config
_AGENTS_ROOT = Path(__file__).parent.parent.parent  # workspace/agents
_WORKSPACE_ROOT = _AGENTS_ROOT.parent               # workspace/
if str(_WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE_ROOT))

# Windows asyncio fix
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

import config
import agents.ruppert.data_analyst.market_cache as market_cache
import agents.ruppert.trader.position_tracker as position_tracker

logger = logging.getLogger(__name__)

DRY_RUN = getattr(config, 'DRY_RUN', True)

# Series prefixes from config (updateable without code change)
ACTIVE_SERIES_PREFIXES = set(getattr(config, 'WS_ACTIVE_SERIES', []))

# 15-min crypto direction series (subset of active series)
CRYPTO_15M_SERIES = ['KXBTC15M', 'KXETH15M', 'KXXRP15M', 'KXDOGE15M']

# Crypto hourly band prefixes
CRYPTO_HOURLY_PREFIXES = ('KXBTC', 'KXETH', 'KXXRP', 'KXDOGE', 'KXSOL')

def ts():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def is_relevant(ticker: str) -> bool:
    """Return True if ticker matches any active series prefix."""
    t = ticker.upper()
    return any(t.startswith(p) for p in ACTIVE_SERIES_PREFIXES)


def _build_auth_headers() -> dict:
    """Build WS auth headers reusing existing auth from ws/connection.py."""
    import base64
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    timestamp = str(int(time.time() * 1000))
    method = "GET"
    path = "/trade-api/ws/v2"

    key_data = Path(config.get_private_key_path()).read_bytes()
    private_key = serialization.load_pem_private_key(key_data, password=None)

    msg = f"{timestamp}{method}{path}".encode()
    signature = private_key.sign(
        msg,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH
        ),
        hashes.SHA256()
    )
    sig_b64 = base64.b64encode(signature).decode()

    return {
        "KALSHI-ACCESS-KEY": config.get_api_key_id(),
        "KALSHI-ACCESS-SIGNATURE": sig_b64,
        "KALSHI-ACCESS-TIMESTAMP": timestamp,
    }


# ─────────────────────────────── Message Handler ──────────────────────────────

async def handle_message(msg: dict):
    """Route a single WS message to appropriate handlers."""
    msg_type = msg.get('type')

    if msg_type != 'ticker':
        return  # ignore fills, subscribed confirmations, etc.

    data = msg.get('msg', {})
    ticker = data.get('market_ticker', '')

    if not ticker or not is_relevant(ticker):
        return  # discard irrelevant markets

    # Extract prices — WS sends dollar strings (e.g. "0.3400"), not cent ints
    # yes_bid_dollars / yes_ask_dollars are the correct field names
    yes_bid_d = data.get('yes_bid_dollars')
    yes_ask_d = data.get('yes_ask_dollars')

    # Convert to cent integers for downstream consumers
    yes_bid = round(float(yes_bid_d) * 100) if yes_bid_d is not None else None
    yes_ask = round(float(yes_ask_d) * 100) if yes_ask_d is not None else None

    # Update shared cache (store as dollar fractions)
    if yes_bid is not None and yes_ask is not None:
        market_cache.update(ticker, float(yes_bid_d), float(yes_ask_d))

    # Check exit triggers for tracked positions
    await position_tracker.check_exits(ticker, yes_bid, yes_ask)

    # Route crypto 15m tickers to evaluate entry
    ticker_upper = ticker.upper()
    if any(ticker_upper.startswith(s) for s in CRYPTO_15M_SERIES):
        close_time = data.get('close_time')
        open_time = data.get('open_time')
        # Estimate book depth from WS message size fields (dollars)
        ask_size = float(data.get('yes_ask_size_fp') or 0)
        bid_size = float(data.get('yes_bid_size_fp') or 0)
        book_depth_usd = ask_size + bid_size
        dollar_oi = float(data.get('dollar_open_interest') or 0)
        if yes_ask and yes_bid:
            try:
                from agents.ruppert.trader.crypto_15m import evaluate_crypto_15m_entry
                evaluate_crypto_15m_entry(ticker, yes_ask, yes_bid, close_time, open_time, book_depth_usd, dollar_oi)
            except Exception as e:
                logger.warning('[WS Feed] 15m eval error: %s', e)

    # Route crypto hourly band tickers
    elif any(ticker_upper.startswith(p) for p in CRYPTO_HOURLY_PREFIXES):
        # Skip 15m tickers that also match hourly prefixes (already handled above)
        if not any(ticker_upper.startswith(s) for s in CRYPTO_15M_SERIES):
            if yes_ask and yes_bid:
                try:
                    from agents.ruppert.trader.position_monitor import evaluate_crypto_entry
                    evaluate_crypto_entry(ticker, yes_ask, yes_bid, data.get('close_time'))
                except Exception as e:
                    logger.warning('[WS Feed] Crypto eval error: %s', e)


# ─────────────────────────────── Main WS Loop ────────────────────────────────

async def run_ws_feed():
    """Main WS feed loop. Connects once, runs indefinitely until shutdown."""
    try:
        import websockets
    except ImportError:
        print('[WS Feed] websockets package not installed. Run: pip install websockets')
        return

    market_cache.load()  # restore from disk on startup

    print(f"\n{'='*60}")
    print(f"  WS FEED — {ts()}")
    print(f"  Mode: 24/7 (no market-hour restriction)")
    print(f"  Active series: {len(ACTIVE_SERIES_PREFIXES)} prefixes")
    print(f"  Tracked positions: {len(position_tracker.get_tracked())}")
    print(f"  Mode: {'DRY RUN' if DRY_RUN else 'LIVE'}")
    print(f"{'='*60}\n")

    from agents.ruppert.data_scientist.logger import log_activity
    log_activity('[WS Feed] Starting persistent WebSocket feed')

    reconnect_delay = 1

    while True:
        try:
            headers = _build_auth_headers()

            async with websockets.connect(
                'wss://api.elections.kalshi.com/trade-api/ws/v2',
                additional_headers=headers,
                ping_interval=None,
                ping_timeout=None,
            ) as ws:
                reconnect_delay = 1  # reset on successful connect
                print(f'  [WS Feed] Connected at {ts()}')
                log_activity('[WS Feed] Connected')

                # Subscribe to ALL ticker updates (no market_tickers filter)
                await ws.send(json.dumps({
                    'id': 1,
                    'cmd': 'subscribe',
                    'params': {'channels': ['ticker']}
                }))

                last_purge = time.time()
                msg_count = 0

                async for raw in ws:
                    msg = json.loads(raw)
                    await handle_message(msg)
                    msg_count += 1

                    # Periodic purge every 5 min
                    now = time.time()
                    if now - last_purge > 300:
                        market_cache.purge_stale()
                        cache_size = len(market_cache.snapshot())
                        tracked_count = len(position_tracker.get_tracked())
                        print(
                            f'  [WS Feed] Heartbeat: {msg_count} msgs, '
                            f'{cache_size} cached, {tracked_count} tracked | {ts()}'
                        )
                        _write_heartbeat()
                        last_purge = now

        except Exception as e:
            print(f'  [WS Feed] Disconnected: {e} (client pings disabled) — reconnecting in {reconnect_delay}s')
            log_activity(f'[WS Feed] Disconnected: {e} (client pings disabled)')

            # On disconnect: REST-poll tracked positions to catch missed moves
            try:
                await position_tracker.recovery_poll_positions()
            except Exception as re:
                logger.warning('[WS Feed] Recovery poll failed: %s', re)

            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 60)  # exponential backoff, max 60s

        finally:
            market_cache.persist()

    print(f'\n  [WS Feed] Session ended at {ts()}')
    log_activity('[WS Feed] Session ended')
    market_cache.persist()


# ─────────────────────────────── Entry Point ──────────────────────────────────

def _write_heartbeat():
    """Write heartbeat file so watchdog knows we're alive."""
    try:
        from agents.ruppert.env_config import get_paths as _get_paths
        heartbeat_file = _get_paths()['logs'] / 'ws_feed_heartbeat.json'
        heartbeat_file.parent.mkdir(parents=True, exist_ok=True)
        heartbeat_file.write_text(json.dumps({
            'last_heartbeat': datetime.now().isoformat(),
            'pid': os.getpid(),
            'status': 'running',
        }), encoding='utf-8')
    except Exception as _e:
        pass  # Non-fatal — watchdog will eventually restart if heartbeat stalls


def run():
    """Convenience wrapper for importing from other modules."""
    asyncio.run(run_ws_feed())


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(name)s %(levelname)s %(message)s',
    )
    run()
