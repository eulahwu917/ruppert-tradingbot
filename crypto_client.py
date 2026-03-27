"""
Crypto Data Client
Fetches BTC/ETH/XRP/DOGE price signals from CoinGecko + Kraken.
Smart money signals from Polymarket data API (no key required).
Price-probability model for Kalshi price-band markets.

Author: Ruppert (AI Trading Analyst)
Updated: 2026-03-10

NOTES ON MARKET STRUCTURE:
  Kalshi crypto markets (KXBTC, KXETH etc.) are price-band contracts.
  Each event (e.g. KXBTC-26MAR1117) has:
    - ~20+ "B" band markets: YES if price lands in a specific $500 range
    - 1 top tail "T" market: YES if price is ABOVE the ceiling
    - 1 bottom tail "T" market: YES if price is BELOW the floor
  Exactly ONE market resolves YES per event.
  Settlement: CF Benchmarks Real-Time Index (RTI), average of 60s before cutoff.
  Settlement times: ~1am, ~5pm, ~11pm EDT daily.

PRICE SOURCES:
  - CoinGecko: current price + 24h change (free, no key, rate-limit ~50/min)
  - Kraken OHLC: hourly candlesticks for RSI, MA, momentum (free, no key)
  Binance geo-blocked in US — not used.
"""

import json
import requests
import statistics
import math
import time
import logging
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

try:
    from scipy.stats import t as scipy_t
    _SCIPY_AVAILABLE = True
except ImportError:
    _SCIPY_AVAILABLE = False

logger = logging.getLogger(__name__)

# ─────────────────────────────── Constants ────────────────────────────────

COINGECKO = 'https://api.coingecko.com/api/v3'
KRAKEN = 'https://api.kraken.com/0/public'
POLYMARKET_DATA = 'https://data-api.polymarket.com'
POLYMARKET_GAMMA = 'https://gamma-api.polymarket.com'
BINANCE_FUTURES = 'https://fapi.binance.com/fapi/v1'

# CoinGecko ID, Kraken pair, symbol
ASSET_CONFIG = {
    'BTC':  {'cg_id': 'bitcoin',   'kraken_pair': 'XXBTZUSD', 'band_step': 500.0,   'hourly_vol_pct': 1.0},
    'ETH':  {'cg_id': 'ethereum',  'kraken_pair': 'XETHZUSD', 'band_step': 40.0,    'hourly_vol_pct': 1.2},
    'XRP':  {'cg_id': 'ripple',    'kraken_pair': 'XXRPZUSD', 'band_step': 0.02,    'hourly_vol_pct': 1.5},
    'DOGE': {'cg_id': 'dogecoin',  'kraken_pair': 'XDGUSD',   'band_step': 0.005,   'hourly_vol_pct': 1.8},
}

# Top Polymarket crypto trader wallets (leaderboard Mar 2026)
TOP_TRADER_WALLETS = {
    '0xdE17f7144fbD0eddb2679132C10ff5e74B120988': '0xdE17f7',
    '0x1f0ebc543B2d411f66947041625c0Aa1ce61CF86': '0x1f0ebc',
    '0x95d470e8d82d3dd6a899e91e36d7cee4b2c7c38c': 'ScroogeX',
    # TODO: replace with verified Polymarket leaderboard wallets
    '0xTODO_wallet_placeholder_4': 'Trader4',
    '0xTODO_wallet_placeholder_5': 'Trader5',
    '0xTODO_wallet_placeholder_6': 'Trader6',
    '0xTODO_wallet_placeholder_7': 'Trader7',
    '0xTODO_wallet_placeholder_8': 'Trader8',
}

# Path to the auto-refreshed wallet list produced by bot/wallet_updater.py
_WALLETS_FILE = Path(__file__).parent / 'logs' / 'smart_money_wallets.json'


def _load_wallets() -> dict:
    """
    Return smart money wallets as {address: display_name}.

    Priority:
      1. logs/smart_money_wallets.json — written daily by wallet_updater.update_wallet_list()
      2. TOP_TRADER_WALLETS fallback   — hardcoded above, placeholders excluded

    The JSON stores a flat list of proxyWallet addresses; display names are
    derived from the first 8 characters of each address.
    """
    if _WALLETS_FILE.exists():
        try:
            data = json.loads(_WALLETS_FILE.read_text(encoding='utf-8'))
            raw = data.get('wallets', [])
            if raw and isinstance(raw, list):
                logger.debug(
                    '_load_wallets: loaded %d wallets from %s (updated %s)',
                    len(raw), _WALLETS_FILE.name, data.get('updated_at', 'unknown')
                )
                # Staleness check
                updated_at = data.get('updated_at', '')
                if updated_at:
                    try:
                        from datetime import datetime, timezone
                        updated_dt = datetime.fromisoformat(updated_at)
                        age_hours = (datetime.now(timezone.utc) - updated_dt).total_seconds() / 3600
                        if age_hours > 25:
                            logger.warning(
                                'smart_money: wallet list is stale (>25h), consider re-running wallet_updater'
                            )
                    except Exception:
                        pass
                return {addr: addr[:8] + '...' for addr in raw}
        except Exception as e:
            logger.warning('_load_wallets: failed to read smart_money_wallets.json: %s', e)

    # Fallback: use hardcoded list, filtering out TODO placeholders
    real_wallets = {k: v for k, v in TOP_TRADER_WALLETS.items()
                    if not k.startswith('0xTODO')}
    logger.debug('_load_wallets: using hardcoded fallback (%d wallets)', len(real_wallets))
    return real_wallets


