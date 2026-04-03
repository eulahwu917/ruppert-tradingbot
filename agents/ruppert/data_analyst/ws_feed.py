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
import math
import time
import logging
from datetime import date, datetime, timezone, timedelta
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
from scripts.event_logger import log_event
import agents.ruppert.data_analyst.market_cache as market_cache
import agents.ruppert.trader.position_tracker as position_tracker
import agents.ruppert.trader.circuit_breaker as circuit_breaker

logger = logging.getLogger(__name__)

DRY_RUN = getattr(config, 'DRY_RUN', True)

# Per-window evaluation dedup guard
# Key: "{series}::{window_open_iso}"  Value: ISO timestamp when evaluated
_window_evaluated: dict[str, str] = {}
_window_eval_lock = asyncio.Lock()

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
    cutoff = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)).isoformat()
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

    # Only fire in the useful window: 90s after open, FALLBACK_MIN_REMAINING before close
    # Align with CRYPTO_15M_ENTRY_CUTOFF_SECS so fallback doesn't waste REST calls
    # on windows the entry evaluator would block anyway.
    _fallback_min_remaining = getattr(config, 'CRYPTO_15M_FALLBACK_MIN_REMAINING', 180)
    if elapsed_secs < 90 or remaining_secs < _fallback_min_remaining:
        return

    for series in CRYPTO_15M_SERIES:
        guard_key = f"{series}::{window_open_iso}"

        # Skip if WS already evaluated this window (atomic check+set under lock)
        async with _window_eval_lock:
            if guard_key in _window_evaluated:
                continue
            _window_evaluated[guard_key] = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()

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
            evaluate_crypto_15m_entry(
                ticker, yes_ask, yes_bid, close_time, open_time,
                book_depth_usd=book_depth_usd,  # computed from top-3 volumes each side
                dollar_oi=0.0,                  # REST OI not fetched here — strategy must tolerate 0
            )

        except Exception as e:
            logger.warning('[Fallback] eval error for %s: %s', series, e)


async def _fallback_poll_loop() -> None:
    """Background task: REST-poll each 15m series if WS hasn't fired for current window.
    Created and cancelled per WS connection cycle — do not run globally.
    Poll interval: 30s (was 60s) to catch windows missed mid-cycle.
    """
    while True:
        await asyncio.sleep(30)  # tightened from 60s — catches stragglers sooner
        try:
            await _check_and_fire_fallback()
        except asyncio.CancelledError:
            raise  # propagate cancellation
        except Exception as e:
            logger.warning('[WS Feed] Fallback poll error: %s', e)


