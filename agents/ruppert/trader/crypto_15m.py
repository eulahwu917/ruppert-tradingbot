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
import sys
import time
import logging
import statistics
import requests
import uuid
import threading
from collections import deque
from datetime import datetime, timezone, date, timedelta
import pytz
from pathlib import Path

# Ensure project root is on sys.path when running standalone
# Resolve workspace root and add to path (agents.ruppert.* + config shim)
_AGENTS_ROOT = Path(__file__).parent.parent.parent  # workspace/agents
_WORKSPACE_ROOT = _AGENTS_ROOT.parent               # workspace/
if str(_WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE_ROOT))

import config

logger = logging.getLogger(__name__)

# ─────────────────────────────── Constants ────────────────────────────────────

OKX_API      = 'https://www.okx.com/api/v5'
COINBASE_API = 'https://api.coinbase.com/v2/prices'

CRYPTO_15M_SERIES = ['KXBTC15M', 'KXETH15M', 'KXXRP15M', 'KXDOGE15M', 'KXSOL15M']

ASSET_SYMBOLS = {
    'BTC':  'BTC-USDT-SWAP',
    'ETH':  'ETH-USDT-SWAP',
    'XRP':  'XRP-USDT-SWAP',
    'DOGE': 'DOGE-USDT-SWAP',
    'SOL':  'SOL-USDT-SWAP',
}

# Per-asset module identifiers (Phase B1 taxonomy)
ASSET_MODULE_NAMES = {
    'BTC':  'crypto_dir_15m_btc',
    'ETH':  'crypto_dir_15m_eth',
    'SOL':  'crypto_dir_15m_sol',
    'XRP':  'crypto_dir_15m_xrp',
    'DOGE': 'crypto_dir_15m_doge',
}
_ALL_CRYPTO_15M_MODULES = list(ASSET_MODULE_NAMES.values())

# Signal weights — must sum to 1.0 (config-driven)
# ISSUE-069: named defaults so we can detect MISSING keys via hasattr()
_W_TFI_DEFAULT  = 0.42
_W_OBI_DEFAULT  = 0.25
_W_MACD_DEFAULT = 0.15
_W_OI_DEFAULT   = 0.18

W_TFI  = getattr(config, 'CRYPTO_15M_DIR_W_TFI',  _W_TFI_DEFAULT)
W_OBI  = getattr(config, 'CRYPTO_15M_DIR_W_OBI',  _W_OBI_DEFAULT)
W_MACD = getattr(config, 'CRYPTO_15M_DIR_W_MACD', _W_MACD_DEFAULT)
W_OI   = getattr(config, 'CRYPTO_15M_DIR_W_OI',   _W_OI_DEFAULT)

# ISSUE-069: warn if any weight key is MISSING from config (hasattr detects absence, not value equality)
_missing_weight_keys = [
    key for key, present in [
        ('CRYPTO_15M_DIR_W_TFI',  hasattr(config, 'CRYPTO_15M_DIR_W_TFI')),
        ('CRYPTO_15M_DIR_W_OBI',  hasattr(config, 'CRYPTO_15M_DIR_W_OBI')),
        ('CRYPTO_15M_DIR_W_MACD', hasattr(config, 'CRYPTO_15M_DIR_W_MACD')),
        ('CRYPTO_15M_DIR_W_OI',   hasattr(config, 'CRYPTO_15M_DIR_W_OI')),
    ] if not present
]
if _missing_weight_keys:
    logger.warning(
        'crypto_15m: signal weight config keys missing: %s. '
        'Using fallback defaults: TFI=%.2f OBI=%.2f MACD=%.2f OI=%.2f',
        ', '.join(_missing_weight_keys),
        W_TFI, W_OBI, W_MACD, W_OI,
    )

# ISSUE-114: raise ValueError (not assert — immune to -O flag) if weights don't sum to 1.0
_weights_sum = W_TFI + W_OBI + W_MACD + W_OI
if abs(_weights_sum - 1.0) >= 1e-6:
    raise ValueError(
        f"CRYPTO_15M signal weights must sum to 1.0, got {_weights_sum:.6f} "
        f"(TFI={W_TFI}, OBI={W_OBI}, MACD={W_MACD}, OI={W_OI})"
    )

from agents.ruppert.env_config import get_paths as _get_paths
from agents.ruppert.strategist.strategy import should_enter
from agents.ruppert.data_analyst.polymarket_client import get_crypto_consensus
from agents.ruppert.trader import circuit_breaker
LOGS_DIR = _get_paths()['logs']
LOGS_DIR.mkdir(exist_ok=True)
DECISION_LOG = LOGS_DIR / 'decisions_15m.jsonl'

# DRY_RUN intentionally not captured at module level — read at call time (see evaluate_crypto_15m_entry)

# ─────────────────────────────── Module-Level Cap State ───────────────────────

# Per-window exposure counter (in-memory, race-safe)
_window_lock           = threading.Lock()
_window_exposure: dict = {}    # dict: window_open_ts (str) → float (dollars committed this window)
_daily_wager           = 0.0   # float: total dollars wagered today (all buys)
_daily_wager_date      = ''    # str: ISO date string, used to detect midnight rollover
_cb_last_window_ts     = ''    # str: last window_open_ts seen (used to detect window transition)

_state_initialized = False     # guard: _rehydrate_state() runs only once per process