# In-process cache (TTL: 5 min for prices, 15 min for smart money)
_CACHE: dict = {}

def _cache_get(key: str, ttl: int = 300):
    entry = _CACHE.get(key)
    if entry and (time.time() - entry['ts']) < ttl:
        return entry['data']
    return None

def _cache_set(key: str, data):
    _CACHE[key] = {'data': data, 'ts': time.time()}


# ─────────────────────────────── Funding Rates ───────────────────────────────

# Binance Futures perpetual symbols for funding rate data
# Note: public market data endpoint — no auth required, US accessible
FUNDING_SYMBOLS = {
    'BTC': 'BTCUSDT',
    'ETH': 'ETHUSDT',
    'XRP': 'XRPUSDT',
}

# Limit = 96 × 8h intervals ≈ 32 days ≈ rolling 30-day window
FUNDING_RATE_LIMIT = 96

# Contrarian z-score thresholds
FUNDING_Z_BEARISH =  2.0   # z > +2.0 → longs crowded → bearish signal
FUNDING_Z_BULLISH = -2.0   # z < -2.0 → shorts crowded → bullish signal


def get_funding_rates(symbol: str, limit: int = FUNDING_RATE_LIMIT) -> list | None:
    """
    Fetch recent funding rates for a Binance perpetual futures symbol.

    Args:
        symbol: Binance futures symbol (e.g. "BTCUSDT")
        limit:  number of funding rate records (8h each; 96 ≈ 32 days)

    Returns:
        List of funding rates as floats (most recent last), or None on failure.
    """
    cached = _cache_get(f'funding_{symbol}', ttl=3600)  # cache 1h (funding settles 8h)
    if cached is not None:
        return cached

    try:
        r = requests.get(
            f'{BINANCE_FUTURES}/fundingRate',
            params={'symbol': symbol, 'limit': limit},
            timeout=12,
        )
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, list) or not data:
            logger.warning('Binance funding rate empty response for %s', symbol)
            return None

        rates = [float(item['fundingRate']) for item in data if 'fundingRate' in item]
        _cache_set(f'funding_{symbol}', rates)
        logger.debug('Binance funding %s: %d records, latest=%.6f', symbol, len(rates), rates[-1])
        return rates

    except Exception as e:
        logger.warning('Binance funding rate fetch failed for %s: %s', symbol, e)
        return None


def _compute_funding_z_scores() -> dict:
    """
    Compute funding rate z-scores for BTC, ETH, XRP.

    z_score = (current_rate - rolling_mean) / rolling_std
    Contrarian:
      z > +2.0 → longs crowded → bearish signal
      z < -2.0 → shorts crowded → bullish signal

    Returns:
        {
          'btc': float or None,
          'eth': float or None,
          'xrp': float or None,
          'raw_rates': {symbol: latest_rate},
          'available': bool,
        }
    """
    cached = _cache_get('funding_z_scores', ttl=3600)
    if cached is not None:
        return cached

    result = {'btc': None, 'eth': None, 'xrp': None, 'raw_rates': {}, 'available': False}

    for asset, symbol in FUNDING_SYMBOLS.items():
        try:
            rates = get_funding_rates(symbol)
            if not rates or len(rates) < 10:
                logger.warning('Insufficient funding rate data for %s (%d records)', symbol, len(rates) if rates else 0)
                continue

            current_rate  = rates[-1]
            rolling_mean  = statistics.mean(rates)
            rolling_std   = statistics.stdev(rates) if len(rates) >= 2 else 0.0

            if rolling_std < 1e-10:
                z_score = 0.0  # degenerate case: no variation
            else:
                z_score = (current_rate - rolling_mean) / rolling_std

            result[asset.lower()]              = round(z_score, 3)
            result['raw_rates'][symbol]        = round(current_rate, 8)
            result['available']                = True

            logger.info(
                'Funding %s: rate=%.6f mean=%.6f std=%.6f z=%.3f',
                symbol, current_rate, rolling_mean, rolling_std, z_score
            )

        except Exception as e:
            logger.warning('Funding z-score failed for %s: %s', symbol, e)

    _cache_set('funding_z_scores', result)
    return result


# ─────────────────────────────── Stats Helpers ───────────────────────────────

def _rsi(closes: list, period: int = 14) -> float | None:
    if len(closes) < period + 2:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    avg_gain = statistics.mean(gains[:period])
    avg_loss = statistics.mean(losses[:period])
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1 + rs))


def _t_cdf(x: float, mu: float, sigma: float, df: int = 3) -> float:
    """
    CDF of Student's t-distribution (df=3 default) to capture crypto fat tails.
    Uses scipy if available; otherwise falls back to a closed-form approximation.
    """
    if sigma <= 0:
        return 1.0 if x >= mu else 0.0
    if _SCIPY_AVAILABLE:
        t_stat = (x - mu) / sigma
        return float(scipy_t.cdf(t_stat, df))
    # Closed-form approximation for df=3
    t_stat = (x - mu) / sigma
    x2 = t_stat * t_stat
    denom = 1 + x2 / 3
    p = 0.5 + t_stat * denom / (2 * math.sqrt(3) * denom ** 1.5)
    return max(0.0, min(1.0, p))


