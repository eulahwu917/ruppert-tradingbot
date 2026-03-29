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
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Resolve workspace root and add to path for env_config
_AGENTS_ROOT = Path(__file__).parent.parent.parent  # workspace/agents
_WORKSPACE_ROOT = _AGENTS_ROOT.parent               # workspace/
if str(_WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE_ROOT))

# Also add environments/demo so bare `import config` resolves when ws_feed
# is the entry point (Task Scheduler runs it directly, not via ruppert_cycle)
_DEMO_ENV_ROOT = _WORKSPACE_ROOT / 'environments' / 'demo'
if str(_DEMO_ENV_ROOT) not in sys.path:
    sys.path.insert(0, str(_DEMO_ENV_ROOT))

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

# Per-window evaluation dedup guard
# Key: "{series}::{window_open_iso}"  Value: ISO timestamp when evaluated
_window_evaluated: dict[str, str] = {}

# Lazy KalshiClient instance for REST fallback (avoids re-init per poll cycle)
_kalshi_client_instance = None

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


# ─────────────────────────────── REST Fallback Helpers ───────────────────────

def _get_kalshi_client():
    """Lazy singleton getter for KalshiClient — avoids re-init per poll cycle."""
    global _kalshi_client_instance
    if _kalshi_client_instance is None:
        from agents.ruppert.data_analyst.kalshi_client import KalshiClient
        _kalshi_client_instance = KalshiClient()
    return _kalshi_client_instance


def _prune_window_guard():
    """Remove dedup entries older than 60 minutes."""
    cutoff = (datetime.utcnow() - timedelta(hours=1)).isoformat()
    stale = [k for k, v in _window_evaluated.items() if v < cutoff]
    for k in stale:
        del _window_evaluated[k]


async def _resolve_15m_ticker(series: str, window_open_dt: datetime) -> dict | None:
    """Find the active 15m market for this series and window via REST.
    Returns market dict with yes_ask, yes_bid, close_time, open_time, or None.
    """
    loop = asyncio.get_running_loop()
    markets = await loop.run_in_executor(
        None,
        lambda: _get_kalshi_client().get_markets_metadata(series, status='open')
    )
    window_open_iso = window_open_dt.replace(tzinfo=timezone.utc).isoformat()
    for m in markets:
        if (m.get('open_time') or '').replace('Z', '+00:00') == window_open_iso:
            return m
    return None


def _enrich_and_compute_depth(m):
    """Fetch orderbook for market dict m, enrich with bid/ask, compute book_depth_usd.
    Runs in executor (blocking). Modifies m in place and returns it.
    """
    client = _get_kalshi_client()
    t = m.get('ticker', '')
    host = client.client.configuration.host
    ob_url = f"{host}/markets/{t}/orderbook"
    from agents.ruppert.data_analyst.kalshi_client import _get_with_retry
    ob_resp = _get_with_retry(ob_url, timeout=5)
    depth = 0.0
    if ob_resp is not None and ob_resp.status_code == 200:
        ob = ob_resp.json().get('orderbook_fp', {})
        yes_side = ob.get('yes_dollars', [])   # [[price_str, vol_str], ...]
        no_side  = ob.get('no_dollars', [])
        # Top-3 volumes on each side (vol is already in dollars)
        yes_vols = sorted([float(v) for p, v in yes_side], reverse=True)[:3]
        no_vols  = sorted([float(v) for p, v in no_side],  reverse=True)[:3]
        depth = sum(yes_vols) + sum(no_vols)
        # Derive bid/ask from the same response
        if no_side:
            best_no_bid = max(float(p) for p, v in no_side)
            m['no_bid']  = int(round(best_no_bid * 100))
            m['yes_ask'] = 100 - m['no_bid']
        if yes_side:
            best_yes_bid = max(float(p) for p, v in yes_side)
            m['yes_bid'] = int(round(best_yes_bid * 100))
            m['no_ask']  = 100 - m['yes_bid']
    m['_book_depth_usd'] = depth
    return m