def _get_current_window_open_ts() -> str:
    """
    Derive the current 15-minute window open timestamp from now().
    Floors to the nearest 15-minute boundary in UTC.
    Returns ISO format string, e.g. '2026-03-30T13:15:00+00:00'
    """
    now = datetime.now(timezone.utc)
    floored_minute = (now.minute // 15) * 15
    window_open = now.replace(minute=floored_minute, second=0, microsecond=0)
    return window_open.isoformat()


def _rehydrate_state():
    """
    Re-read trade log and circuit breaker state file to restore in-memory counters
    after a restart. Called once at startup before first evaluation.
    """
    global _daily_wager, _daily_wager_date, _window_exposure, _state_initialized

    if _state_initialized:
        return
    _state_initialized = True

    today_str = circuit_breaker._today_pdt()
    _daily_wager_date = today_str

    # 1. Daily wager: sum all buys today from trade log
    try:
        from agents.ruppert.data_scientist.logger import get_daily_wager, get_window_exposure
        _daily_wager = sum(get_daily_wager(m) for m in _ALL_CRYPTO_15M_MODULES)

        # 2. Window exposure: re-hydrate for any window currently open
        current_window_ts = _get_current_window_open_ts()
        if current_window_ts:
            _window_exposure[current_window_ts] = sum(get_window_exposure(m, current_window_ts) for m in _ALL_CRYPTO_15M_MODULES)
    except Exception as e:
        logger.warning('[crypto_15m] _rehydrate_state: failed to re-hydrate wager counters: %s', e)

    # 3. Circuit breaker: log max consecutive losses from unified state file
    _cb_max = max((circuit_breaker.get_consecutive_losses(m) for m in _ALL_CRYPTO_15M_MODULES), default=0)

    logger.info(
        '[crypto_15m] State rehydrated: daily_wager=$%.2f, cb_max_consecutive_losses=%d',
        _daily_wager, _cb_max,
    )


# Run rehydration at module load time
_rehydrate_state()

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

ROLLING_WINDOW = getattr(config, 'CRYPTO_15M_ROLLING_WINDOW_BUCKETS', 48)  # 4 hours of 5-min buckets


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
    Compute Taker Flow Imbalance from OKX recent trades.
    OKX doesn't have pre-bucketed taker vol — we compute buy/sell vol
    from raw trades grouped into 5-min buckets.
    Returns {'tfi_z': float, 'stale': bool, 'raw': float, 'ts': float}
    """
    try:
        r = requests.get(
            f'{OKX_API}/market/trades',
            params={'instId': symbol, 'limit': '200'},
            timeout=10,
        )
        r.raise_for_status()
        resp = r.json()
        trades = resp.get('data', [])
    except Exception as e:
        logger.warning('TFI fetch failed for %s: %s', symbol, e)
        return {'tfi_z': 0.0, 'stale': True, 'raw': 0.0, 'ts': 0.0}

    if not trades:
        return {'tfi_z': 0.0, 'stale': True, 'raw': 0.0, 'ts': 0.0}

    # Group trades into 5-min buckets by timestamp
    bucket_size_ms = 5 * 60 * 1000
    buckets_map: dict[int, dict] = {}
    last_ts = 0

    for t in trades:
        ts_ms = int(t.get('ts', 0))
        side = t.get('side', '')
        sz = float(t.get('sz', 0))
        bucket_key = ts_ms // bucket_size_ms
        if bucket_key not in buckets_map:
            buckets_map[bucket_key] = {'buy': 0.0, 'sell': 0.0}
        if side == 'buy':
            buckets_map[bucket_key]['buy'] += sz
        else:
            buckets_map[bucket_key]['sell'] += sz
        last_ts = max(last_ts, ts_ms / 1000)

    # Sort buckets chronologically and compute TFI per bucket
    sorted_keys = sorted(buckets_map.keys())
    bucket_tfis = []
    for k in sorted_keys:
        b = buckets_map[k]
        total = b['buy'] + b['sell']
        tfi = (b['buy'] - b['sell']) / total if total > 0 else 0.0
        bucket_tfis.append(tfi)

    # Time-weighted composite of last 3 buckets
    weights = getattr(config, 'CRYPTO_15M_TFI_BUCKET_WEIGHTS', [0.20, 0.30, 0.50])
    while len(bucket_tfis) < 3:
        bucket_tfis.insert(0, 0.0)
    tfi_composite = sum(w * t for w, t in zip(weights, bucket_tfis[-3:]))

    # Update rolling window and compute z-score
    _update_rolling(_rolling_tfi, symbol, tfi_composite)
    tfi_z = _z_score(tfi_composite, _rolling_tfi.get(symbol, deque()))

    age = time.time() - last_ts if last_ts > 0 else 999
    return {'tfi_z': round(tfi_z, 4), 'stale': age > 90, 'raw': round(tfi_composite, 6), 'ts': last_ts}


# ─────────────────────────────── Signal 2: OBI ───────────────────────────────

_obi_snapshots: dict[str, deque] = {}  # EWM history per symbol


def fetch_orderbook_imbalance(symbol: str) -> dict:
    """
    Fetch orderbook depth from OKX.
    Returns {'obi_z': float, 'stale': bool, 'raw': float, 'ts': float}
    """
    try:
        r = requests.get(
            f'{OKX_API}/market/books',
            params={'instId': symbol, 'sz': '10'},
            timeout=10,
        )
        r.raise_for_status()
        resp = r.json()
        data = resp.get('data', [{}])[0]
    except Exception as e:
        logger.warning('OBI fetch failed for %s: %s', symbol, e)
        return {'obi_z': 0.0, 'stale': True, 'raw': 0.0, 'ts': 0.0}

    # OKX format: bids/asks are [[price, qty, 0, orders], ...]
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
    snapshots = list(_obi_snapshots[symbol])  # chronological: oldest first
    if not snapshots:
        ewm = 0.0
    else:
        ewm = snapshots[0]  # seed with OLDEST value
        for val in snapshots[1:]:  # iterate OLDEST → NEWEST (forward)
            ewm = alpha * val + (1 - alpha) * ewm
    # NOTE: EWM direction corrected (ISSUE-087, 2026-04-03). First ~4h of obi_z post-deploy are transitional.
    if not hasattr(fetch_orderbook_imbalance, '_ewm_correction_logged'):
        logger.info('[crypto_15m] OBI EWM direction corrected — seed=oldest, iterate forward (ISSUE-087)')
        fetch_orderbook_imbalance._ewm_correction_logged = True

    # Update rolling window and compute z-score
    _update_rolling(_rolling_obi, symbol, ewm)
    obi_z = _z_score(ewm, _rolling_obi.get(symbol, deque()))

    snap_ts = float(data.get('ts', time.time() * 1000)) / 1000
    age = time.time() - snap_ts if snap_ts > 1e9 else 0
    return {'obi_z': round(obi_z, 4), 'stale': age > 30, 'raw': round(ewm, 6), 'ts': snap_ts}


# ─────────────────────────────── Signal 3: MACD ──────────────────────────────

def fetch_macd_signal(symbol: str) -> dict:
    """
    Compute MACD histogram on 5-min candles from OKX.
    Returns {'macd_z': float, 'stale': bool, 'raw': float, 'ts': float}
    """
    try:
        r = requests.get(
            f'{OKX_API}/market/candles',
            params={'instId': symbol, 'bar': '5m', 'limit': '30'},
            timeout=10,
        )
        r.raise_for_status()
        resp = r.json()
        # OKX returns newest first — reverse to chronological
        data = list(reversed(resp.get('data', [])))
    except Exception as e:
        logger.warning('MACD fetch failed for %s: %s', symbol, e)
        return {'macd_z': 0.0, 'stale': True, 'raw': 0.0, 'ts': 0.0}

    if not data or len(data) < 26:
        return {'macd_z': 0.0, 'stale': True, 'raw': 0.0, 'ts': 0.0}

    # OKX candle format: [ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]
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
    Open Interest delta conviction signal from OKX.
    OKX provides a snapshot (not history) — we cache the previous value
    and compute delta vs the cached value.
    Returns {'oi_z': float, 'stale': bool, 'raw': float, 'ts': float}
    """
    try:
        r = requests.get(
            f'{OKX_API}/public/open-interest',
            params={'instType': 'SWAP', 'instId': symbol},
            timeout=10,
        )
        r.raise_for_status()
        resp = r.json()
        oi_data = resp.get('data', [])
    except Exception as e:
        logger.warning('OI fetch failed for %s: %s', symbol, e)
        return {'oi_z': 0.0, 'stale': True, 'raw': 0.0, 'ts': 0.0}

    if not oi_data:
        return {'oi_z': 0.0, 'stale': True, 'raw': 0.0, 'ts': 0.0}

    curr_oi = float(oi_data[0].get('oiCcy', 0))
    last_ts = float(oi_data[0].get('ts', 0)) / 1000

    # Retrieve previous OI from cache, then store current
    prev_oi_key = f'prev_oi_{symbol}'
    prev_oi = _cache_get(prev_oi_key, ttl=600)  # 10 min TTL for previous snapshot
    _cache_set(prev_oi_key, curr_oi)

    if prev_oi is _CACHE_MISS or prev_oi < 1e-6:  # ISSUE-129: guard near-zero prev_oi
        return {'oi_z': 0.0, 'stale': False, 'raw': 0.0, 'ts': last_ts}

    oi_delta_pct = (curr_oi - prev_oi) / prev_oi

    # Need price delta for conviction — fetch from klines cache or quick fetch
    price_delta = _get_recent_price_delta(symbol)
    sign_price = 1.0 if price_delta > 0 else (-1.0 if price_delta < 0 else 0.0)
    oi_conviction_raw = oi_delta_pct * sign_price

    # Update rolling window and compute z-score (clip to [-2, 2])
    _update_rolling(_rolling_oi, symbol, oi_conviction_raw)
    oi_z = _z_score(oi_conviction_raw, _rolling_oi.get(symbol, deque()), clip_lo=-2.0, clip_hi=2.0)

    return {'oi_z': round(oi_z, 4), 'stale': False, 'raw': round(oi_conviction_raw, 6), 'ts': last_ts}


def _get_recent_price_delta(symbol: str) -> float:
    """Get 5-min price delta from recent OKX candles (cached)."""
    cached = _cache_get(f'price_delta_{symbol}', ttl=120)
    if cached is not _CACHE_MISS:
        return cached

    try:
        r = requests.get(
            f'{OKX_API}/market/candles',
            params={'instId': symbol, 'bar': '5m', 'limit': '2'},
            timeout=10,
        )
        r.raise_for_status()
        resp = r.json()
        data = list(reversed(resp.get('data', [])))  # OKX returns newest first
        if len(data) >= 2:
            p_now = float(data[-1][4])   # close
            p_prev = float(data[-2][4])  # close
            delta = (p_now - p_prev) / p_prev if p_prev > 0 else 0.0
            _cache_set(f'price_delta_{symbol}', delta)
            return delta
    except Exception as e:
        logger.warning('fetch_price_delta failed for %s: %s', symbol, e)
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


def fetch_okx_price(symbol: str) -> float | None:
    """Fetch last price from OKX."""
    cached = _cache_get(f'okx_price_{symbol}', ttl=30)
    if cached is not _CACHE_MISS:
        return cached

    try:
        r = requests.get(
            f'{OKX_API}/market/ticker',
            params={'instId': symbol},
            timeout=10,
        )
        r.raise_for_status()
        resp = r.json()
        data = resp.get('data', [{}])[0]
        price = float(data['last'])
        _cache_set(f'okx_price_{symbol}', price)
        return price
    except Exception as e:
        logger.warning('fetch_okx_price failed for %s: %s', symbol, e)
        return None


# ─────────────────────────────── Bias: Funding Rate ──────────────────────────

def get_funding_z(asset: str) -> float | None:
    """Get funding rate z-score from crypto_client (reuse existing infra)."""
    try:
        from agents.ruppert.trader.crypto_client import _compute_funding_z_scores
        fz = _compute_funding_z_scores()
        return fz.get(asset.lower())
    except Exception:
        return None


# ─────────────────────────────── Bias: Polymarket ────────────────────────────
# get_polymarket_yes_prob stub removed — get_crypto_consensus imported at module level


# ─────────────────────────────── Risk Filters ────────────────────────────────

def _get_session_pnl_15m() -> float:
    """Sum realized P&L from today's 15m trades."""
    today = date.today().isoformat()
    log_path = _get_paths()['trades'] / f'trades_{today}.jsonl'
    if not log_path.exists():
        return 0.0

    total = 0.0
    for line in log_path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
            if rec.get('module', '').startswith('crypto_dir_15m_') and rec.get('action') in ('settle', 'exit'):
                total += float(rec.get('pnl', 0.0))
        except Exception:
            continue
    return total


def _fetch_okx_5m_volume(symbol: str) -> float | None:
    """Get recent 5-min volume from OKX candles."""
    try:
        r = requests.get(
            f'{OKX_API}/market/candles',
            params={'instId': symbol, 'bar': '5m', 'limit': '1'},
            timeout=10,
        )
        r.raise_for_status()
        resp = r.json()
        data = resp.get('data', [])
        if data:
            return float(data[0][5])  # index 5 = vol (in contracts)
    except Exception:
        pass
    return None


def _fetch_30d_avg_okx_vol(symbol: str) -> float | None:
    """Get 30-day average daily volume as proxy (cached 1h)."""
    cached = _cache_get(f'avg_vol_30d_{symbol}', ttl=3600)
    if cached is not _CACHE_MISS:
        return cached

    try:
        r = requests.get(
            f'{OKX_API}/market/candles',
            params={'instId': symbol, 'bar': '1D', 'limit': '30'},
            timeout=10,
        )
        r.raise_for_status()
        resp = r.json()
        data = resp.get('data', [])
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


def _fetch_30d_avg_price_vol(symbol: str) -> float | None:
    """Get 30-day average of 5-min price range ratio (high-low)/close, for R1 comparison."""
    cached = _cache_get(f'avg_price_vol_30d_{symbol}', ttl=3600)
    if cached is not _CACHE_MISS:
        return cached

    try:
        r = requests.get(
            f'{OKX_API}/market/candles',
            params={'instId': symbol, 'bar': '5m', 'limit': '8640'},  # 30 days of 5-min candles
            timeout=15,
        )
        r.raise_for_status()
        resp = r.json()
        data = resp.get('data', [])
        if len(data) < 10:
            return None
        ratios = []
        for candle in data:
            try:
                high = float(candle[2])
                low = float(candle[3])
                close_prev = float(candle[4])
                if close_prev > 0:
                    ratios.append((high - low) / close_prev)
            except Exception:
                continue
        if not ratios:
            return None
        avg = statistics.mean(ratios)
        _cache_set(f'avg_price_vol_30d_{symbol}', avg)
        return avg
    except Exception:
        return None


def _get_realized_5m_vol(symbol: str) -> tuple[float | None, float | None]:
    """Get 5-min realized vol from OKX candles."""
    try:
        r = requests.get(
            f'{OKX_API}/market/candles',
            params={'instId': symbol, 'bar': '5m', 'limit': '2'},
            timeout=10,
        )
        r.raise_for_status()
        resp = r.json()
        data = list(reversed(resp.get('data', [])))  # OKX returns newest first
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
    dollar_oi: float = 0.0,
) -> dict:
    """
    Apply all 10 risk filters.

    Returns dict:
        {
            'block': str | None,       # block reason, or None if all filters pass
            'okx_volume_pct': float | None,  # actual okx_vol / avg_30d (e.g. 0.12 = 12%)
        }
    'block' is None means clear to enter.
    'okx_volume_pct' is always returned when available (even on block) for logging.
    """
    # Compute OKX volume ratio upfront (used for R4 gate + tagging on all rejection paths)
    okx_volume_pct: float | None = None
    try:
        okx_vol = _fetch_okx_5m_volume(symbol)
        avg_okx_vol = _fetch_30d_avg_okx_vol(symbol)
        if okx_vol is not None and avg_okx_vol is not None and avg_okx_vol > 0:
            okx_volume_pct = round(okx_vol / avg_okx_vol, 4)
    except Exception:
        pass

    # R1: Extreme realized vol — compare price range ratio against its own 30-day average.
    # vol_5m is a dimensionless price range ratio (high-low)/close_prev.
    # avg_vol_30d was volume (contracts) — wrong units. Use a dedicated price-vol baseline instead.
    vol_5m, _ = _get_realized_5m_vol(symbol)
    avg_price_vol_30d = _fetch_30d_avg_price_vol(symbol)  # NEW function — see Notes
    if vol_5m is not None and avg_price_vol_30d is not None and avg_price_vol_30d > 0:
        if vol_5m > 3.0 * avg_price_vol_30d:
            return {'block': 'EXTREME_VOL', 'okx_volume_pct': okx_volume_pct}

    # R2: Wide spread — now config-driven (DEMO: 15c, PROD default: 8c)
    spread = yes_ask - yes_bid
    max_spread = getattr(config, 'CRYPTO_15M_MAX_SPREAD', 8)
    if spread > max_spread:
        return {'block': 'WIDE_SPREAD', 'okx_volume_pct': okx_volume_pct}

    # R3: Thin Kalshi book — percentage of OI (scales with market activity)
    # Require book depth >= LIQUIDITY_MIN_PCT of open interest
    # Falls back to absolute $100 floor if OI is unavailable
    liquidity_min_pct = getattr(config, 'CRYPTO_15M_LIQUIDITY_MIN_PCT', 0.003)
    liquidity_floor = getattr(config, 'CRYPTO_15M_LIQUIDITY_FLOOR', 20.0)
    if dollar_oi > 0:
        min_depth = max(dollar_oi * liquidity_min_pct, liquidity_floor)
    else:
        min_depth = liquidity_floor
    if book_depth_usd < min_depth:
        return {'block': 'LOW_KALSHI_LIQUIDITY', 'okx_volume_pct': okx_volume_pct}

    # R4: Thin underlying volume — now uses already-computed okx_volume_pct
    if okx_volume_pct is not None:
        thin_market_ratio = getattr(config, 'CRYPTO_15M_THIN_MARKET_RATIO', 0.25)
        if okx_volume_pct < thin_market_ratio:
            return {'block': 'THIN_MARKET', 'okx_volume_pct': okx_volume_pct}

    # R5: Stale data
    if tfi_stale:
        return {'block': 'TFI_STALE', 'okx_volume_pct': okx_volume_pct}
    if obi_stale:
        return {'block': 'OBI_STALE', 'okx_volume_pct': okx_volume_pct}

    # R6: Extreme funding
    if fr_z is not None and abs(fr_z) > 3.0:
        return {'block': 'EXTREME_FUNDING', 'okx_volume_pct': okx_volume_pct}

    # R7: Low conviction
    min_conviction = getattr(config, 'CRYPTO_15M_MIN_CONVICTION', 0.05)
    if abs(raw_score) < min_conviction:
        return {'block': 'LOW_CONVICTION', 'okx_volume_pct': okx_volume_pct}

    # R8: Session drawdown
    session_pnl = _get_session_pnl_15m()
    from agents.ruppert.data_scientist.capital import get_capital
    capital = get_capital()
    # R8: pause if session loss exceeds 5% of total capital (not 5% of daily_alloc).
    # Prior formula used 5% of daily_alloc which was ~0.2% of capital — far too sensitive.
    _drawdown_pause_pct = getattr(config, 'CRYPTO_15M_SESSION_DRAWDOWN_PAUSE_PCT', 0.05)
    if session_pnl < -_drawdown_pause_pct * capital:
        return {'block': 'DRAWDOWN_PAUSE', 'okx_volume_pct': okx_volume_pct}

    # R9: Macro event (reuse from main cycle if available)
    try:
        from ruppert_cycle import has_macro_event_within
        if has_macro_event_within(minutes=30):
            return {'block': 'MACRO_EVENT_RISK', 'okx_volume_pct': okx_volume_pct}
    except (ImportError, AttributeError):
        pass  # Not available in all contexts

    # R10: Coinbase-OKX basis
    coinbase_price = fetch_coinbase_price(asset)
    okx_price = fetch_okx_price(symbol)

    if coinbase_price is None:
        # Kalshi settles on Coinbase price — can't validate basis without it.
        # Block entry rather than proceed blind.
        logger.warning('[crypto_15m] Coinbase price unavailable for %s — blocking entry (COINBASE_UNAVAILABLE)', asset)
        return {'block': 'COINBASE_UNAVAILABLE', 'okx_volume_pct': okx_volume_pct}

    if okx_price and okx_price > 0:
        basis = abs(coinbase_price - okx_price) / okx_price
        _max_basis = getattr(config, 'CRYPTO_15M_MAX_BASIS_PCT', 0.0015)
        if basis > _max_basis:
            return {'block': 'BASIS_RISK', 'okx_volume_pct': okx_volume_pct}

    return {'block': None, 'okx_volume_pct': okx_volume_pct}


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
    polymarket_yes_price: float | None = None,
    polymarket_fetched_at: str | None = None,
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
        'polymarket_yes_price': polymarket_yes_price,
        'polymarket_fetched_at': polymarket_fetched_at,
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
    for prefix in ('KXBTC15M', 'KXETH15M', 'KXXRP15M', 'KXDOGE15M', 'KXSOL15M'):
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
    dollar_oi: float = 0.0,
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
    from agents.ruppert.data_scientist.capital import get_capital
    from agents.ruppert.data_scientist.logger import log_trade, log_activity, get_daily_exposure
    from agents.ruppert.data_analyst.kalshi_client import KalshiClient
    from agents.ruppert.trader.utils import load_traded_tickers, push_alert

    asset = _parse_asset_from_ticker(ticker)
    if not asset:
        return

    symbol = ASSET_SYMBOLS.get(asset)
    if not symbol:
        return

    _module_name = ASSET_MODULE_NAMES[asset]

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
    _entry_cutoff = getattr(config, 'CRYPTO_15M_ENTRY_CUTOFF_SECS', 660)
    _secondary_start = getattr(config, 'CRYPTO_15M_SECONDARY_START_SECS', 480)

    _early_cutoff = getattr(config, 'CRYPTO_15M_EARLY_WINDOW_SECS', 120)
    if elapsed_secs < _early_cutoff:
        _log_decision(ticker, window_open_ts, window_close_ts, elapsed_secs,
                       {}, {'yes_ask': yes_ask, 'yes_bid': yes_bid, 'spread': yes_ask - yes_bid, 'book_depth_usd': book_depth_usd},
                       'SKIP', 'EARLY_WINDOW', None, None, None)
        return

    elif elapsed_secs <= _secondary_start:
        pass  # primary window, use base min_edge

    elif elapsed_secs <= _entry_cutoff:
        _secondary_edge_mult = getattr(config, 'CRYPTO_15M_SECONDARY_EDGE_MULTIPLIER', 1.25)
        min_edge = min_edge * _secondary_edge_mult  # secondary window, harder threshold

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

    # ── Shadow: Polymarket consensus price (logging only, no weight change) ──
    import time as _time
    _poly_result  = None
    _poly_fetched = None
    try:
        _poly_result  = get_crypto_consensus(asset)
        _poly_fetched = _time.time()
    except Exception as _poly_err:
        logger.warning('[crypto_15m] Polymarket shadow fetch failed: %s', _poly_err)

    _STALE_SECS = 600
    if _poly_result and _poly_fetched and (_time.time() - _poly_fetched) <= _STALE_SECS:
        polymarket_yes_price  = _poly_result.get("yes_price")
        polymarket_fetched_at = datetime.fromtimestamp(_poly_fetched, tz=timezone.utc).isoformat()
    else:
        polymarket_yes_price  = None
        polymarket_fetched_at = None
    # ── End Polymarket shadow ──

    # ── Composite Score → Probability ──
    raw_score = W_TFI * tfi_z + W_OBI * obi_z + W_MACD * macd_z + W_OI * oi_z
    scale = getattr(config, 'CRYPTO_15M_SIGMOID_SCALE', 1.0)
    P_directional = 1.0 / (1.0 + math.exp(-scale * raw_score))

    # ── Bias Filters ──
    fr_z = get_funding_z(asset)
    funding_mult = 1.0
    _funding_z_threshold = getattr(config, 'CRYPTO_15M_FUNDING_Z_THRESHOLD', 2.0)
    _funding_bearish_mult = getattr(config, 'CRYPTO_15M_FUNDING_BEARISH_MULT', 0.85)
    _funding_bullish_mult = getattr(config, 'CRYPTO_15M_FUNDING_BULLISH_MULT', 1.15)
    if fr_z is not None:
        if fr_z > _funding_z_threshold:
            funding_mult = _funding_bearish_mult
        elif fr_z < -_funding_z_threshold:
            funding_mult = _funding_bullish_mult

    P_biased = P_directional * funding_mult

    # Polymarket divergence nudge — intentionally disabled (shadow only)
    poly_nudge = 0.0

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
    risk_result = check_risk_filters(
        symbol=symbol,
        asset=asset,
        raw_score=raw_score,
        yes_ask=yes_ask,
        yes_bid=yes_bid,
        book_depth_usd=book_depth_usd,
        tfi_stale=tfi['stale'],
        obi_stale=obi['stale'],
        fr_z=fr_z,
        dollar_oi=dollar_oi,
    )
    block_reason = risk_result['block']
    okx_volume_pct = risk_result['okx_volume_pct']  # used for data quality tagging

    if block_reason:
        _log_decision(ticker, window_open_ts, window_close_ts, elapsed_secs,
                       signals, kalshi_info, 'SKIP', block_reason, None, None, None)
        return

    # ── Data Quality Tagging ──
    # Compare actual values against original PROD thresholds to classify trade quality.
    # These constants define "clean" data regardless of what config is currently set to.
    # Priority when multiple thresholds are relaxed: thin_market > wide_spread > low_liquidity
    _STRICT_MAX_SPREAD        = 8      # original R2 production threshold
    _STRICT_THIN_MARKET_RATIO = 0.25   # original R4 production threshold
    _STRICT_LIQUIDITY_MIN_PCT = 0.003  # original R3 production threshold

    spread = yes_ask - yes_bid

    spread_clean = spread <= _STRICT_MAX_SPREAD

    thin_mkt_clean = (
        okx_volume_pct is None  # couldn't fetch — treat as unknown, don't penalize
        or okx_volume_pct >= _STRICT_THIN_MARKET_RATIO
    )

    strict_min_depth = (
        max(dollar_oi * _STRICT_LIQUIDITY_MIN_PCT, 50.0) if dollar_oi > 0 else 100.0
    )
    liquidity_clean = book_depth_usd >= strict_min_depth

    if not thin_mkt_clean:
        data_quality = 'thin_market'
    elif not spread_clean:
        data_quality = 'wide_spread'
    elif not liquidity_clean:
        data_quality = 'low_liquidity'
    else:
        data_quality = 'standard'

    # Can't confirm standard quality without OKX volume data
    if data_quality == 'standard' and okx_volume_pct is None:
        data_quality = 'unknown'

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
                       max(edge_yes, edge_no), None, None,
                       polymarket_yes_price=polymarket_yes_price,
                       polymarket_fetched_at=polymarket_fetched_at)
        return

    # ── Capital + Cap Constants ──
    capital = get_capital()
    window_cap      = capital * getattr(config, 'CRYPTO_15M_WINDOW_CAP_PCT', 0.02)
    daily_wager_cap = capital * getattr(config, 'CRYPTO_15M_DAILY_WAGER_CAP_PCT', 0.40)
    cb_n            = getattr(config, 'CRYPTO_15M_CIRCUIT_BREAKER_N', 3)
    cb_advisory     = getattr(config, 'CRYPTO_15M_CIRCUIT_BREAKER_ADVISORY', True)

    # Strategy gate: global 70% deployment cap + strategy filters
    from agents.ruppert.data_scientist.logger import get_daily_exposure as _get_exp, get_daily_wager as _get_wager
    _deployed_today  = _get_exp()
    _agg_wager_today = sum(_get_wager(m) for m in _ALL_CRYPTO_15M_MODULES)   # aggregate all crypto_dir_15m_* modules
    _module_deployed_pct = _agg_wager_today / capital if capital > 0 else 0.0    # passed to should_enter backstop
    from agents.ruppert.data_scientist.capital import get_buying_power as _get_bp
    _bp = _get_bp()
    _signal_dict = {
        'ticker': ticker,
        'side': direction,
        'edge': round(edge, 4),
        'win_prob': round(P_win, 4),
        'confidence': round(abs(raw_score), 3),
        'module': _module_name,
        'yes_ask': yes_ask,
        'yes_bid': yes_bid,
        'hours_to_settlement': max(0, (900 - elapsed_secs) / 3600),
        'open_position_value': max(0.0, capital - _bp),
    }
    _se_decision = should_enter(
        _signal_dict, capital, _deployed_today,
        module=_module_name,
        module_deployed_pct=_module_deployed_pct,
        traded_tickers=None,
    )
    if not _se_decision['enter']:
        _log_decision(ticker, window_open_ts, window_close_ts, elapsed_secs,
                      signals, kalshi_info, 'SKIP', f'STRATEGY_GATE:{_se_decision["reason"]}',
                      edge, entry_price, None)
        return

    # ── Position Sizing: Half-Kelly, capped ──
    c = entry_price / 100.0
    denom = c * (1.0 - c)
    if denom <= 0:
        return

    kelly_full = (P_win - c) / denom
    kelly_half = kelly_full / 2.0

    _hard_cap  = getattr(config, 'CRYPTO_15M_DIR_HARD_CAP_USD', 100.0)
    _min_size  = getattr(config, 'CRYPTO_15M_DIR_MIN_POSITION_USD', 5.0)

    position_usd = min(
        kelly_half * capital,
        capital * getattr(config, 'MAX_POSITION_PCT', 0.01),
        _hard_cap,
    )
    position_usd = max(position_usd, _min_size)

    if position_usd < _min_size:
        _log_decision(ticker, window_open_ts, window_close_ts, elapsed_secs,
                       signals, kalshi_info, 'SKIP', 'SIZE_TOO_SMALL',
                       edge, entry_price, position_usd)
        return

    # ── Three-Tier Cap Check (race-safe, inside lock) ──
    # Required global declarations — without these, Python raises UnboundLocalError
    # on assignment to module-level variables inside this function.
    global _cb_last_window_ts
    global _daily_wager, _daily_wager_date, _window_exposure

    _skip_reason = None
    # ISSUE-105: Step 1 — declare before lock; will be set inside lock if trade proceeds
    actual_spend = None
    contracts    = None

    with _window_lock:

        # --- Re-read CB state from unified file on each window transition ---
        # post_trade_monitor updates the state FILE after each settled window.
        # Re-read fresh from disk on window change to catch updates written externally.
        win_key = window_open_ts or 'unknown'
        if win_key != _cb_last_window_ts:
            _cb_last_window_ts = win_key
        _cb_consecutive_losses = circuit_breaker.get_consecutive_losses(_module_name)

        # --- Check 0: Circuit breaker ---
        if _cb_consecutive_losses >= cb_n:
            if cb_advisory:
                logger.warning(
                    '[crypto_15m] CIRCUIT BREAKER advisory: %d consecutive complete-loss windows '
                    '(threshold=%d). Would halt but ADVISORY mode is on.',
                    _cb_consecutive_losses, cb_n,
                )
                # Do NOT set _skip_reason — advisory mode continues trading
            else:
                _skip_reason = 'CIRCUIT_BREAKER'

        if not _skip_reason:
            # --- Check 1: Tier 2 daily wager backstop ---
            # PHASE 2 (2026-03-31): Daily caps removed. CB is the daily hard stop.
            # Backstop disabled via config flag. Still tracking _daily_wager for metrics.
            today_str = circuit_breaker._today_pdt()
            if _daily_wager_date != today_str:
                _daily_wager = 0.0
                _daily_wager_date = today_str

            _backstop_enabled = getattr(config, 'CRYPTO_15M_DIR_DAILY_BACKSTOP_ENABLED', False)
            if _backstop_enabled and _daily_wager + position_usd > daily_wager_cap:
                trimmed = daily_wager_cap - _daily_wager
                if trimmed < 5.0:
                    _skip_reason = 'DAILY_WAGER_BACKSTOP'
                else:
                    position_usd = trimmed

        if not _skip_reason:
            # --- Check 2: Tier 1 window cap ---
            win_exp = _window_exposure.get(win_key, 0.0)

            if win_exp + position_usd > window_cap:
                trimmed = window_cap - win_exp
                if trimmed < 5.0:
                    _skip_reason = 'WINDOW_CAP'
                else:
                    position_usd = trimmed

        if not _skip_reason:
            # ISSUE-105: compute contracts INSIDE lock using final post-trim position_usd
            # Step 2: Compute contracts from FINAL post-trim position_usd
            _contracts = max(1, int(position_usd / (entry_price / 100.0)))
            # Step 3: Compute actual_spend = contracts × entry_price/100
            _actual_spend = _contracts * (entry_price / 100.0)
            # Step 4: Reserve actual_spend (not position_usd)
            _window_exposure[win_key] = _window_exposure.get(win_key, 0.0) + _actual_spend
            _daily_wager += _actual_spend
            # Step 5: Expose to enclosing scope for rollback and log record
            actual_spend = _actual_spend
            contracts = _contracts

    # --- Outside lock ---
    if _skip_reason:
        _log_decision(ticker, window_open_ts, window_close_ts, elapsed_secs,
                       signals, kalshi_info, 'SKIP', _skip_reason,
                       edge, entry_price, None)
        return

    # ── Execute ──
    # ISSUE-105: contracts and actual_spend set inside lock above; do NOT recompute here

    print(f"  [15m Crypto] {ticker} {direction.upper()} | P={P_final:.2f} edge={edge:+.1%} | ${position_usd:.2f}")

    _dry_run = getattr(config, 'DRY_RUN', True)
    if _dry_run:
        order_result = {'dry_run': True, 'status': 'simulated'}
    else:
        from agents.ruppert.env_config import require_live_enabled
        require_live_enabled()
        try:
            client = KalshiClient()
            order_result = client.place_order(ticker, direction, entry_price, contracts)
        except Exception as e:
            print(f"  [15m Crypto] Order failed: {e}")
            _log_decision(ticker, window_open_ts, window_close_ts, elapsed_secs,
                           signals, kalshi_info, 'SKIP', f'ORDER_FAILED:{e}',
                           edge, entry_price, actual_spend)
            # ISSUE-105: Release reservation on order failure — use actual_spend
            with _window_lock:
                _window_exposure[win_key] = max(0.0, _window_exposure.get(win_key, 0.0) - actual_spend)
                _daily_wager = max(0.0, _daily_wager - actual_spend)
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
        'module': _module_name,
        'yes_ask': yes_ask,
        'yes_bid': yes_bid,
        'hours_to_settlement': max(0, (900 - elapsed_secs) / 3600),
        'action': 'buy',
        'contracts': contracts,
        'size_dollars': round(actual_spend, 2),  # ISSUE-105: use actual_spend (post-floor rounding)
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'date': str(date.today()),
        'scan_price': entry_price,
        'fill_price': entry_price,
        'window_open_ts': window_open_ts,                         # for get_window_exposure() re-hydration
        # ── Data quality tags (for Optimizer / Data Scientist segmentation) ──
        'data_quality':          data_quality,
        'okx_volume_pct':        okx_volume_pct,                  # float ratio, e.g. 0.12 = 12% of 30d avg
        'kalshi_book_depth_usd': round(book_depth_usd, 2),        # USD depth at entry
        'kalshi_spread_cents':   yes_ask - yes_bid,               # spread in cents at entry
    }

    log_trade(opp, actual_spend, contracts, order_result)  # ISSUE-105: use actual_spend
    log_activity(f'[15M-CRYPTO] Entered {ticker} {direction.upper()} @ {entry_price}c | edge={edge:+.1%} P={P_final:.2f}')
    push_alert('trade', f'15M Crypto: {ticker} {direction.upper()} @ {entry_price}c', ticker=ticker)

    # ── Track position for WS exit monitoring ──
    try:
        from agents.ruppert.trader import position_tracker
        fill_price = entry_price
        fill_contracts = contracts
        if not _dry_run and order_result and isinstance(order_result, dict):
            fill_price = int(order_result.get('price', order_result.get('yes_price', entry_price)) or entry_price)
            fill_contracts = int(order_result.get('contracts', order_result.get('count', contracts)) or contracts)
        fill_price_pt = fill_price if fill_price else entry_price
        fill_contracts_pt = fill_contracts if fill_contracts else contracts
        # entry_secs_in_window: elapsed_secs is seconds since window open (computed above)
        # contract_remaining_at_entry: seconds left on contract at entry time
        _contract_remaining = (close_dt - now).total_seconds() if close_dt is not None else None
        position_tracker.add_position(
            ticker, fill_contracts_pt, direction, fill_price_pt,
            module=_module_name,
            title=f'{asset} 15m direction',
            entry_raw_score=raw_score,
            size_dollars=round(position_usd, 2),
            entry_secs_in_window=elapsed_secs if elapsed_secs > 0 else None,
            contract_remaining_at_entry=_contract_remaining,
        )
    except Exception as _pt_err:
        logger.warning(f'[15m] position_tracker.add_position failed: {_pt_err}')

    # ── Log decision ──
    _log_decision(ticker, window_open_ts, window_close_ts, elapsed_secs,
                   signals, kalshi_info,
                   'ENTER', None,
                   edge, entry_price, position_usd,
                   polymarket_yes_price=polymarket_yes_price,
                   polymarket_fetched_at=polymarket_fetched_at)