def _band_probability(low: float, high: float, mu: float, sigma: float) -> float:
    """P(low ≤ price < high) under Student's t-distribution (df=3)."""
    return _t_cdf(high, mu, sigma) - _t_cdf(low, mu, sigma)


# ─────────────────────────────── Kraken OHLC ─────────────────────────────────

def _kraken_ohlc(pair: str, interval_min: int = 60, count: int = 50) -> list | None:
    """
    Fetch OHLC candles from Kraken.
    Returns list of [time, open, high, low, close, vwap, volume, count] or None.
    """
    cached = _cache_get(f'kraken_{pair}_{interval_min}', ttl=300)
    if cached:
        return cached
    try:
        r = requests.get(f'{KRAKEN}/OHLC',
                         params={'pair': pair, 'interval': interval_min},
                         timeout=15)
        data = r.json()
        if data.get('error'):
            logger.warning('Kraken OHLC error %s: %s', pair, data['error'])
            return None
        result = data.get('result', {})
        key = next((k for k in result if k != 'last'), None)
        if not key:
            return None
        candles = result[key][-count:]
        _cache_set(f'kraken_{pair}_{interval_min}', candles)
        return candles
    except Exception as e:
        logger.warning('Kraken OHLC fetch failed for %s: %s', pair, e)
        return None


# ─────────────────────────────── Price Signal ────────────────────────────────

def _build_signal(symbol: str) -> dict:
    """
    Core signal builder for one asset.
    Returns full signal dict.
    """
    cfg = ASSET_CONFIG[symbol]

    # ── Current price: CoinGecko primary, Kraken fallback
    current_price = 0.0
    change_24h = 0.0
    try:
        r = requests.get(f'{COINGECKO}/simple/price',
                         params={'ids': cfg['cg_id'], 'vs_currencies': 'usd',
                                 'include_24hr_change': 'true'},
                         timeout=12)
        cg = r.json().get(cfg['cg_id'], {})
        current_price = float(cg.get('usd') or 0)
        change_24h = float(cg.get('usd_24h_change') or 0)
    except Exception:
        pass

    # Kraken fallback if CoinGecko rate-limited or returned zero
    if current_price <= 0:
        try:
            r2 = requests.get(f'{KRAKEN}/Ticker',
                              params={'pair': cfg['kraken_pair']}, timeout=10)
            kr = r2.json()
            if not kr.get('error'):
                key = next(iter(kr.get('result', {})), None)
                if key:
                    current_price = float(kr['result'][key]['c'][0])
        except Exception as e:
            pass

    if current_price <= 0:
        raise ValueError(f'Could not fetch price for {symbol} from CoinGecko or Kraken')

    # ── Candles from Kraken: 1h, 4h, daily
    candles_1h = _kraken_ohlc(cfg['kraken_pair'], 60, 50)
    candles_4h = _kraken_ohlc(cfg['kraken_pair'], 240, 30)
    candles_1d = _kraken_ohlc(cfg['kraken_pair'], 1440, 8)

    change_1h = change_4h = rsi = rsi_4h = ma20 = above_ma = trend_7d = None

    if candles_1h and len(candles_1h) >= 10:
        closes = [float(c[4]) for c in candles_1h]
        change_1h = (closes[-1] - closes[-2]) / closes[-2] * 100 if len(closes) >= 2 else 0.0
        change_4h = (closes[-1] - closes[-5]) / closes[-5] * 100 if len(closes) >= 5 else 0.0
        rsi = _rsi(closes, 14)
        if len(closes) >= 20:
            ma20 = statistics.mean(closes[-20:])
            above_ma = current_price > ma20

    # 4h RSI for multi-timeframe confirmation
    if candles_4h and len(candles_4h) >= 16:
        closes_4h = [float(c[4]) for c in candles_4h]
        rsi_4h = _rsi(closes_4h, 14)

    if candles_1d and len(candles_1d) >= 2:
        daily_closes = [float(c[4]) for c in candles_1d]
        trend_7d = (daily_closes[-1] - daily_closes[0]) / daily_closes[0] * 100

    # ── Magnitude-weighted momentum scoring
    # Returns accumulated bull_score / bear_score (float, threshold ≥ 3.5)
    bull_score = 0.0
    bear_score = 0.0

    # 1h change  — thresholds: 0-0.5% = ±0.5 | 0.5-2% = ±1.0 | 2%+ = ±1.5
    c1 = abs(change_1h or 0)
    pts_1h = 0.5 if c1 < 0.5 else (1.0 if c1 < 2.0 else 1.5)
    if (change_1h or 0) > 0:
        bull_score += pts_1h
    elif (change_1h or 0) < 0:
        bear_score += pts_1h

    # 4h change  — thresholds: 0-1% = ±0.5 | 1-3% = ±1.0 | 3%+ = ±1.5
    c4 = abs(change_4h or 0)
    pts_4h = 0.5 if c4 < 1.0 else (1.0 if c4 < 3.0 else 1.5)
    if (change_4h or 0) > 0:
        bull_score += pts_4h
    elif (change_4h or 0) < 0:
        bear_score += pts_4h

    # 24h change — thresholds: 0-2% = ±0.5 | 2-5% = ±1.0 | 5%+ = ±1.5
    c24 = abs(change_24h or 0)
    pts_24h = 0.5 if c24 < 2.0 else (1.0 if c24 < 5.0 else 1.5)
    if change_24h > 0:
        bull_score += pts_24h
    elif change_24h < 0:
        bear_score += pts_24h

    # MA — binary ±1.0
    if above_ma is True:
        bull_score += 1.0
    elif above_ma is False:
        bear_score += 1.0

    # Multi-timeframe RSI scoring
    rsi_overbought = rsi is not None and rsi > 70
    rsi_oversold   = rsi is not None and rsi < 30
    rsi_4h_overbought = rsi_4h is not None and rsi_4h > 70
    rsi_4h_oversold   = rsi_4h is not None and rsi_4h < 30

    if rsi_overbought and rsi_4h_overbought:
        bear_score += 1.5   # both timeframes overbought → strong bear signal
    elif rsi_overbought:
        bear_score += 0.75  # only 1h overbought → mild bear
    if rsi_oversold and rsi_4h_oversold:
        bull_score += 1.5   # both timeframes oversold → strong bull signal
    elif rsi_oversold:
        bull_score += 0.75  # only 1h oversold → mild bull

    # Legacy integer counts for backwards-compatible fields
    bull_count = int(bull_score)
    bear_count = int(bear_score)

    SIGNAL_THRESHOLD = 3.5
    if bull_score >= SIGNAL_THRESHOLD and bull_score > bear_score:
        direction = 'BULLISH'
    elif bear_score >= SIGNAL_THRESHOLD and bear_score > bull_score:
        direction = 'BEARISH'
    else:
        direction = 'NEUTRAL'

    # ── Funding rate z-score signal
    funding_z_scores = _compute_funding_z_scores()
    asset_key        = symbol.lower()  # 'btc', 'eth', 'xrp', 'doge'
    funding_z        = funding_z_scores.get(asset_key)  # None for DOGE (not tracked)
    funding_signal   = {
        'btc': funding_z_scores.get('btc'),
        'eth': funding_z_scores.get('eth'),
        'xrp': funding_z_scores.get('xrp'),
        'available': funding_z_scores.get('available', False),
    }

    return {
        'symbol': symbol,
        'price': current_price,
        'change_1h': change_1h,
        'change_4h': change_4h,
        'change_24h': change_24h,
        'rsi': rsi,
        'rsi_4h': rsi_4h,
        'ma20': ma20,
        'above_ma': above_ma,
        'trend_7d': trend_7d,
        'direction': direction,
        'bull_score': round(bull_score, 2),
        'bear_score': round(bear_score, 2),
        'bull_signals': bull_count,
        'bear_signals': bear_count,
        'hourly_vol_pct': cfg['hourly_vol_pct'],
        'funding_z': funding_z,        # this asset's z-score (or None if unavailable)
        'funding_signal': funding_signal,  # all tracked assets
        'fetched_at': datetime.now(timezone.utc).isoformat(),
    }