# ─────────────────────────────── Crypto Hourly Entry Evaluator ───────────────

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
    from agents.ruppert.trader.utils import load_traded_tickers, push_alert

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

    # Derive module from series + strike_type
    _WS_MODULE_MAP = {
        ('BTC', 'between'): 'crypto_band_daily_btc',
        ('ETH', 'between'): 'crypto_band_daily_eth',
        ('XRP', 'between'): 'crypto_band_daily_xrp',
        ('DOGE', 'between'): 'crypto_band_daily_doge',
        ('SOL', 'between'): 'crypto_band_daily_sol',
        ('BTC', 'greater'): 'crypto_threshold_daily_btc',
        ('BTC', 'less'):    'crypto_threshold_daily_btc',
        ('ETH', 'greater'): 'crypto_threshold_daily_eth',
        ('ETH', 'less'):    'crypto_threshold_daily_eth',
        ('SOL', 'greater'): 'crypto_threshold_daily_sol',
        ('SOL', 'less'):    'crypto_threshold_daily_sol',
    }
    _ws_module = _WS_MODULE_MAP.get((asset, strike_type), f'crypto_band_daily_{asset.lower()}')

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
        except Exception:
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

    # ── Decision logging helpers ─────────────────────────────────────────────
    # Import log functions lazily — only needed when a decision is made.
    def _log_threshold_skip(reason_str):
        """Log a SKIP decision for threshold_daily (above/below) contracts."""
        if strike_type in ('greater', 'less'):
            try:
                from agents.ruppert.trader.crypto_threshold_daily import _log_decision as _log_td
                _log_td(
                    asset=asset, window='ws', signals={}, decision='SKIP', reason=reason_str,
                    ticker=ticker, side=side, edge=round(edge, 4),
                    model_prob=round(model_prob, 4), confidence=confidence,
                )
            except Exception as _ld_err:
                logger.debug('[WS-CRYPTO] _log_threshold_skip failed: %s', _ld_err)

    def _log_band_skip(reason_str):
        """Log a SKIP decision for band_daily (between) contracts."""
        if strike_type == 'between':
            try:
                from agents.ruppert.trader.crypto_band_daily import _log_band_decision as _log_bd
                _log_bd(
                    ticker=ticker, series=series,
                    spot=current_price, band_mid=strike,
                    sigma=sigma, prob_model=model_prob,
                    mkt_yes=yes_ask / 100.0,
                    edge_yes=round(edge, 4) if side == 'yes' else round(-edge, 4),
                    edge_no=round(-edge, 4) if side == 'yes' else round(edge, 4),
                    decision='SKIP', skip_reason=reason_str,
                )
            except Exception as _ld_err:
                logger.debug('[WS-CRYPTO] _log_band_skip failed: %s', _ld_err)

    def _log_skip(reason_str):
        """Dispatch SKIP log to the right module based on strike_type."""
        if strike_type in ('greater', 'less'):
            _log_threshold_skip(reason_str)
        else:
            _log_band_skip(reason_str)
    # ── End decision logging helpers ──────────────────────────────────────────

    # Check minimum edge threshold
    min_edge = getattr(config, 'CRYPTO_MIN_EDGE_THRESHOLD', 0.12)
    if abs(edge) < min_edge:
        return  # sub-threshold: not worth logging (very frequent, noisy)

    # Check if already traded
    traded_tickers = load_traded_tickers()
    if ticker in traded_tickers:
        return

    # Check daily cap
    from agents.ruppert.data_scientist.capital import get_capital
    from agents.ruppert.data_scientist.logger import get_daily_exposure
    capital = get_capital()
    daily_cap = capital * getattr(config, 'DAILY_CAP_RATIO', 0.70)
    current_exposure = get_daily_exposure()

    if current_exposure >= daily_cap:
        logger.debug(f"Crypto global daily cap reached: ${current_exposure:.2f} >= ${daily_cap:.2f}")
        _log_skip('daily_cap_reached')
        return

    # ── Circuit breaker gate (per-module) ────────────────────────────────────
    # Mirrors the check in crypto_threshold_daily.py step 1b.
    # Blocks new entries when consecutive losses exceed threshold.
    # DOES NOT affect exits — this function is entry-only.
    try:
        _cb_n = getattr(config, 'CRYPTO_DAILY_CIRCUIT_BREAKER_N',
                        getattr(config, 'CRYPTO_1H_CIRCUIT_BREAKER_N', 3))
        _cb_advisory = getattr(config, 'CRYPTO_DAILY_CIRCUIT_BREAKER_ADVISORY', False)
        _cb_losses = circuit_breaker.get_consecutive_losses(_ws_module)
        if _cb_losses >= _cb_n:
            if _cb_advisory:
                logger.info(
                    '[WS-CRYPTO] CB advisory: %d consecutive losses for %s (threshold=%d) — continuing',
                    _cb_losses, _ws_module, _cb_n
                )
            else:
                logger.warning(
                    '[WS-CRYPTO] CB TRIPPED: %d consecutive losses for %s (threshold=%d) — entry blocked',
                    _cb_losses, _ws_module, _cb_n
                )
                _log_skip('circuit_breaker')
                return
    except Exception as _cb_err:
        logger.warning('[WS-CRYPTO] CB gate failed for %s: %s', _ws_module, _cb_err)
    # ── End circuit breaker gate ──────────────────────────────────────────────

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
        'module': _ws_module,
        'yes_ask': yes_ask,
        'yes_bid': yes_bid,
        'current_price': current_price,
        'hours_to_settlement': hours_left,
    }

    # Compute open_position_value for strategy gate (same pattern as main.py)
    from agents.ruppert.data_scientist.capital import get_buying_power
    _total = get_capital()
    _bp = get_buying_power()
    opp['open_position_value'] = max(0.0, _total - _bp)

    # Check entry via strategy
    from agents.ruppert.strategist.strategy import should_enter, calculate_position_size
    deployed_today = get_daily_exposure()
    _module_deployed = get_daily_exposure(_ws_module)
    module_deployed_pct = _module_deployed / capital if capital > 0 else 0.0
    decision = should_enter(opp, capital, deployed_today, module=_ws_module, module_deployed_pct=module_deployed_pct, traded_tickers=None)
    if not decision['enter']:
        reason = decision['reason']
        logger.debug(f"[WS Crypto] {ticker}: entry blocked — {reason}")
        _log_skip(f'strategy_gate:{reason}')
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
        _log_skip('size_below_minimum')
        return

    # Execute trade
    from agents.ruppert.data_analyst.kalshi_client import KalshiClient
    client = KalshiClient()
    bet_price = yes_ask if side == 'yes' else (100 - yes_ask)
    contracts = max(1, int(size / (bet_price / 100)))

    print(f"  [WS Crypto Entry] {ticker} {side.upper()} | edge={edge:+.1%} | ${size:.2f}")

    _dry_run = getattr(config, 'DRY_RUN', True)
    if _dry_run:
        order_result = {'dry_run': True, 'status': 'simulated'}
    else:
        from agents.ruppert.env_config import require_live_enabled
        require_live_enabled()
        try:
            order_result = client.place_order(ticker, side, bet_price, contracts)
        except Exception as e:
            print(f"  [WS Crypto] Order failed: {e}")
            return

    from agents.ruppert.data_scientist.logger import log_trade, log_activity
    opp['action'] = 'buy'
    opp['contracts'] = contracts
    opp['size_dollars'] = size
    opp['timestamp'] = ts()
    opp['date'] = str(date.today())
    opp['scan_price'] = bet_price
    opp['fill_price'] = bet_price

    log_trade(opp, size, contracts, order_result)
    log_activity(f'[WS-CRYPTO] Entered {ticker} {side.upper()} @ {bet_price}c | edge={edge:+.1%}')
    log_event('TRADE_EXECUTED', {
        'ticker': ticker,
        'side': side,
        'size': size,
        'contracts': contracts,
        'price': bet_price,
        'dry_run': _dry_run,
    })
    push_alert('trade', f'WS Crypto Entry: {ticker} {side.upper()} @ {bet_price}c', ticker=ticker)

    # ── Track position for WS exit monitoring ──
    try:
        fill_price = bet_price
        fill_contracts = contracts
        if not _dry_run and order_result and isinstance(order_result, dict):
            fill_price = int(order_result.get('price', order_result.get('yes_price', bet_price)) or bet_price)
            fill_contracts = int(order_result.get('contracts', order_result.get('count', contracts)) or contracts)
        position_tracker.add_position(ticker, fill_contracts, side, fill_price,
                                      module=opp.get('module', 'crypto'), title=opp.get('title', ''))
    except Exception as _pt_err:
        logger.warning('[WS-CRYPTO] position_tracker.add_position failed: %s', _pt_err)

    # ── Log entry decision ──────────────────────────────────────────────────
    try:
        if strike_type in ('greater', 'less'):
            from agents.ruppert.trader.crypto_threshold_daily import _log_decision as _log_td
            _log_td(
                asset=asset, window='ws', signals={}, decision='ENTER',
                ticker=ticker, side=side, edge=round(edge, 4),
                model_prob=round(model_prob, 4), confidence=confidence,
                size_usd=round(size, 2),
                reason='ws_entry',
            )
        else:
            from agents.ruppert.trader.crypto_band_daily import _log_band_decision as _log_bd
            _log_bd(
                ticker=ticker, series=series,
                spot=current_price, band_mid=strike,
                sigma=sigma, prob_model=model_prob,
                mkt_yes=yes_ask / 100.0,
                edge_yes=round(edge, 4) if side == 'yes' else round(model_prob - yes_ask / 100.0, 4),
                edge_no=round(1.0 - model_prob - (100 - yes_ask) / 100.0, 4) if side == 'yes' else round(edge, 4),
                decision='ENTER',
                side=side, edge=round(edge, 4), confidence=confidence,
                size_usd=round(size, 2),
                hours_to_settlement=hours_left,
            )
    except Exception as _le_err:
        logger.debug('[WS-CRYPTO] entry decision log failed: %s', _le_err)
    # ── End entry decision log ────────────────────────────────────────────────