async def _fetch_15m_market_price(series: str, window_open_dt: datetime) -> dict | None:
    """Resolve ticker and fetch live bid/ask for a 15m series/window via REST."""
    market = await _resolve_15m_ticker(series, window_open_dt)
    if not market:
        logger.warning('[Fallback] No open market found for %s window %s', series, window_open_dt)
        return None

    ticker = market.get('ticker', '')
    if not ticker:
        return None

    loop = asyncio.get_running_loop()
    enriched = await loop.run_in_executor(None, lambda: _enrich_and_compute_depth(market))

    yes_ask = enriched.get('yes_ask')
    yes_bid = enriched.get('yes_bid')
    book_depth_usd = enriched.get('_book_depth_usd', 0.0)
    if yes_ask is None or yes_bid is None:
        logger.warning('[Fallback] No bid/ask from REST for %s', ticker)
        return None

    return {
        'ticker': ticker,
        'yes_ask': yes_ask,                    # cents (int)
        'yes_bid': yes_bid,                    # cents (int)
        'book_depth_usd': book_depth_usd,      # sum of top-3 volumes each side (dollars)
        'open_time': market.get('open_time'),
        'close_time': market.get('close_time'),
    }


async def _check_and_fire_fallback() -> None:
    """Check each 15m series; fire REST-based evaluation if WS missed the window."""
    now_utc = datetime.now(tz=timezone.utc)

    # Compute current 15m window boundaries
    window_minutes = (now_utc.minute // 15) * 15
    window_open_dt = now_utc.replace(minute=window_minutes, second=0, microsecond=0)
    window_close_dt = window_open_dt + timedelta(minutes=15)
    window_open_iso = window_open_dt.isoformat()

    elapsed_secs = (now_utc - window_open_dt).total_seconds()
    remaining_secs = (window_close_dt - now_utc).total_seconds()

    # Only fire in the useful window: 90s after open, 120s before close
    if elapsed_secs < 90 or remaining_secs < 120:
        return

    for series in CRYPTO_15M_SERIES:
        guard_key = f"{series}::{window_open_iso}"

        # Skip if WS already evaluated this window
        if guard_key in _window_evaluated:
            continue

        try:
            market = await _fetch_15m_market_price(series, window_open_dt)
            if not market:
                continue

            ticker = market['ticker']
            yes_ask = market['yes_ask']
            yes_bid = market['yes_bid']
            close_time = market['close_time']
            open_time = market['open_time']

            # Update market cache with REST price
            market_cache.update(ticker, yes_bid / 100, yes_ask / 100, source='rest_fallback')

            logger.info('[Fallback] Firing REST eval for %s (WS missed window)', ticker)

            book_depth_usd = market.get('book_depth_usd', 0.0)

            from agents.ruppert.trader.crypto_15m import evaluate_crypto_15m_entry
            try:
                evaluate_crypto_15m_entry(
                    ticker, yes_ask, yes_bid, close_time, open_time,
                    book_depth_usd=book_depth_usd,  # computed from top-3 volumes each side
                    dollar_oi=0.0,                  # REST OI not fetched here — strategy must tolerate 0
                )
            finally:
                # Always mark window evaluated — even on exception — to prevent retry storm
                _window_evaluated[guard_key] = now_utc.isoformat()

        except Exception as e:
            logger.warning('[Fallback] eval error for %s: %s', series, e)


async def _fallback_poll_loop() -> None:
    """Background task: REST-poll each 15m series if WS hasn't fired for current window.
    Created and cancelled per WS connection cycle — do not run globally.
    """
    while True:
        await asyncio.sleep(60)
        try:
            await _check_and_fire_fallback()
        except asyncio.CancelledError:
            raise  # propagate cancellation
        except Exception as e:
            logger.warning('[WS Feed] Fallback poll error: %s', e)


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
            # Mark this window as evaluated so fallback poll skips it
            _series = next((s for s in CRYPTO_15M_SERIES if ticker_upper.startswith(s)), None)
            # Normalize Z suffix to match fallback's +00:00 format
            _open_time_norm = open_time.replace('Z', '+00:00') if open_time and open_time.endswith('Z') else open_time
            if _series and _open_time_norm:
                _window_evaluated[f"{_series}::{_open_time_norm}"] = datetime.utcnow().isoformat()

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


# ─────────────────────────────── REST Stale Heal ────────────────────────────

async def _rest_refresh_stale() -> None:
    """Refresh stale tracked-ticker cache entries via Kalshi REST.
    Called once per 5-minute heartbeat cycle from inside run_ws_feed().
    Only refreshes tickers actively tracked by position_tracker.
    """
    try:
        tracked = position_tracker.get_tracked()
    except Exception as e:
        logger.warning('[WS Feed] _rest_refresh_stale: could not get tracked: %s', e)
        return

    kalshi_client = None
    for key_str in tracked:
        ticker = key_str.split('::')[0]  # get_tracked() returns 'ticker::side' keys
        try:
            _, _, is_stale = market_cache.get_with_staleness(ticker)
            if not is_stale:
                continue
            if kalshi_client is None:
                from agents.ruppert.data_analyst.kalshi_client import KalshiClient
                kalshi_client = KalshiClient()
            result = kalshi_client.get_market(ticker)
            if result and result.get('yes_bid') is not None and result.get('yes_ask') is not None:
                bid_d = result['yes_bid'] / 100
                ask_d = result['yes_ask'] / 100
                market_cache.update(ticker, bid_d, ask_d, source='rest_heal')
                logger.debug('[WS Feed] REST heal: %s', ticker)
        except Exception as e:
            logger.warning('[WS Feed] _rest_refresh_stale error for %s: %s', ticker, e)


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

    while True:
        try:
            headers = _build_auth_headers()

            async with websockets.connect(
                'wss://api.elections.kalshi.com/trade-api/ws/v2',
                additional_headers=headers,
                ping_interval=None,
                ping_timeout=None,
            ) as ws:
                print(f'  [WS Feed] Connected at {ts()}')
                log_activity('[WS Feed] Connected')
                _write_heartbeat()  # update heartbeat on every successful reconnect

                # Subscribe to ALL ticker updates (no market_tickers filter)
                await ws.send(json.dumps({
                    'id': 1,
                    'cmd': 'subscribe',
                    'params': {'channels': ['ticker']}
                }))

                last_purge = time.time()
                last_persist = time.time()
                msg_count = 0

                # START fallback task for this connection cycle
                fallback_task = asyncio.create_task(_fallback_poll_loop())

                try:
                    async for raw in ws:
                        msg = json.loads(raw)
                        await handle_message(msg)
                        msg_count += 1

                        # Yield to event loop every 100 messages so server PINGs get answered
                        if msg_count % 100 == 0:
                            await asyncio.sleep(0)

                        now = time.time()

                        # Periodic persist every 60s
                        if now - last_persist >= 60:
                            market_cache.persist()
                            _write_heartbeat()
                            last_persist = now

                        # Periodic purge every 5 min
                        if now - last_purge > 300:
                            market_cache.purge_stale()
                            await _rest_refresh_stale()
                            _prune_window_guard()
                            cache_size = len(market_cache.snapshot())
                            tracked_count = len(position_tracker.get_tracked())
                            print(
                                f'  [WS Feed] Heartbeat: {msg_count} msgs, '
                                f'{cache_size} cached, {tracked_count} tracked | {ts()}'
                            )
                            _write_heartbeat()
                            last_purge = now
                finally:
                    # CANCEL on every exit (disconnect, exception, clean shutdown)
                    fallback_task.cancel()
                    try:
                        await fallback_task
                    except asyncio.CancelledError:
                        pass

        except Exception as e:
            print(f'  [WS Feed] Disconnected: {e} — reconnecting in 5s')
            log_activity(f'[WS Feed] Disconnected: {e}')

            # On disconnect: REST-poll tracked positions to catch missed moves
            try:
                await position_tracker.recovery_poll_positions()
            except Exception as re:
                logger.warning('[WS Feed] Recovery poll failed: %s', re)

            await asyncio.sleep(5)  # fixed 5s wait, then infinite retry

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