def get_realized_vol(symbol: str, lookback_hours: int = 24) -> float:
    """
    Compute realized hourly vol (as % of price, annualized to per-hour basis)
    from Kraken OHLC data. Used to calibrate sigma for edge calculation.
    Returns hourly vol as a fraction (e.g., 0.007 = 0.7%/h).
    """
    cached = _cache_get(f'rvol_{symbol}', ttl=1800)
    if cached is not None:
        return cached

    cfg = ASSET_CONFIG[symbol]
    candles = _kraken_ohlc(cfg['kraken_pair'], 60, lookback_hours + 2)
    if not candles or len(candles) < 4:
        return cfg['hourly_vol_pct'] / 100  # fallback

    closes = [float(c[4]) for c in candles]
    log_returns = [math.log(closes[i] / closes[i-1]) for i in range(1, len(closes))]
    if len(log_returns) < 3:
        return cfg['hourly_vol_pct'] / 100

    # EWMA volatility (λ=0.94) — gives more weight to recent returns,
    # better suited to crypto's regime-switching behaviour than equal-weight stdev.
    LAMBDA = 0.94
    variance = log_returns[0] ** 2
    for r in log_returns[1:]:
        variance = LAMBDA * variance + (1 - LAMBDA) * r ** 2
    vol = math.sqrt(variance)
    _cache_set(f'rvol_{symbol}', vol)
    return vol


def get_btc_signal() -> dict:
    """
    Returns BTC price signal with momentum indicators.
    {price, change_1h, change_4h, change_24h, rsi, ma20, above_ma,
     trend_7d, direction (BULLISH/BEARISH/NEUTRAL), bull_signals, bear_signals,
      realized_hourly_vol}
    """
    cached = _cache_get('signal_BTC', ttl=300)
    if cached:
        return cached
    sig = _build_signal('BTC')
    sig['realized_hourly_vol'] = get_realized_vol('BTC')
    _cache_set('signal_BTC', sig)
    return sig


