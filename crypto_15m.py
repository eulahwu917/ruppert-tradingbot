"""
crypto_15m.py — 15-Minute Crypto Binary Direction Algorithm

Handles Kalshi 15-min binary crypto direction series:
  KXBTC15M, KXETH15M, KXXRP15M, KXDOGE15M

These are YES/NO markets: "Will price be up in the next 15 mins?"
Settlement: YES if close_price > open_price (Coinbase reference).

Signal stack:
  1. Taker Flow Imbalance (TFI)    — weight 0.40
  2. Orderbook Imbalance (OBI)     — weight 0.25
  3. MACD Histogram (5m candles)   — weight 0.15
  4. Open Interest Delta           — weight 0.10

Bias filters: Funding rate z-score, Polymarket divergence (additive nudge).

Author: Ruppert (AI Trading Analyst)
Created: 2026-03-28
"""

import json
import math
import time
import logging
import statistics
import requests
import uuid
from collections import deque
from datetime import datetime, timezone, date, timedelta
import pytz
from pathlib import Path

import config

logger = logging.getLogger(__name__)

# ─────────────────────────────── Constants ────────────────────────────────────

BINANCE_FUTURES = 'https://fapi.binance.com/fapi/v1'
BINANCE_DATA    = 'https://fapi.binance.com/futures/data'
COINBASE_API    = 'https://api.coinbase.com/v2/prices'

CRYPTO_15M_SERIES = ['KXBTC15M', 'KXETH15M', 'KXXRP15M', 'KXDOGE15M']

ASSET_SYMBOLS = {
    'BTC':  'BTCUSDT',
    'ETH':  'ETHUSDT',
    'XRP':  'XRPUSDT',
    'DOGE': 'DOGEUSDT',
}

# Signal weights (fixed — autoresearcher will optimize)
W_TFI  = 0.40
W_OBI  = 0.25
W_MACD = 0.15
W_OI   = 0.10

LOGS_DIR = Path(__file__).parent / 'logs'
LOGS_DIR.mkdir(exist_ok=True)
DECISION_LOG = LOGS_DIR / 'decisions_15m.jsonl'

DRY_RUN = getattr(config, 'DRY_RUN', True)

# ─────────────────────────────── Cache ────────────────────────────────────────

_CACHE: dict = {}
_CACHE_MISS = object()


def _cache_get(key: str, ttl: int = 300):
    entry = _CACHE.get(key)
    if entry and (time.time() - entry['ts']) < ttl:
        return entry['data']
    return _CACHE_MISS


def _cache_set(key: str, data):
    _CACHE[key] = {'data': data, 'ts': time.time()}


# ─────────────────────────────── Rolling Window ──────────────────────────────

# 4H rolling windows for z-score computation (48 x 5-min buckets)
_rolling_tfi:  dict[str, deque] = {}   # per-symbol
_rolling_obi:  dict[str, deque] = {}
_rolling_macd: dict[str, deque] = {}
_rolling_oi:   dict[str, deque] = {}

ROLLING_WINDOW = 48  # 4 hours of 5-min buckets


def _z_score(value: float, window: deque, clip_lo: float = -3.0, clip_hi: float = 3.0) -> float:
    """Z-score against rolling window, clipped."""
    if len(window) < 5:
        return 0.0
    mu = statistics.mean(window)
    sd = statistics.stdev(window) if len(window) >= 2 else 1.0
    if sd < 1e-10:
        return 0.0
    z = (value - mu) / sd
    return max(clip_lo, min(clip_hi, z))


def _update_rolling(store: dict, symbol: str, value: float):
    """Append value to per-symbol rolling deque."""
    if symbol not in store:
        store[symbol] = deque(maxlen=ROLLING_WINDOW)
    store[symbol].append(value)


# ─────────────────────────────── Signal 1: TFI ───────────────────────────────