# ─────────────────── Background Task Wrappers (non-blocking) ─────────────────
# These run as asyncio.create_task() from handle_message so the main WS recv
# loop stays lightweight and always responds to server PINGs on time.

async def _safe_check_exits(ticker: str, yes_bid: int, yes_ask: int, close_time: str | None):
    """Background task: check exit triggers for tracked positions."""
    try:
        await position_tracker.check_exits(ticker, yes_bid, yes_ask, close_time=close_time)
    except Exception as e:
        logger.warning('[WS Feed] check_exits error: %s', e)


async def _safe_eval_15m(
    ticker: str, ticker_upper: str,
    yes_ask: int, yes_bid: int,
    close_time: str | None, open_time: str | None,
    book_depth_usd: float, dollar_oi: float,
):
    """Background task: REST depth enrichment + crypto_15m entry evaluation."""
    try:
        # Fetch REST orderbook if single-level depth is below liquidity floor
        if book_depth_usd < 50.0:
            try:
                loop = asyncio.get_running_loop()
                _market_stub = {'ticker': ticker}
                _enriched = await loop.run_in_executor(None, lambda: _enrich_and_compute_depth(_market_stub))
                _rest_depth = _enriched.get('_book_depth_usd', 0.0)
                if _rest_depth > book_depth_usd:
                    book_depth_usd = _rest_depth
            except Exception as _e:
                logger.debug('[WS Feed] depth enrich failed for %s: %s', ticker, _e)

        # ── Atomic window dedup guard ──
        if open_time:
            _series = next((s for s in CRYPTO_15M_SERIES if ticker_upper.startswith(s)), None)
            _open_time_norm = open_time.replace('Z', '+00:00') if open_time and open_time.endswith('Z') else open_time
            _guard_key = f"{_series}::{_open_time_norm}" if _series and _open_time_norm else None
        else:
            _guard_key = None

        async with _window_eval_lock:
            if _guard_key and _guard_key in _window_evaluated:
                return  # already evaluated this window — drop silently
            if _guard_key:
                _window_evaluated[_guard_key] = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
            # proceed with evaluation — mark is set inside the lock

        _import_ok = True
        try:
            from agents.ruppert.trader.crypto_15m import evaluate_crypto_15m_entry
        except ImportError as e:
            logger.error('[WS Feed] crypto_15m import failed — window NOT marked evaluated so REST fallback can recover: %s', e)
            _import_ok = False

        if _import_ok:
            try:
                evaluate_crypto_15m_entry(ticker, yes_ask, yes_bid, close_time, open_time, book_depth_usd, dollar_oi)
            except Exception as e:
                logger.warning('[WS Feed] 15m eval error: %s', e)
    except Exception as e:
        logger.warning('[WS Feed] _safe_eval_15m error for %s: %s', ticker, e)