def get_eth_signal() -> dict:
    """Same as get_btc_signal() but for ETH."""
    cached = _cache_get('signal_ETH', ttl=300)
    if cached:
        return cached
    sig = _build_signal('ETH')
    sig['realized_hourly_vol'] = get_realized_vol('ETH')
    _cache_set('signal_ETH', sig)
    return sig


def get_xrp_signal() -> dict:
    """Same for XRP."""
    cached = _cache_get('signal_XRP', ttl=300)
    if cached:
        return cached
    sig = _build_signal('XRP')
    sig['realized_hourly_vol'] = get_realized_vol('XRP')
    _cache_set('signal_XRP', sig)
    return sig


def get_doge_signal() -> dict:
    """Same for DOGE."""
    cached = _cache_get('signal_DOGE', ttl=300)
    if cached:
        return cached
    sig = _build_signal('DOGE')
    sig['realized_hourly_vol'] = get_realized_vol('DOGE')
    _cache_set('signal_DOGE', sig)
    return sig


# ─────────────────────────────── Smart Money ─────────────────────────────────

def _resolve_condition_to_market(condition_id: str) -> dict | None:
    """Look up Polymarket market by conditionId to get title and category."""
    try:
        r = requests.get(f'{POLYMARKET_GAMMA}/markets',
                         params={'conditionId': condition_id}, timeout=10)
        if r.status_code == 200:
            mkts = r.json()
            if isinstance(mkts, list) and mkts:
                return mkts[0]
    except Exception:
        pass
    return None


def _classify_crypto_direction(question: str, outcome: str) -> tuple[str | None, str]:
    """
    Map a (question, outcome) pair to (asset, direction).
    Returns (asset, 'BULLISH'|'BEARISH'|'UNKNOWN') or (None, 'N/A').
    """
    q = question.lower()
    o = outcome.lower()

    asset = None
    if 'bitcoin' in q or ' btc' in q:
        asset = 'BTC'
    elif 'ethereum' in q or ' eth' in q:
        asset = 'ETH'
    elif 'solana' in q or ' sol' in q:
        asset = 'SOL'
    elif 'ripple' in q or ' xrp' in q:
        asset = 'XRP'

    if not asset:
        return None, 'N/A'

    # Positive outcomes on bullish framing → BULLISH
    bullish_q_words = ('above', 'over', 'high', 'hit', 'reach', 'break', 'up', 'bull', 'gain')
    bearish_q_words = ('below', 'under', 'low', 'fall', 'drop', 'down', 'bear', 'crash')
    positive_o = o in ('yes', 'up', 'higher', 'above')
    negative_o = o in ('no', 'down', 'lower', 'below')

    q_bull = any(w in q for w in bullish_q_words)
    q_bear = any(w in q for w in bearish_q_words)

    if positive_o and q_bull:
        direction = 'BULLISH'
    elif positive_o and q_bear:
        direction = 'BEARISH'
    elif negative_o and q_bull:
        direction = 'BEARISH'
    elif negative_o and q_bear:
        direction = 'BULLISH'
    else:
        direction = 'UNKNOWN'

    return asset, direction


def get_polymarket_smart_money(wallets: dict | None = None) -> dict:
    """
    Fetch open positions from top Polymarket crypto traders and aggregate direction.

    Args:
        wallets: dict of {wallet_address: display_name} (defaults to TOP_TRADER_WALLETS)

    Returns:
        {
          'BTC': {'direction': 'BULLISH'|'BEARISH'|'NEUTRAL', 'bull': N, 'bear': N, 'traders': N},
          'ETH': {...},
          'available': True|False,
          'reason': 'ok' | 'no_positions' | 'api_error',
          'raw_signals': [...]
        }
    """
    if wallets is None:
        wallets = _load_wallets()

    cached = _cache_get('smart_money', ttl=900)
    if cached:
        return cached

    raw_signals = []
    errors = []

    for wallet, name in wallets.items():
        try:
            r = requests.get(f'{POLYMARKET_DATA}/positions',
                             params={'user': wallet}, timeout=15)
            if r.status_code != 200:
                errors.append(f'{name}: HTTP {r.status_code}')
                continue

            positions = r.json()
            if not isinstance(positions, list):
                continue

            for pos in positions:
                size = float(pos.get('size') or 0)
                if size < 5:  # skip dust
                    continue
                condition_id = pos.get('conditionId', '')
                outcome = pos.get('outcome', '') or ''

                # Resolve conditionId to market question
                mkt = _resolve_condition_to_market(condition_id)
                if not mkt:
                    continue
                question = mkt.get('question', '')
                asset, direction = _classify_crypto_direction(question, outcome)

                if asset and direction not in ('UNKNOWN', 'N/A'):
                    raw_signals.append({
                        'trader': name,
                        'wallet': wallet[:12] + '...',
                        'asset': asset,
                        'direction': direction,
                        'size_usd': size,
                        'question': question[:60],
                    })

            time.sleep(0.3)

        except Exception as e:
            errors.append(f'{name}: {e}')

    # Aggregate per asset — weighted by position size (USD) rather than wallet count
    def _agg(asset):
        sigs = [s for s in raw_signals if s['asset'] == asset]
        bull = sum(1 for s in sigs if s['direction'] == 'BULLISH')
        bear = sum(1 for s in sigs if s['direction'] == 'BEARISH')
        total = bull + bear
        bull_weight = sum(s['size_usd'] for s in sigs if s['direction'] == 'BULLISH')
        bear_weight = sum(s['size_usd'] for s in sigs if s['direction'] == 'BEARISH')
        combined = bull_weight + bear_weight
        if combined == 0:
            return {'direction': 'NEUTRAL', 'bull': 0, 'bear': 0, 'traders': 0,
                    'bull_usd': 0.0, 'bear_usd': 0.0}
        ratio = bull_weight / combined
        if ratio >= 0.70:
            d = 'STRONG_BULL'
        elif ratio >= 0.55:
            d = 'MILD_BULL'
        elif ratio <= 0.30:
            d = 'STRONG_BEAR'
        elif ratio <= 0.45:
            d = 'MILD_BEAR'
        else:
            d = 'NEUTRAL'
        return {
            'direction': d,
            'bull': bull,
            'bear': bear,
            'traders': total,
            'bull_usd': round(bull_weight, 2),
            'bear_usd': round(bear_weight, 2),
        }

    result = {
        'BTC': _agg('BTC'),
        'ETH': _agg('ETH'),
        'XRP': _agg('XRP'),
        'available': len(raw_signals) > 0,
        'reason': 'ok' if raw_signals else ('no_positions' if not errors else 'api_error'),
        'raw_signals': raw_signals,
        'errors': errors,
        'tracked_wallets': len(wallets),
        'wallet_source': 'dynamic' if _WALLETS_FILE.exists() else 'hardcoded_fallback',
    }

    _cache_set('smart_money', result)
    return result