def fetch_taker_flow_imbalance(symbol: str) -> dict:
    """
    Fetch Taker Buy/Sell Volume from Binance Futures.
    Returns {'tfi_z': float, 'stale': bool, 'raw': float, 'ts': float}
    """
    try:
        r = requests.get(
            f'{BINANCE_FUTURES}/takeLongShortRatio',
            params={'symbol': symbol, 'period': '5m', 'limit': 3},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        logger.warning('TFI fetch failed for %s: %s', symbol, e)
        return {'tfi_z': 0.0, 'stale': True, 'raw': 0.0, 'ts': 0.0}

    if not data or len(data) < 1:
        return {'tfi_z': 0.0, 'stale': True, 'raw': 0.0, 'ts': 0.0}

    # Compute per-bucket TFI and time-weighted composite
    weights = [0.20, 0.30, 0.50]
    buckets = []
    last_ts = 0

    for item in data[-3:]:
        buy_vol = float(item.get('buyVol', item.get('buySellRatio', 1.0)))
        sell_vol = float(item.get('sellVol', 1.0))
        total = buy_vol + sell_vol
        tfi = (buy_vol - sell_vol) / total if total > 0 else 0.0
        buckets.append(tfi)
        last_ts = max(last_ts, float(item.get('timestamp', 0)) / 1000)

    # Pad if fewer than 3 buckets
    while len(buckets) < 3:
        buckets.insert(0, 0.0)

    tfi_composite = sum(w * t for w, t in zip(weights, buckets[-3:]))

    # Update rolling window and compute z-score
    _update_rolling(_rolling_tfi, symbol, tfi_composite)
    tfi_z = _z_score(tfi_composite, _rolling_tfi.get(symbol, deque()))

    age = time.time() - last_ts if last_ts > 0 else 999
    return {'tfi_z': round(tfi_z, 4), 'stale': age > 90, 'raw': round(tfi_composite, 6), 'ts': last_ts}


# ─────────────────────────────── Signal 2: OBI ───────────────────────────────

_obi_snapshots: dict[str, deque] = {}  # EWM history per symbol


def fetch_orderbook_imbalance(symbol: str) -> dict:
    """
    Fetch orderbook depth from Binance Futures.
    Returns {'obi_z': float, 'stale': bool, 'raw': float, 'ts': float}
    """
    try:
        r = requests.get(
            f'{BINANCE_FUTURES}/depth',
            params={'symbol': symbol, 'limit': 20},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        logger.warning('OBI fetch failed for %s: %s', symbol, e)
        return {'obi_z': 0.0, 'stale': True, 'raw': 0.0, 'ts': 0.0}

    bids = data.get('bids', [])[:10]
    asks = data.get('asks', [])[:10]

    if not bids or not asks:
        return {'obi_z': 0.0, 'stale': True, 'raw': 0.0, 'ts': 0.0}

    bid_qty = sum(float(b[1]) for b in bids)
    ask_qty = sum(float(a[1]) for a in asks)
    total = bid_qty + ask_qty

    obi_instant = (bid_qty - ask_qty) / total if total > 0 else 0.0

    # EWM approximation: exponentially weighted moving average
    if symbol not in _obi_snapshots:
        _obi_snapshots[symbol] = deque(maxlen=120)  # ~2 min of snapshots at 1/sec
    _obi_snapshots[symbol].append(obi_instant)

    # Simple EWM with span=60 (alpha = 2/(60+1))
    alpha = 2.0 / 61.0
    ewm = obi_instant
    for val in reversed(list(_obi_snapshots[symbol])[:-1]):
        ewm = alpha * val + (1 - alpha) * ewm

    # Update rolling window and compute z-score
    _update_rolling(_rolling_obi, symbol, ewm)
    obi_z = _z_score(ewm, _rolling_obi.get(symbol, deque()))

    snap_ts = float(data.get('T', data.get('lastUpdateId', time.time() * 1000))) / 1000
    age = time.time() - snap_ts if snap_ts > 1e9 else 0  # heuristic: if it looks like a real ts
    return {'obi_z': round(obi_z, 4), 'stale': age > 30, 'raw': round(ewm, 6), 'ts': snap_ts}


# ─────────────────────────────── Signal 3: MACD ──────────────────────────────

def fetch_macd_signal(symbol: str) -> dict:
    """
    Compute MACD histogram on 5-min candles from Binance Futures.
    Returns {'macd_z': float, 'stale': bool, 'raw': float, 'ts': float}
    """
    try:
        r = requests.get(
            f'{BINANCE_FUTURES}/klines',
            params={'symbol': symbol, 'interval': '5m', 'limit': 30},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        logger.warning('MACD fetch failed for %s: %s', symbol, e)
        return {'macd_z': 0.0, 'stale': True, 'raw': 0.0, 'ts': 0.0}

    if not data or len(data) < 26:
        return {'macd_z': 0.0, 'stale': True, 'raw': 0.0, 'ts': 0.0}

    closes = [float(candle[4]) for candle in data]  # index 4 = close price
    last_ts = float(data[-1][0]) / 1000  # open time of last candle

    # EMA helper
    def ema(values, span):
        alpha = 2.0 / (span + 1)
        result = [values[0]]
        for v in values[1:]:
            result.append(alpha * v + (1 - alpha) * result[-1])
        return result

    ema_12 = ema(closes, 12)
    ema_26 = ema(closes, 26)
    macd_line = [e12 - e26 for e12, e26 in zip(ema_12, ema_26)]
    macd_signal = ema(macd_line, 9)
    macd_hist = macd_line[-1] - macd_signal[-1]

    # Update rolling window and compute z-score
    _update_rolling(_rolling_macd, symbol, macd_hist)
    macd_z = _z_score(macd_hist, _rolling_macd.get(symbol, deque()))

    age = time.time() - last_ts
    return {'macd_z': round(macd_z, 4), 'stale': age > 600, 'raw': round(macd_hist, 6), 'ts': last_ts}


# ─────────────────────────────── Signal 4: OI Delta ──────────────────────────

def fetch_oi_conviction(symbol: str) -> dict:
    """
    Open Interest delta conviction signal.
    Returns {'oi_z': float, 'stale': bool, 'raw': float, 'ts': float}
    """
    try:
        r = requests.get(
            f'{BINANCE_DATA}/openInterestHist',
            params={'symbol': symbol, 'period': '5m', 'limit': 3},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        logger.warning('OI fetch failed for %s: %s', symbol, e)
        return {'oi_z': 0.0, 'stale': True, 'raw': 0.0, 'ts': 0.0}

    if not data or len(data) < 2:
        return {'oi_z': 0.0, 'stale': True, 'raw': 0.0, 'ts': 0.0}

    oi_now = float(data[-1].get('sumOpenInterest', 0))
    oi_prev = float(data[-2].get('sumOpenInterest', 0))
    last_ts = float(data[-1].get('timestamp', 0)) / 1000

    if oi_prev == 0:
        return {'oi_z': 0.0, 'stale': False, 'raw': 0.0, 'ts': last_ts}

    oi_delta_pct = (oi_now - oi_prev) / oi_prev

    # Need price delta for conviction — fetch from klines cache or quick fetch
    price_delta = _get_recent_price_delta(symbol)
    sign_price = 1.0 if price_delta > 0 else (-1.0 if price_delta < 0 else 0.0)
    oi_conviction_raw = oi_delta_pct * sign_price

    # Update rolling window and compute z-score (clip to [-2, 2])
    _update_rolling(_rolling_oi, symbol, oi_conviction_raw)
    oi_z = _z_score(oi_conviction_raw, _rolling_oi.get(symbol, deque()), clip_lo=-2.0, clip_hi=2.0)

    return {'oi_z': round(oi_z, 4), 'stale': False, 'raw': round(oi_conviction_raw, 6), 'ts': last_ts}


def _get_recent_price_delta(symbol: str) -> float:
    """Get 5-min price delta from recent klines (cached)."""
    cached = _cache_get(f'price_delta_{symbol}', ttl=120)
    if cached is not _CACHE_MISS:
        return cached

    try:
        r = requests.get(
            f'{BINANCE_FUTURES}/klines',
            params={'symbol': symbol, 'interval': '5m', 'limit': 2},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        if len(data) >= 2:
            p_now = float(data[-1][4])   # close
            p_prev = float(data[-2][4])  # close
            delta = (p_now - p_prev) / p_prev if p_prev > 0 else 0.0
            _cache_set(f'price_delta_{symbol}', delta)
            return delta
    except Exception:
        pass
    return 0.0


# ─────────────────────────────── Bias: Coinbase Price ────────────────────────

def fetch_coinbase_price(asset: str) -> float | None:
    """
    Fetch spot price from Coinbase.
    GET https://api.coinbase.com/v2/prices/{asset}-USD/spot
    """
    cached = _cache_get(f'coinbase_{asset}', ttl=30)
    if cached is not _CACHE_MISS:
        return cached

    try:
        r = requests.get(
            f'{COINBASE_API}/{asset}-USD/spot',
            timeout=10,
        )
        r.raise_for_status()
        price = float(r.json()['data']['amount'])
        _cache_set(f'coinbase_{asset}', price)
        return price
    except Exception as e:
        logger.warning('Coinbase price fetch failed for %s: %s', asset, e)
        return None


def fetch_binance_price(symbol: str) -> float | None:
    """Fetch mark price from Binance Futures."""
    cached = _cache_get(f'binance_price_{symbol}', ttl=30)
    if cached is not _CACHE_MISS:
        return cached

    try:
        r = requests.get(
            f'{BINANCE_FUTURES}/ticker/price',
            params={'symbol': symbol},
            timeout=10,
        )
        r.raise_for_status()
        price = float(r.json()['price'])
        _cache_set(f'binance_price_{symbol}', price)
        return price
    except Exception:
        return None


# ─────────────────────────────── Bias: Funding Rate ──────────────────────────

def get_funding_z(asset: str) -> float | None:
    """Get funding rate z-score from crypto_client (reuse existing infra)."""
    try:
        from crypto_client import _compute_funding_z_scores
        fz = _compute_funding_z_scores()
        return fz.get(asset.lower())
    except Exception:
        return None


# ─────────────────────────────── Bias: Polymarket ────────────────────────────

def get_polymarket_yes_prob(asset: str) -> float | None:
    """
    Check if Polymarket has a corresponding 15-min crypto market.
    Returns YES probability or None if unavailable.
    """
    # Polymarket doesn't have 15-min direction markets yet — placeholder
    return None


# ─────────────────────────────── Risk Filters ────────────────────────────────

def _get_session_pnl_15m() -> float:
    """Sum realized P&L from today's 15m trades."""
    today = date.today().isoformat()
    log_path = LOGS_DIR / f'trades_{today}.jsonl'
    if not log_path.exists():
        return 0.0

    total = 0.0
    for line in log_path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
            if rec.get('module') == 'crypto_15m' and rec.get('action') in ('settle', 'exit'):
                total += float(rec.get('pnl', 0.0))
        except Exception:
            continue
    return total


def _fetch_binance_5m_volume(symbol: str) -> float | None:
    """Get recent 5-min volume from Binance klines."""
    try:
        r = requests.get(
            f'{BINANCE_FUTURES}/klines',
            params={'symbol': symbol, 'interval': '5m', 'limit': 1},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        if data:
            return float(data[0][5])  # index 5 = volume
    except Exception:
        pass
    return None


def _fetch_30d_avg_binance_vol(symbol: str) -> float | None:
    """Get 30-day average daily volume as proxy (cached 1h)."""
    cached = _cache_get(f'avg_vol_30d_{symbol}', ttl=3600)
    if cached is not _CACHE_MISS:
        return cached

    try:
        r = requests.get(
            f'{BINANCE_FUTURES}/klines',
            params={'symbol': symbol, 'interval': '1d', 'limit': 30},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        if data:
            vols = [float(d[5]) for d in data]
            avg = statistics.mean(vols) if vols else 0.0
            # Convert daily avg to 5-min avg (288 5-min periods per day)
            avg_5m = avg / 288
            _cache_set(f'avg_vol_30d_{symbol}', avg_5m)
            return avg_5m
    except Exception:
        pass
    return None


def _get_realized_5m_vol(symbol: str) -> tuple[float | None, float | None]:
    """Get 5-min realized vol and 30-day average 5-min vol."""
    try:
        r = requests.get(
            f'{BINANCE_FUTURES}/klines',
            params={'symbol': symbol, 'interval': '5m', 'limit': 2},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        if data and len(data) >= 2:
            high = float(data[-1][2])
            low = float(data[-1][3])
            close_prev = float(data[-2][4])
            if close_prev > 0:
                vol_5m = (high - low) / close_prev
                return vol_5m, None
    except Exception:
        pass
    return None, None


def check_risk_filters(
    symbol: str,
    asset: str,
    raw_score: float,
    yes_ask: int,
    yes_bid: int,
    book_depth_usd: float,
    tfi_stale: bool,
    obi_stale: bool,
    fr_z: float | None,
) -> str | None:
    """
    Apply all 10 risk filters. Returns block reason string or None if clear.
    """
    # R1: Extreme realized vol
    vol_5m, _ = _get_realized_5m_vol(symbol)
    avg_vol_30d = _fetch_30d_avg_binance_vol(symbol)
    if vol_5m is not None and avg_vol_30d is not None and avg_vol_30d > 0:
        if vol_5m > 3.0 * avg_vol_30d:
            return 'EXTREME_VOL'

    # R2: Wide spread
    spread = yes_ask - yes_bid
    if spread > 8:
        return 'WIDE_SPREAD'

    # R3: Thin Kalshi book
    if book_depth_usd < 1000:
        return 'LOW_KALSHI_LIQUIDITY'

    # R4: Thin underlying volume
    binance_vol = _fetch_binance_5m_volume(symbol)
    avg_binance_vol = _fetch_30d_avg_binance_vol(symbol)
    if binance_vol is not None and avg_binance_vol is not None and avg_binance_vol > 0:
        if binance_vol < 0.25 * avg_binance_vol:
            return 'THIN_MARKET'

    # R5: Stale data
    if tfi_stale:
        return 'TFI_STALE'
    if obi_stale:
        return 'OBI_STALE'

    # R6: Extreme funding
    if fr_z is not None and abs(fr_z) > 3.0:
        return 'EXTREME_FUNDING'

    # R7: Low conviction
    if abs(raw_score) < 0.15:
        return 'LOW_CONVICTION'

    # R8: Session drawdown
    session_pnl = _get_session_pnl_15m()
    from capital import get_capital
    capital = get_capital()
    daily_alloc = capital * getattr(config, 'CRYPTO_15M_DAILY_CAP_PCT', 0.04)
    if session_pnl < -0.05 * daily_alloc:
        return 'DRAWDOWN_PAUSE'

    # R9: Macro event (reuse from main cycle if available)
    try:
        from ruppert_cycle import has_macro_event_within
        if has_macro_event_within(minutes=30):
            return 'MACRO_EVENT_RISK'
    except (ImportError, AttributeError):
        pass  # Not available in all contexts

    # R10: Coinbase-Binance basis
    coinbase_price = fetch_coinbase_price(asset)
    binance_price = fetch_binance_price(symbol)
    if coinbase_price and binance_price and binance_price > 0:
        basis = abs(coinbase_price - binance_price) / binance_price
        if basis > 0.0015:
            return 'BASIS_RISK'

    return None


# ─────────────────────────────── Decision Logger ─────────────────────────────

def _log_decision(
    market_id: str,
    window_open_ts: str,
    window_close_ts: str,
    elapsed_secs: float,
    signals: dict,
    kalshi: dict,
    decision: str,
    skip_reason: str | None,
    edge: float | None,
    entry_price: int | None,
    position_usd: float | None,
):
    """Append decision record to decisions_15m.jsonl."""
    record = {
        'ts': datetime.now(timezone.utc).isoformat(),
        'market_id': market_id,
        'window_open_ts': window_open_ts,
        'window_close_ts': window_close_ts,
        'elapsed_secs': round(elapsed_secs, 1),
        'signals': signals,
        'kalshi': kalshi,
        'decision': decision,
        'skip_reason': skip_reason,
        'edge': round(edge, 4) if edge is not None else None,
        'entry_price': entry_price,
        'position_usd': round(position_usd, 2) if position_usd is not None else None,
    }
    try:
        with open(DECISION_LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps(record) + '\n')
    except Exception as e:
        logger.error('Decision log write failed: %s', e)


# ─────────────────────────────── Core Entry Evaluator ────────────────────────

def is_15m_ticker(ticker: str) -> bool:
    """Check if a ticker belongs to the 15-min crypto direction series."""
    series = ticker.split('-')[0].upper()
    return series in CRYPTO_15M_SERIES


def _parse_asset_from_ticker(ticker: str) -> str | None:
    """Extract asset name from 15-min ticker (KXBTC15M-... → BTC)."""
    series = ticker.split('-')[0].upper()
    for prefix in ('KXBTC15M', 'KXETH15M', 'KXXRP15M', 'KXDOGE15M'):
        if series == prefix:
            asset = prefix.replace('KX', '').replace('15M', '')
            return asset
    return None


def evaluate_crypto_15m_entry(
    ticker: str,
    yes_ask: int,
    yes_bid: int,
    close_time: str | None = None,
    open_time: str | None = None,
    book_depth_usd: float = 2000.0,
):
    """
    Evaluate a 15-min crypto direction market for entry.

    Called on each WS tick for KXBTC15M/KXETH15M/KXXRP15M/KXDOGE15M tickers.

    Args:
        ticker:         Kalshi market ticker
        yes_ask:        YES ask in cents
        yes_bid:        YES bid in cents
        close_time:     Market close time (ISO 8601)
        open_time:      Window open time (ISO 8601)
        book_depth_usd: Estimated book depth in USD
    """
    from capital import get_capital
    from logger import log_trade, log_activity, get_daily_exposure
    from kalshi_client import KalshiClient
    from position_monitor import load_traded_tickers, push_alert

    asset = _parse_asset_from_ticker(ticker)
    if not asset:
        return

    symbol = ASSET_SYMBOLS.get(asset)
    if not symbol:
        return

    # ── Parse timing ──
    now = datetime.now(timezone.utc)
    window_open_ts = open_time or ''
    window_close_ts = close_time or ''

    elapsed_secs = 0.0
    close_dt = None

    if open_time:
        try:
            open_dt = datetime.fromisoformat(open_time.replace('Z', '+00:00'))
            elapsed_secs = (now - open_dt).total_seconds()
        except Exception:
            pass

    if close_time:
        try:
            close_dt = datetime.fromisoformat(close_time.replace('Z', '+00:00'))
        except Exception:
            pass

    # If no open_time or close_time from WS message (WS ticker msgs don't include them),
    # parse window open time directly from ticker name.
    # Format: KXBTC15M-26MAR281315-15 → window opens at 2026-03-28 13:15 UTC
    if not elapsed_secs:
        try:
            parts = ticker.split('-')
            if len(parts) >= 2:
                date_part = parts[1]  # e.g. '26MAR281315'
                # Format: YYMMMDDhhmm
                import re
                m = re.match(r'(\d{2})([A-Z]{3})(\d{2})(\d{2})(\d{2})', date_part)
                if m:
                    yr = 2000 + int(m.group(1))
                    mon_str = m.group(2)
                    day = int(m.group(3))
                    hour = int(m.group(4))
                    minute = int(m.group(5))
                    mon_map = {'JAN':1,'FEB':2,'MAR':3,'APR':4,'MAY':5,'JUN':6,
                               'JUL':7,'AUG':8,'SEP':9,'OCT':10,'NOV':11,'DEC':12}
                    mon = mon_map.get(mon_str, 1)
                    # Kalshi ticker encodes CLOSE time in EST (UTC-4)
                    # e.g. 26MAR281330 = closes at 13:30 EST = 17:30 UTC
                    est = pytz.timezone('America/New_York')
                    close_est = est.localize(datetime(yr, mon, day, hour, minute))
                    close_dt = close_est.astimezone(timezone.utc)
                    open_dt = close_dt - timedelta(minutes=15)
                    elapsed_secs = (now - open_dt).total_seconds()
                    if not window_open_ts:
                        window_open_ts = open_dt.isoformat()
                    if not window_close_ts:
                        window_close_ts = close_dt.isoformat()
        except Exception:
            pass

    # Final fallback: estimate from close_time if we somehow have it but not elapsed
    if not elapsed_secs and close_dt:
        elapsed_secs = max(0, 900 - (close_dt - now).total_seconds())

    # ── Timing Gate ──
    min_edge = getattr(config, 'CRYPTO_15M_MIN_EDGE', 0.08)

    if elapsed_secs < 120:
        _log_decision(ticker, window_open_ts, window_close_ts, elapsed_secs,
                       {}, {'yes_ask': yes_ask, 'yes_bid': yes_bid, 'spread': yes_ask - yes_bid, 'book_depth_usd': book_depth_usd},
                       'SKIP', 'EARLY_WINDOW', None, None, None)
        return

    elif elapsed_secs <= 480:
        pass  # primary window, use base min_edge

    elif elapsed_secs <= 660:
        min_edge = min_edge * 1.25  # secondary window, harder threshold

    else:
        _log_decision(ticker, window_open_ts, window_close_ts, elapsed_secs,
                       {}, {'yes_ask': yes_ask, 'yes_bid': yes_bid, 'spread': yes_ask - yes_bid, 'book_depth_usd': book_depth_usd},
                       'SKIP', 'LATE_WINDOW', None, None, None)
        return

    # ── Already traded? ──
    traded = load_traded_tickers()
    if ticker in traded:
        return

    # ── Fetch all signals ──
    tfi = fetch_taker_flow_imbalance(symbol)
    obi = fetch_orderbook_imbalance(symbol)
    macd = fetch_macd_signal(symbol)
    oi = fetch_oi_conviction(symbol)

    tfi_z = tfi['tfi_z']
    obi_z = obi['obi_z']
    macd_z = macd['macd_z']
    oi_z = oi['oi_z']

    # ── Composite Score → Probability ──
    raw_score = W_TFI * tfi_z + W_OBI * obi_z + W_MACD * macd_z + W_OI * oi_z
    scale = getattr(config, 'CRYPTO_15M_SIGMOID_SCALE', 1.0)
    P_directional = 1.0 / (1.0 + math.exp(-scale * raw_score))

    # ── Bias Filters ──
    fr_z = get_funding_z(asset)
    funding_mult = 1.0
    if fr_z is not None:
        if fr_z > 2.0:
            funding_mult = 0.85
        elif fr_z < -2.0:
            funding_mult = 1.15

    P_biased = P_directional * funding_mult

    # Polymarket divergence nudge
    poly_nudge = 0.0
    poly_yes = get_polymarket_yes_prob(asset)
    kalshi_yes = yes_ask / 100.0
    if poly_yes is not None:
        divergence = poly_yes - kalshi_yes
        if abs(divergence) > 0.03:
            poly_nudge = 0.3 * divergence

    P_final = max(0.05, min(0.95, P_biased + poly_nudge))

    # ── Build signal dict for logging ──
    signals = {
        'tfi_z': tfi_z,
        'obi_z': obi_z,
        'macd_z': macd_z,
        'oi_conviction_z': oi_z,
        'raw_score': round(raw_score, 4),
        'P_final': round(P_final, 4),
    }
    kalshi_info = {
        'yes_ask': yes_ask,
        'yes_bid': yes_bid,
        'spread': yes_ask - yes_bid,
        'book_depth_usd': book_depth_usd,
    }

    # ── Risk Filters ──
    block_reason = check_risk_filters(
        symbol=symbol,
        asset=asset,
        raw_score=raw_score,
        yes_ask=yes_ask,
        yes_bid=yes_bid,
        book_depth_usd=book_depth_usd,
        tfi_stale=tfi['stale'],
        obi_stale=obi['stale'],
        fr_z=fr_z,
    )
    if block_reason:
        _log_decision(ticker, window_open_ts, window_close_ts, elapsed_secs,
                       signals, kalshi_info, 'SKIP', block_reason, None, None, None)
        return

    # ── Entry Logic ──
    edge_yes = P_final - (yes_ask / 100.0)
    edge_no = (1.0 - P_final) - ((100 - yes_bid) / 100.0)

    direction = None
    entry_price = None
    P_win = None
    edge = None

    if edge_yes >= min_edge:
        direction = 'yes'
        entry_price = yes_ask
        P_win = P_final
        edge = edge_yes
    elif edge_no >= min_edge:
        direction = 'no'
        entry_price = 100 - yes_bid
        P_win = 1.0 - P_final
        edge = edge_no
    else:
        _log_decision(ticker, window_open_ts, window_close_ts, elapsed_secs,
                       signals, kalshi_info, 'SKIP', 'INSUFFICIENT_EDGE',
                       max(edge_yes, edge_no), None, None)
        return

    # ── Daily cap check ──
    capital = get_capital()
    daily_cap = capital * getattr(config, 'CRYPTO_15M_DAILY_CAP_PCT', 0.04)
    current_exposure = get_daily_exposure('crypto_15m')

    if current_exposure >= daily_cap:
        _log_decision(ticker, window_open_ts, window_close_ts, elapsed_secs,
                       signals, kalshi_info, 'SKIP', 'DAILY_CAP',
                       edge, entry_price, None)
        return

    # ── Position Sizing: Half-Kelly, capped ──
    c = entry_price / 100.0
    denom = c * (1.0 - c)
    if denom <= 0:
        return

    kelly_full = (P_win - c) / denom
    kelly_half = kelly_full / 2.0

    position_usd = min(
        kelly_half * capital,
        capital * getattr(config, 'MAX_POSITION_PCT', 0.01),
        100.0,  # hard $100 cap
    )
    position_usd = max(position_usd, 5.0)  # minimum viable

    # Don't exceed remaining daily cap
    position_usd = min(position_usd, daily_cap - current_exposure)
    if position_usd < 5.0:
        _log_decision(ticker, window_open_ts, window_close_ts, elapsed_secs,
                       signals, kalshi_info, 'SKIP', 'SIZE_TOO_SMALL',
                       edge, entry_price, position_usd)
        return

    # ── Execute ──
    contracts = max(1, int(position_usd / (entry_price / 100.0)))

    print(f"  [15m Crypto] {ticker} {direction.upper()} | P={P_final:.2f} edge={edge:+.1%} | ${position_usd:.2f}")

    if DRY_RUN:
        order_result = {'dry_run': True, 'status': 'simulated'}
    else:
        try:
            client = KalshiClient()
            order_result = client.place_order(ticker, direction, entry_price, contracts)
        except Exception as e:
            print(f"  [15m Crypto] Order failed: {e}")
            _log_decision(ticker, window_open_ts, window_close_ts, elapsed_secs,
                           signals, kalshi_info, 'SKIP', f'ORDER_FAILED:{e}',
                           edge, entry_price, position_usd)
            return

    # ── Log trade ──
    opp = {
        'ticker': ticker,
        'title': f'{asset} 15m direction',
        'side': direction,
        'edge': round(edge, 4),
        'win_prob': round(P_win, 4),
        'confidence': round(abs(raw_score), 3),
        'market_prob': yes_ask / 100.0 if direction == 'yes' else (100 - yes_bid) / 100.0,
        'model_prob': round(P_final, 4),
        'source': 'crypto_15m',
        'module': 'crypto_15m',
        'yes_ask': yes_ask,
        'yes_bid': yes_bid,
        'hours_to_settlement': max(0, (900 - elapsed_secs) / 3600),
        'action': 'buy',
        'contracts': contracts,
        'size_dollars': round(position_usd, 2),
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'date': str(date.today()),
        'scan_price': entry_price,
    }

    log_trade(opp, position_usd, contracts, order_result)
    log_activity(f'[15M-CRYPTO] Entered {ticker} {direction.upper()} @ {entry_price}c | edge={edge:+.1%} P={P_final:.2f}')
    push_alert('trade', f'15M Crypto: {ticker} {direction.upper()} @ {entry_price}c', ticker=ticker)

    # ── Log decision ──
    _log_decision(ticker, window_open_ts, window_close_ts, elapsed_secs,
                   signals, kalshi_info,
                   direction.upper(), None,
                   edge, entry_price, position_usd)