async def _safe_eval_hourly(ticker: str, yes_ask: int, yes_bid: int, close_time: str | None):
    """Background task: crypto hourly band entry evaluation."""
    try:
        # push_alert() and position_tracker.add_position() are fully synchronous
        # (verified 2026-04-03) — safe to run entire function in executor.
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: evaluate_crypto_entry(ticker, yes_ask, yes_bid, close_time)
        )
    except Exception as e:
        logger.warning('[WS Feed] Crypto eval error: %s', e)


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

    # Extract close_time early — needed for settlement guard in check_exits()
    # (also used below in crypto-15m entry evaluation)
    close_time = data.get('close_time')

    # Check exit triggers for tracked positions (only when both prices are present)
    # Fires as background task to avoid blocking the event loop (PONG responses).
    if yes_bid is not None and yes_ask is not None:
        asyncio.create_task(_safe_check_exits(ticker, yes_bid, yes_ask, close_time))

    # Route crypto 15m tickers to evaluate entry (background task)
    ticker_upper = ticker.upper()
    if any(ticker_upper.startswith(s) for s in CRYPTO_15M_SERIES):
        if yes_ask is not None and yes_bid is not None:
            open_time = data.get('open_time')
            ask_size = float(data.get('yes_ask_size_fp') or 0)
            bid_size = float(data.get('yes_bid_size_fp') or 0)
            dollar_oi = float(data.get('dollar_open_interest') or 0)
            asyncio.create_task(_safe_eval_15m(
                ticker, ticker_upper, yes_ask, yes_bid, close_time, open_time,
                ask_size + bid_size, dollar_oi,
            ))

    # Route crypto hourly band tickers (elif guarantees no CRYPTO_15M_SERIES match)
    elif any(ticker_upper.startswith(p) for p in CRYPTO_HOURLY_PREFIXES):
        if yes_ask is not None and yes_bid is not None:
            asyncio.create_task(_safe_eval_hourly(ticker, yes_ask, yes_bid, close_time))


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

    loop = asyncio.get_running_loop()
    for key_str in tracked:
        ticker = key_str.split('::')[0]  # get_tracked() returns 'ticker::side' keys
        try:
            _, _, is_stale = market_cache.get_with_staleness(ticker)
            if not is_stale:
                continue
            result = await loop.run_in_executor(
                None,
                lambda t=ticker: _get_kalshi_client().get_market(t)
            )
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
                ping_interval=None,   # Kalshi sends server-side pings every 10s; client pings cause false 1011 disconnects
                ping_timeout=None,    # recv timeout below handles zombie detection
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
                last_expiry_check = time.time()
                msg_count = 0

                # START fallback task for this connection cycle
                fallback_task = asyncio.create_task(_fallback_poll_loop())

                # Bootstrap: immediately fire one REST check on reconnect
                # so any active 15m window missed during disconnect is evaluated
                # without waiting up to 60s for the first poll cycle.
                try:
                    await _check_and_fire_fallback()
                    logger.info('[WS Feed] REST bootstrap fired on reconnect')
                except Exception as _boot_err:
                    logger.warning('[WS Feed] REST bootstrap error: %s', _boot_err)

                try:
                    while True:
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=30)
                        except asyncio.TimeoutError:
                            # No message in 30s (Kalshi pings every 10s) — connection is dead
                            log_activity('[WS Feed] recv timeout (30s silence) — reconnecting')
                            break
                        try:
                            msg = json.loads(raw)
                        except json.JSONDecodeError as e:
                            logger.warning('[WS Feed] Malformed JSON message, skipping: %s', e)
                            continue
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

                        # Periodic expiry check every 60s
                        if now - last_expiry_check >= 60:
                            try:
                                await position_tracker.check_expired_positions()
                            except Exception as _exp_err:
                                logger.warning('[WS Feed] check_expired_positions error: %s', _exp_err)
                            last_expiry_check = now

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