# ─────────────────────────────── Edge Calculator ─────────────────────────────

def _parse_ticker_band(ticker: str) -> tuple[str, float | None, str]:
    """
    Parse ticker like KXBTC-26MAR1117-B71250 or KXBTC-26MAR1117-T79999.99

    Returns:
        (asset, strike, market_type)
        market_type: 'B' (price band), 'T_top' (above tail), 'T_bot' (below tail)

    The 'T' markets come in pairs:
        - T{high} e.g. T79999.99 → above tail (usually the largest strike)
        - T{low}  e.g. T61000    → below tail (usually the smallest strike)
    We disambiguate by checking which is higher.
    """
    parts = ticker.split('-')
    if len(parts) < 3:
        return '', None, 'UNKNOWN'

    # Asset
    series = parts[0]
    if 'BTC' in series:
        asset = 'BTC'
    elif 'ETH' in series:
        asset = 'ETH'
    elif 'XRP' in series:
        asset = 'XRP'
    elif 'DOGE' in series:
        asset = 'DOGE'
    else:
        asset = series

    strike_str = parts[-1]
    if strike_str.startswith('B'):
        return asset, float(strike_str[1:]), 'B'
    elif strike_str.startswith('T'):
        strike = float(strike_str[1:])
        # We'll classify T_top vs T_bot in the edge function using context
        return asset, strike, 'T'

    return asset, None, 'UNKNOWN'


def _hours_to_settlement(close_time_str: str) -> float:
    """Hours from now to market close time."""
    try:
        close_dt = datetime.fromisoformat(close_time_str.replace('Z', '+00:00'))
        now = datetime.now(timezone.utc)
        delta = (close_dt - now).total_seconds()
        return max(delta / 3600, 0.05)  # never less than 3 min
    except Exception:
        return 6.0  # fallback


def get_crypto_edge(market: dict, all_event_markets: list | None = None) -> dict | None:
    """
    Compute model probability and edge for a Kalshi crypto price-band market.

    Market structure confirmed:
      - B{mid} markets: YES if price ∈ [floor_strike, cap_strike]  (price band)
      - T{high} market: YES if price ≥ floor_strike  (top tail, e.g. "above $80K")
      - T{low}  market: YES if price ≤ cap_strike    (bottom tail, e.g. "below $61K")
      Band bounds come directly from market.floor_strike / market.cap_strike.

    Liquidity filter: require yes_bid > 0 AND bid-ask spread ≤ 30 cents.
    Market probability: use midpoint of bid-ask.

    Returns:
        edge dict or None if filtered out.
    """
    ticker = market.get('ticker', '')
    yes_ask = market.get('yes_ask')
    yes_bid = market.get('yes_bid', 0)
    volume = market.get('volume', 0)
    close_time = market.get('close_time', '')
    title = market.get('title', '')
    # BTC/ETH have flat floor_strike/cap_strike; XRP/DOGE use custom_strike sub-dict
    custom = market.get('custom_strike', {}) or {}
    floor_strike = market.get('floor_strike') or custom.get('floor_strike')
    cap_strike = market.get('cap_strike') or custom.get('cap_strike')
    # strike_type may be at top level OR inside custom_strike
    strike_type = market.get('strike_type', '') or custom.get('strike_type', '')
    open_interest = market.get('open_interest', 0)

    if yes_ask is None or yes_ask <= 0:
        return None

    # ── Liquidity filter: require real two-sided market
    spread = yes_ask - yes_bid
    if yes_bid == 0 and yes_ask >= 95:
        return None  # phantom ask, no real market
    if yes_bid == 0 and volume == 0:
        return None  # no activity at all
    if spread > 30 and yes_bid == 0:
        return None  # stale ask

    asset, strike_from_ticker, mtype = _parse_ticker_band(ticker)
    if mtype == 'UNKNOWN':
        return None
    if asset not in ASSET_CONFIG:
        return None

    # ── Get price signal (cached)
    try:
        signal_fn = {'BTC': get_btc_signal, 'ETH': get_eth_signal,
                     'XRP': get_xrp_signal, 'DOGE': get_doge_signal}
        signal = signal_fn[asset]()
    except Exception as e:
        logger.warning('Signal fetch failed for %s: %s', asset, e)
        return None

    current_price = signal['price']
    hours_left = _hours_to_settlement(close_time)

    # ── Settlement distribution: use realized vol (fallback to config default)
    realized_vol = signal.get('realized_hourly_vol') or (ASSET_CONFIG[asset]['hourly_vol_pct'] / 100)
    sigma = current_price * realized_vol * math.sqrt(max(hours_left, 0.1))

    # Momentum-adjusted drift
    direction = signal.get('direction', 'NEUTRAL')
    momentum_shift = 0.0
    if direction == 'BULLISH':
        momentum_shift = sigma * 0.08
    elif direction == 'BEARISH':
        momentum_shift = -sigma * 0.08
    mu = current_price + momentum_shift

    # ── Market probability: use midpoint when bid exists, else ask (conservative)
    if yes_bid > 0:
        market_prob = ((yes_ask + yes_bid) / 2) / 100.0
    else:
        market_prob = yes_ask / 100.0

    # ── Model probability based on strike_type / market structure
    if strike_type == 'between' and floor_strike is not None and cap_strike is not None:
        # Band market: YES if floor_strike ≤ price ≤ cap_strike
        try:
            low = float(floor_strike)
            high = float(cap_strike)
        except (TypeError, ValueError):
            low = high = 0.0
        model_prob = _band_probability(low, high, mu, sigma)
        reasoning_prefix = (f'Band [{low:g}, {high:g}] | '
                            f'price={current_price:g} | '
                            f'dist={abs((low+high)/2 - current_price):g}')

    elif strike_type in ('greater', 'above') and floor_strike is not None:
        # Top tail: YES if price > floor_strike
        try:
            fs = float(floor_strike)
        except (TypeError, ValueError):
            fs = mu
        model_prob = 1.0 - _t_cdf(fs, mu, sigma)
        reasoning_prefix = f'Top-tail (above {fs:g})'

    elif strike_type in ('less', 'below') and cap_strike is not None:
        # Bottom tail: YES if price < cap_strike
        try:
            cs = float(cap_strike)
        except (TypeError, ValueError):
            cs = mu
        model_prob = _t_cdf(cs, mu, sigma)
        reasoning_prefix = f'Bot-tail (below {cs:g})'

    elif mtype == 'T':
        # Fallback for T markets without strike_type info
        strike = strike_from_ticker or 0
        if strike > current_price * 1.02:
            model_prob = 1.0 - _t_cdf(strike, mu, sigma)
            reasoning_prefix = f'Top-tail (above {strike:g})'
        else:
            model_prob = _t_cdf(strike, mu, sigma)
            reasoning_prefix = f'Bot-tail (below {strike:g})'
    else:
        # B market fallback using band_step
        band_step = ASSET_CONFIG[asset]['band_step']
        strike = strike_from_ticker or 0
        low = strike - band_step / 2
        high = strike + band_step / 2
        model_prob = _band_probability(low, high, mu, sigma)
        reasoning_prefix = f'Band [{low:g}, {high:g}] (inferred)'

    # ── Edge
    edge = model_prob - market_prob

    # ── Confidence
    # sigma_dist: how many sigmas from current price to band center
    if floor_strike is not None and cap_strike is not None:
        band_center = (float(floor_strike) + float(cap_strike)) / 2
    else:
        band_center = strike_from_ticker or current_price
    sigma_dist = abs(band_center - current_price) / sigma if sigma > 0 else 99

    has_strong_momentum = signal.get('bull_signals', 0) >= 4 or signal.get('bear_signals', 0) >= 4
    has_rsi = signal.get('rsi') is not None

    if sigma_dist < 1.0 and has_strong_momentum and abs(edge) >= 0.15:
        confidence = 'high'
    elif sigma_dist < 1.5 and has_rsi and abs(edge) >= 0.10:
        confidence = 'medium'
    elif sigma_dist < 2.0 and abs(edge) >= 0.10:
        confidence = 'low'
    else:
        confidence = 'low'

    # ── Funding rate confidence modifier (±5%)
    # Contrarian: extreme positive z (longs crowded) → bearish → lower confidence
    #             extreme negative z (shorts crowded) → bullish → raise confidence
    # Applied as a numeric modifier then converted back to string tier.
    _conf_map    = {'low': 0.50, 'medium': 0.65, 'high': 0.80}
    _conf_num    = _conf_map.get(confidence, 0.50)
    funding_z    = signal.get('funding_z')
    funding_conf_adj = 0.0

    if funding_z is not None:
        if funding_z > FUNDING_Z_BEARISH:
            funding_conf_adj = -0.05  # bearish pressure → lower confidence
        elif funding_z < FUNDING_Z_BULLISH:
            funding_conf_adj = +0.05  # bullish pressure → raise confidence

    _conf_num = max(0.0, min(1.0, _conf_num + funding_conf_adj))

    # Re-map numeric back to string tier
    if _conf_num >= 0.72:
        confidence = 'high'
    elif _conf_num >= 0.57:
        confidence = 'medium'
    else:
        confidence = 'low'

    if funding_conf_adj != 0.0:
        logger.info(
            'Funding z=%.3f → confidence_adj=%+.2f → confidence=%s (asset=%s)',
            funding_z, funding_conf_adj, confidence, asset
        )

    # ── Smart money boost
    smart_money = get_polymarket_smart_money()
    sm_asset = smart_money.get(asset, {})
    sm_dir = sm_asset.get('direction', 'NEUTRAL')

    if sm_dir in ('STRONG_BULL', 'MILD_BULL') and direction == 'BULLISH':
        if confidence == 'medium':
            confidence = 'high'
    elif sm_dir in ('STRONG_BEAR', 'MILD_BEAR') and direction == 'BEARISH':
        if confidence == 'medium':
            confidence = 'high'

    # ── Trade direction
    trade_direction = 'YES' if edge > 0 else 'NO'

    # ── Reasoning
    rsi_str = f'{signal["rsi"]:.0f}' if signal.get('rsi') else 'N/A'
    ma_str = ('above 20h MA' if signal.get('above_ma') is True else
              'below 20h MA' if signal.get('above_ma') is False else '')
    reasoning = (
        f'{reasoning_prefix} | '
        f'price={current_price:g}, vol={sigma:.2f} over {hours_left:.1f}h | '
        f'model={model_prob:.1%} vs market={market_prob:.1%} => edge={edge:+.1%} | '
        f'momentum={direction}, RSI={rsi_str} {ma_str} | '
        f'smart_money={sm_dir}'
    )

    return {
        'ticker': ticker,
        'title': title,
        'asset': asset,
        'strike': strike_from_ticker,
        'floor_strike': floor_strike,
        'cap_strike': cap_strike,
        'market_type': strike_type or mtype,
        'market_prob': round(market_prob, 4),
        'model_prob': round(model_prob, 4),
        'edge': round(edge, 4),
        'direction': trade_direction,
        'confidence': confidence,
        'confidence_score': round(_conf_num, 3),
        'funding_z': funding_z,
        'funding_conf_adj': round(funding_conf_adj, 3),
        'funding_signal': signal.get('funding_signal', {}),
        'hours_to_settlement': round(hours_left, 2),
        'sigma': round(sigma, 4),
        'current_price': current_price,
        'momentum': direction,
        'rsi': signal.get('rsi'),
        'yes_ask': yes_ask,
        'yes_bid': yes_bid,
        'spread': spread,
        'volume': volume,
        'open_interest': open_interest,
        'reasoning': reasoning,
        'signal': signal,
        'smart_money': sm_asset,
    }


# ─────────────────────────────── Self-test ───────────────────────────────────

if __name__ == '__main__':
    import json

    print('=== Crypto Client Self-Test ===\n')

    print('[1] BTC signal:')
    btc = get_btc_signal()
    print(f'  Price:     ${btc["price"]:,.2f}')
    print(f'  Direction: {btc["direction"]} ({btc["bull_signals"]} bull / {btc["bear_signals"]} bear)')
    print(f'  RSI:       {btc["rsi"]:.1f}' if btc.get('rsi') else '  RSI: N/A')
    print(f'  24h chg:   {btc["change_24h"]:+.2f}%' if btc.get('change_24h') else '')

    print('\n[2] ETH signal:')
    eth = get_eth_signal()
    print(f'  Price:     ${eth["price"]:,.2f}')
    print(f'  Direction: {eth["direction"]}')

    print('\n[3] XRP signal:')
    xrp = get_xrp_signal()
    print(f'  Price:     ${xrp["price"]:,.4f}')
    print(f'  Direction: {xrp["direction"]}')

    print('\n[4] Smart money:')
    sm = get_polymarket_smart_money()
    print(f'  Available: {sm["available"]}')
    print(f'  BTC: {sm["BTC"]["direction"]} ({sm["BTC"]["bull"]} bull / {sm["BTC"]["bear"]} bear)')
    print(f'  ETH: {sm["ETH"]["direction"]}')

    print('\n[5] Sample edge calculation (mock market):')
    sample_market = {
        'ticker': 'KXBTC-26MAR1117-B70250',
        'title': 'Bitcoin price range on Mar 11, 2026?',
        'yes_ask': 15,
        'volume': 200,
        'close_time': '2026-03-11T21:00:00Z',
    }
    edge_result = get_crypto_edge(sample_market)
    if edge_result:
        print(f'  Edge: {edge_result["edge"]:+.1%} | confidence={edge_result["confidence"]}')
        print(f'  Reasoning: {edge_result["reasoning"][:100]}...')
    else:
        print('  No edge (market filtered out)')

    print('\nSelf-test complete.')
