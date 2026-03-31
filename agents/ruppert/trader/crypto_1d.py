"""
crypto_1d.py — Daily crypto above/below trading module.

Trades KXBTCD (BTC above/below) and KXETHD (ETH above/below) on Kalshi.
Uses 4 daily-scale signals: 24h momentum, funding rate regime, ATR band
selector, and OI regime (disk-persisted 24h snapshot).

Entry windows:
  Primary:   09:30–11:30 ET
  Secondary: 13:30–14:30 ET (gated by global exposure and 1.5× edge)
  No entry after 15:00 ET (2h before 17:00 settlement)

Run via: python ruppert_cycle.py crypto_1d
Triggered by: Ruppert-Crypto1D Windows Task Scheduler task
"""

import json
import math
import logging
import sys
import requests
from datetime import datetime, date, timezone, timedelta
from pathlib import Path

# Resolve workspace root and add to path
_CRYPTO_1D_AGENTS = Path(__file__).parent.parent.parent   # workspace/agents
_CRYPTO_1D_WORKSPACE = _CRYPTO_1D_AGENTS.parent           # workspace/
_CRYPTO_1D_ENV = _CRYPTO_1D_WORKSPACE / 'environments' / 'demo'
for _p in [str(_CRYPTO_1D_WORKSPACE), str(_CRYPTO_1D_ENV)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

import config
from agents.ruppert.data_scientist.logger import log_activity
from agents.ruppert.data_scientist.capital import get_capital, get_buying_power
from agents.ruppert.data_scientist.logger import get_daily_exposure
from agents.ruppert.data_analyst.kalshi_client import KalshiClient
from agents.ruppert.env_config import get_paths as _get_paths

logger = logging.getLogger(__name__)

# ─────────────────────────── Constants ────────────────────────────────────────

ASSETS_PHASE1 = ['BTC', 'ETH']   # Phase 1: live at launch (David approved)
ASSETS_PHASE2 = ['SOL']          # Phase 2: after 20-trade calibration

KALSHI_SERIES = {
    'BTC': 'KXBTCD',
    'ETH': 'KXETHD',
    'SOL': 'KXSOLD',   # Phase 2, wired but gated
}
OKX_SYMBOLS = {
    'BTC': 'BTC-USDT-SWAP',
    'ETH': 'ETH-USDT-SWAP',
    'SOL': 'SOL-USDT-SWAP',
}
BINANCE_SYMBOLS = {
    'BTC': 'BTCUSDT',
    'ETH': 'ETHUSDT',
    'SOL': 'SOLUSDT',
}

OKX_API = 'https://www.okx.com/api/v5'

_LOGS_DIR = _get_paths()['logs']
_LOGS_DIR.mkdir(exist_ok=True)
OI_SNAPSHOT_PATH = _LOGS_DIR / 'oi_1d_snapshot.json'
DECISION_LOG_PATH = _LOGS_DIR / 'decisions_1d.jsonl'

PRIMARY_WINDOW_START_ET   = '09:30'
PRIMARY_WINDOW_END_ET     = '11:30'
SECONDARY_WINDOW_START_ET = '13:30'
SECONDARY_WINDOW_END_ET   = '14:30'
NO_ENTRY_AFTER_ET         = '15:00'

# ATR high-vol thresholds per asset (as fraction of price)
HIGH_VOL_THRESHOLD = {
    'BTC': 0.03,
    'ETH': 0.04,
    'SOL': 0.05,
}

# ─────────────────────────── OKX Data Fetch ───────────────────────────────────

def fetch_daily_candle(symbol: str, lookback: int = 30) -> list:
    """
    Fetch daily OHLCV candles from OKX for momentum and ATR computation.

    Returns list of dicts (oldest first):
      [{'ts': int, 'open': float, 'high': float, 'low': float,
        'close': float, 'vol': float}, ...]
    Raises on HTTP error.
    """
    try:
        r = requests.get(
            f'{OKX_API}/market/candles',
            params={'instId': symbol, 'bar': '1D', 'limit': lookback},
            timeout=15,
        )
        r.raise_for_status()
        resp = r.json()
        raw = resp.get('data', [])
        # OKX returns newest first — reverse to oldest-first
        candles = []
        for c in reversed(raw):
            candles.append({
                'ts':    int(c[0]),
                'open':  float(c[1]),
                'high':  float(c[2]),
                'low':   float(c[3]),
                'close': float(c[4]),
                'vol':   float(c[5]),
            })
        return candles
    except Exception as e:
        logger.warning('fetch_daily_candle failed for %s: %s', symbol, e)
        raise


def fetch_okx_oi(symbol: str) -> float:
    """
    Fetch current open interest (in coin units) from OKX.
    Returns 0.0 on failure.
    """
    try:
        r = requests.get(
            f'{OKX_API}/public/open-interest',
            params={'instType': 'SWAP', 'instId': symbol},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json().get('data', [])
        if data:
            return float(data[0].get('oiCcy', 0))
    except Exception as e:
        logger.warning('fetch_okx_oi failed for %s: %s', symbol, e)
    return 0.0


# ─────────────────────────── ATR ──────────────────────────────────────────────

def compute_atr(ohlc_data: list, period: int = 14) -> float:
    """
    Compute ATR-14 from daily OHLC data.
    Returns ATR_pct = ATR / current_price (normalized).
    """
    if len(ohlc_data) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(ohlc_data)):
        h = ohlc_data[i]['high']
        l = ohlc_data[i]['low']
        prev_c = ohlc_data[i - 1]['close']
        tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        trs.append(tr)
    if len(trs) < period:
        return 0.0
    atr = sum(trs[-period:]) / period
    current_price = ohlc_data[-1]['close']
    if current_price <= 0:
        return 0.0
    return atr / current_price


def _z_score_series(values: list) -> float:
    """Compute z-score of last value vs rest of the series."""
    if len(values) < 3:
        return 0.0
    hist = values[:-1]
    mean = sum(hist) / len(hist)
    variance = sum((x - mean) ** 2 for x in hist) / len(hist)
    std = math.sqrt(variance) if variance > 0 else 1e-8
    return (values[-1] - mean) / std


# ─────────────────────────── Signal 1: Momentum ───────────────────────────────

def compute_s1_momentum(candles: list) -> dict:
    """
    Signal 1 — 24h price momentum.
    Returns {'pct_24h', 'z_score', 'regime', 'raw_score'}.
    """
    if len(candles) < 3:
        return {'pct_24h': 0.0, 'z_score': 0.0, 'regime': 'neutral', 'raw_score': 0.0}

    prev_close = candles[-2]['close']
    curr_close = candles[-1]['close']
    pct_24h = (curr_close - prev_close) / prev_close if prev_close > 0 else 0.0

    # 30-day daily returns
    daily_returns = []
    for i in range(1, len(candles)):
        pc = candles[i - 1]['close']
        cc = candles[i]['close']
        if pc > 0:
            daily_returns.append((cc - pc) / pc)

    if len(daily_returns) >= 3:
        mean_ret = sum(daily_returns[:-1]) / max(len(daily_returns) - 1, 1)
        var_ret = sum((x - mean_ret) ** 2 for x in daily_returns[:-1]) / max(len(daily_returns) - 1, 1)
        std_ret = math.sqrt(var_ret) if var_ret > 0 else 1e-8
        z_score = (pct_24h - mean_ret) / std_ret
    else:
        z_score = 0.0

    # Regime classification
    az = abs(z_score)
    if z_score > 3.0:
        regime = 'extreme_up'
    elif z_score > 1.5:
        regime = 'strong_up'
    elif z_score > 0.5:
        regime = 'weak_up'
    elif z_score < -3.0:
        regime = 'extreme_down'
    elif z_score < -1.5:
        regime = 'strong_down'
    elif z_score < -0.5:
        regime = 'weak_down'
    else:
        regime = 'neutral'

    # raw_score: z clamped to [-2, 2], scaled to [-1, 1]
    clamped = max(-2.0, min(2.0, z_score))
    raw_score = clamped / 2.0

    return {
        'pct_24h': round(pct_24h, 6),
        'z_score': round(z_score, 3),
        'regime': regime,
        'raw_score': round(raw_score, 4),
    }


# ─────────────────────────── Signal 2: Funding ────────────────────────────────

def compute_s2_funding(asset: str) -> dict:
    """
    Signal 2 — funding rate regime via Binance Futures.
    Returns {'funding_24h_cumulative', 'funding_24h_z', 'regime', 'raw_score', 'filter_skip'}.
    """
    binance_symbol = BINANCE_SYMBOLS.get(asset, f'{asset}USDT')
    try:
        from agents.ruppert.trader.crypto_client import _compute_funding_z_scores
        result = _compute_funding_z_scores(binance_symbol, return_cumulative=True)
    except Exception as e:
        logger.warning('compute_s2_funding: failed to fetch funding data for %s: %s', asset, e)
        return {
            'funding_24h_cumulative': 0.0,
            'funding_24h_z': 0.0,
            'regime': 'neutral',
            'raw_score': 0.0,
            'filter_skip': False,
        }

    cumulative = result.get('funding_24h_cumulative', 0.0)
    funding_z = result.get('funding_24h_z', 0.0)

    # Risk filter R6: extreme funding rate regime
    filter_skip = abs(funding_z) > 3.5

    # Regime classification (contrarian: high positive funding = crowded longs = bearish)
    if funding_z > 2.0:
        regime = 'bull_overheat'
    elif funding_z < -2.0:
        regime = 'bear_overheat'
    else:
        regime = 'neutral'

    # raw_score: positive funding (longs paying) → mild bearish signal
    # Negate so positive funding → negative raw_score (bearish)
    raw_score = max(-1.0, min(1.0, -funding_z / 3.0))

    return {
        'funding_24h_cumulative': round(cumulative, 8),
        'funding_24h_z': round(funding_z, 3),
        'regime': regime,
        'raw_score': round(raw_score, 4),
        'filter_skip': filter_skip,
    }


# ─────────────────────────── Signal 3: ATR Band ───────────────────────────────

def compute_s3_atr_band(asset: str, candles: list, current_price: float) -> dict:
    """
    Signal 3 — ATR band selector and strike confidence.
    Returns {'ATR_14', 'ATR_pct', 'ATR_pct_z', 'above_confidence', 'atr_size_mult', 'high_vol_day'}.
    """
    if len(candles) < 15:
        return {
            'ATR_14': 0.0, 'ATR_pct': 0.0, 'ATR_pct_z': 0.0,
            'above_confidence': 0.5, 'atr_size_mult': 1.0, 'high_vol_day': False,
            'raw_score': 0.0,
        }

    # Compute rolling ATR_pct over each day's window
    period = 14
    atr_pct_series = []
    for end in range(period + 1, len(candles) + 1):
        window = candles[:end]
        ap = compute_atr(window, period)
        atr_pct_series.append(ap)

    current_atr_pct = atr_pct_series[-1] if atr_pct_series else 0.0

    # ATR_14 in price terms
    atr_14 = current_atr_pct * current_price

    # z-score of current ATR_pct vs 30-day history
    if len(atr_pct_series) >= 3:
        atr_pct_z = _z_score_series(atr_pct_series)
    else:
        atr_pct_z = 0.0

    # Sizing multiplier based on ATR_pct_z
    if atr_pct_z > 1.0:
        atr_size_mult = max(0.5, min(1.2, 1.0 - (atr_pct_z - 1.0) * 0.15))
    elif atr_pct_z <= 0:
        atr_size_mult = min(1.2, 1.0 + abs(atr_pct_z) * 0.1)
    else:
        atr_size_mult = 1.0

    # High vol day
    hv_threshold = HIGH_VOL_THRESHOLD.get(asset, 0.04)
    high_vol_day = current_atr_pct > hv_threshold

    # above_confidence: 0.5 baseline (ATR band doesn't directly yield direction)
    above_confidence = 0.5

    # raw_score: S3 is primarily a sizing/confidence signal, not directional
    # Use 0 as raw_score (direction comes from S1/S2/S4)
    raw_score = 0.0

    return {
        'ATR_14': round(atr_14, 4),
        'ATR_pct': round(current_atr_pct, 6),
        'ATR_pct_z': round(atr_pct_z, 3),
        'above_confidence': above_confidence,
        'atr_size_mult': round(atr_size_mult, 3),
        'high_vol_day': high_vol_day,
        'raw_score': raw_score,
    }


# ─────────────────────────── OI Snapshot ──────────────────────────────────────

def cache_oi_snapshot(asset: str, current_oi: float, write: bool = False) -> dict:
    """
    Read/write oi_1d_snapshot.json for OI regime computation.

    When write=False (default): returns existing snapshot entry for asset.
    When write=True: updates the snapshot with current_oi + timestamp.

    Returns:
      {'oi': float|None, 'timestamp': str|None, 'bootstrap': bool, 'stale': bool}
    """
    snapshot_path = OI_SNAPSHOT_PATH

    # ── Write mode ─────────────────────────────────────────────────────────────
    if write:
        try:
            data = {}
            if snapshot_path.exists():
                data = json.loads(snapshot_path.read_text(encoding='utf-8'))
            data[asset] = {
                'oi': current_oi,
                'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            }
            snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            snapshot_path.write_text(json.dumps(data, indent=2), encoding='utf-8')
            logger.info('OI snapshot written: %s oi=%.2f', asset, current_oi)
        except Exception as e:
            logger.warning('cache_oi_snapshot write failed for %s: %s', asset, e)
        return {}

    # ── Read mode ──────────────────────────────────────────────────────────────
    if not snapshot_path.exists():
        return {'oi': None, 'timestamp': None, 'bootstrap': True, 'stale': False}

    try:
        data = json.loads(snapshot_path.read_text(encoding='utf-8'))
        entry = data.get(asset)
        if not entry:
            return {'oi': None, 'timestamp': None, 'bootstrap': True, 'stale': False}

        oi_val = entry.get('oi')
        ts_str = entry.get('timestamp')
        stale = False

        if ts_str:
            try:
                snap_dt = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                age_hours = (datetime.now(timezone.utc) - snap_dt).total_seconds() / 3600
                stale = age_hours > 26
                if stale:
                    logger.warning('OI snapshot stale for %s: age=%.1fh', asset, age_hours)
            except Exception:
                stale = True

        return {'oi': oi_val, 'timestamp': ts_str, 'bootstrap': False, 'stale': stale}

    except Exception as e:
        logger.warning('cache_oi_snapshot read failed for %s: %s', asset, e)
        return {'oi': None, 'timestamp': None, 'bootstrap': True, 'stale': False}


# ─────────────────────────── Signal 4: OI Regime ──────────────────────────────

def compute_s4_oi_regime(asset: str, current_oi: float, s1_regime: str = 'neutral') -> dict:
    """
    Signal 4 — OI regime from 24h snapshot delta.
    Returns {'OI_delta_24h', 'OI_regime', 'raw_score', 'weight_override'}.
    """
    snap = cache_oi_snapshot(asset, current_oi, write=False)

    # Bootstrap or stale handling
    if snap.get('bootstrap') or snap.get('oi') is None:
        return {
            'OI_delta_24h': 0.0,
            'OI_regime': 'neutral',
            'raw_score': 0.0,
            'weight_override': 0.20,  # full weight, neutral signal
        }

    if snap.get('stale'):
        logger.warning('S4 OI stale for %s — using neutral', asset)
        return {
            'OI_delta_24h': 0.0,
            'OI_regime': 'neutral',
            'raw_score': 0.0,
            'weight_override': 0.0,  # redistribute to S1/S2/S3
        }

    baseline_oi = snap['oi']
    if baseline_oi and baseline_oi > 0:
        oi_delta = (current_oi - baseline_oi) / baseline_oi
    else:
        oi_delta = 0.0

    # Determine regime by crossing with momentum direction
    price_rising = s1_regime in ('strong_up', 'weak_up', 'extreme_up')
    price_falling = s1_regime in ('strong_down', 'weak_down', 'extreme_down')
    oi_rising = oi_delta > 0.01   # >1% increase
    oi_falling = oi_delta < -0.01  # >1% decrease

    if oi_rising and price_rising:
        oi_regime = 'long_buildup'
    elif oi_rising and price_falling:
        oi_regime = 'short_buildup'
    elif oi_falling:
        oi_regime = 'unwind'
    else:
        oi_regime = 'neutral'

    # raw_score: scaled by delta magnitude
    delta_mag = min(abs(oi_delta), 0.10)  # cap at 10%
    scale = delta_mag / 0.10

    if oi_regime == 'long_buildup':
        raw_score = 0.5 * scale
    elif oi_regime == 'short_buildup':
        raw_score = -0.5 * scale
    else:
        raw_score = 0.0

    return {
        'OI_delta_24h': round(oi_delta, 6),
        'OI_regime': oi_regime,
        'raw_score': round(raw_score, 4),
        'weight_override': 0.20,
    }


# ─────────────────────────── Composite Score ──────────────────────────────────

def compute_composite_score(s1: dict, s2: dict, s3: dict, s4: dict) -> dict:
    """
    Combine 4 signals into composite directional score.
    Returns {'raw_composite', 'P_above', 'direction', 'confidence', 'skip_reason'}.
    """
    # Extreme funding risk filter
    if s2.get('filter_skip'):
        return {
            'raw_composite': 0.0,
            'P_above': 0.5,
            'direction': 'no_trade',
            'confidence': 0.0,
            'skip_reason': 'extreme_funding',
        }

    # Base weights
    w4 = s4.get('weight_override', 0.20)
    remaining = 1.0 - w4
    if w4 == 0.0:
        # Redistribute proportionally to S1:S2:S3 = 0.30:0.25:0.25 ratio
        total_123 = 0.30 + 0.25 + 0.25  # = 0.80
        w1 = 0.30 / total_123
        w2 = 0.25 / total_123
        w3 = 0.25 / total_123
    else:
        w1 = 0.30
        w2 = 0.25
        w3 = 0.25

    raw_composite = (
        w1 * s1.get('raw_score', 0.0) +
        w2 * s2.get('raw_score', 0.0) +
        w3 * s3.get('raw_score', 0.0) +
        w4 * s4.get('raw_score', 0.0)
    )

    # P_above via sigmoid
    P_above = 1.0 / (1.0 + math.exp(-raw_composite * 3.0))

    # confidence
    confidence = min(1.0, abs(raw_composite))

    # Direction gate
    min_edge = getattr(config, 'CRYPTO_1D_MIN_EDGE', 0.08)
    half_edge = min_edge / 2.0

    if P_above > 0.5 + half_edge:
        direction = 'above'
    elif P_above < 0.5 - half_edge:
        direction = 'below'
    else:
        direction = 'no_trade'

    skip_reason = None
    if direction == 'no_trade':
        skip_reason = f'insufficient_edge (P_above={P_above:.3f})'

    return {
        'raw_composite': round(raw_composite, 4),
        'P_above': round(P_above, 4),
        'direction': direction,
        'confidence': round(confidence, 4),
        'skip_reason': skip_reason,
    }


# ─────────────────────────── Market Discovery ─────────────────────────────────

def discover_1d_markets(asset: str) -> list:
    """
    Discover available KXBTCD / KXETHD / KXSOLD above/below markets on Kalshi.
    Returns list of enriched markets sorted by abs(edge) descending.
    """
    series = KALSHI_SERIES.get(asset)
    if not series:
        return []

    try:
        client = KalshiClient()
        all_meta = client.get_markets_metadata(series, status='open')
        logger.info('discover_1d_markets: %s found %d markets', series, len(all_meta))
    except Exception as e:
        logger.warning('discover_1d_markets: failed to fetch markets for %s: %s', series, e)
        return []

    # Filter to markets expiring today at 17:00 ET settlement
    today_str = date.today().isoformat()  # 'YYYY-MM-DD'
    qualifying = []

    for m in all_meta:
        close_time = m.get('close_time', '') or m.get('expiration_time', '')
        if not close_time:
            # Accept if ticker contains today's date pattern
            qualifying.append(m)
            continue
        try:
            ct = datetime.fromisoformat(close_time.replace('Z', '+00:00'))
            # Settlement is 17:00 ET; close_time should be on today's date
            if ct.date().isoformat() == today_str:
                qualifying.append(m)
        except Exception:
            qualifying.append(m)

    # Enrich orderbooks
    for m in qualifying:
        try:
            client.enrich_orderbook(m)
        except Exception:
            pass

    # Apply liquidity filters: yes_ask in [5, 95], spread <= 12, depth >= $300
    filtered = []
    for m in qualifying:
        ya = m.get('yes_ask') or 0
        na = m.get('no_ask') or 0
        if ya < 5 or ya > 95:
            continue
        spread = ya + na - 100
        if spread > 12:
            continue
        depth = m.get('book_depth_usd') or m.get('open_interest', 0)
        # Note: book_depth_usd may not be populated; be lenient on depth check
        # if not populated (we'll check again in evaluate_crypto_1d_entry)
        filtered.append(m)

    # Sort by absolute implied edge (placeholder — select_best_strike does real edge)
    return filtered


# ─────────────────────────── Strike Selection ─────────────────────────────────

def select_best_strike(asset: str, P_above: float, markets: list,
                       direction: str = 'above') -> dict | None:
    """
    Pick the best above/below strike given model P_above estimate.
    Returns best market dict with 'edge' key, or None.
    """
    if not markets:
        return None

    # Skip if P_above is too extreme (very far from edge zone)
    if P_above < 0.15 or P_above > 0.85:
        logger.info('select_best_strike: P_above=%.3f outside tradeable zone', P_above)
        return None

    min_edge = getattr(config, 'CRYPTO_1D_MIN_EDGE', 0.08)
    best = None
    best_edge = -999.0

    for m in markets:
        ya = m.get('yes_ask') or 0
        na = m.get('no_ask') or 0
        ticker = m.get('ticker', '')

        if direction == 'above':
            # Buy YES: edge = model_P_yes - yes_ask/100
            model_yes = P_above
            edge = model_yes - (ya / 100.0)
            m['edge'] = round(edge, 4)
            m['side'] = 'yes'
            m['cost_cents'] = ya
        else:
            # direction == 'below': buy NO on above contracts
            # P(price below strike) = 1 - P_above
            model_no = 1.0 - P_above
            edge = model_no - (na / 100.0)
            m['edge'] = round(edge, 4)
            m['side'] = 'no'
            m['cost_cents'] = na

        if edge > best_edge and edge >= min_edge:
            best_edge = edge
            best = m

    return best


# ─────────────────────────── Cross-Module Guard ───────────────────────────────

def _cross_module_guard(asset: str, settlement_date: str) -> bool:
    """
    Returns True (safe to enter) if no other module holds an active position
    in any contract for this asset's daily settlement.

    Checks today's trade log for active positions tagged with:
    - asset matching (BTC, ETH, or SOL)
    - settlement_date matching today's date
    - module != 'crypto_1d'

    If any such position exists → return False (do not enter).
    """
    try:
        # Try position_tracker first (if available with filter support)
        from agents.ruppert.trader.position_tracker import get_active_positions
        active = get_active_positions(asset=asset, settlement_date=settlement_date)
        for pos in active:
            if pos.get('module') != 'crypto_1h_dir':
                logger.info(
                    'crypto_1h_dir cross-module guard: %s blocked by %s position in %s',
                    asset, pos.get('module'), pos.get('market_id', '?')
                )
                return False
        return True
    except (ImportError, TypeError):
        # position_tracker doesn't support filtered get_active_positions — fall back to trade log
        pass
    except Exception as e:
        logger.warning('cross_module_guard position_tracker error: %s — falling back to trade log', e)

    # Fallback: scan today's trade log for same-asset positions from other modules
    try:
        from agents.ruppert.env_config import get_paths as _get_paths
        trades_dir = _get_paths()['trades']
        trade_log = trades_dir / f'trades_{date.today().isoformat()}.jsonl'
        if not trade_log.exists():
            return True

        for line in trade_log.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue

            rec_action = rec.get('action', '')
            rec_asset = rec.get('asset', '')
            rec_module = rec.get('module', rec.get('source', ''))

            # Only check buy/open trades, same asset, different module
            if rec_action not in ('buy', 'open'):
                continue
            if rec_asset != asset:
                continue
            if rec_module == 'crypto_1h_dir':
                continue

            # Check if ticker is for daily series (KXBTCD / KXETHD / KXSOLD)
            ticker = rec.get('ticker', '')
            daily_series = KALSHI_SERIES.get(asset, '')
            if daily_series and ticker.startswith(daily_series):
                logger.info(
                    'crypto_1h_dir cross-module guard: %s blocked by %s position %s',
                    asset, rec_module, ticker
                )
                return False

    except Exception as e:
        logger.warning('cross_module_guard trade log fallback error: %s — allowing entry', e)

    return True


# ─────────────────────────── Position Sizing ──────────────────────────────────

def compute_position_size(capital: float, P_win: float, cost_cents: int,
                          ATR_pct_z: float) -> float:
    """
    Compute Half-Kelly position size with ATR modifier.
    Returns size in USD.
    """
    cost = cost_cents / 100.0
    if cost <= 0 or cost >= 1:
        return 10.0

    kelly_full = (P_win - cost) / (cost * (1.0 - cost)) if (cost * (1.0 - cost)) > 0 else 0.0
    kelly_half = kelly_full / 2.0

    # ATR modifier
    atr_mult = max(0.5, min(1.2, 1.0 - (ATR_pct_z - 1.0) * 0.15))

    position_usd = kelly_half * capital * atr_mult
    position_usd = min(position_usd, capital * getattr(config, 'CRYPTO_1D_WINDOW_CAP_PCT', 0.05))
    position_usd = min(position_usd, getattr(config, 'CRYPTO_1D_MAX_POSITION_USD', 200.0))
    position_usd = max(position_usd, 10.0)   # CRYPTO_1D_MIN_POSITION_USD

    return round(position_usd, 2)


# ─────────────────────────── Decision Log ─────────────────────────────────────

def _log_decision(asset: str, window: str, signals: dict, decision: str, reason: str,
                  market_id: str = None, size_usd: float = None,
                  composite: float = None, P_above: float = None, edge: float = None):
    """
    Append a structured entry to decisions_1d.jsonl.
    """
    entry = {
        'ts': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'asset': asset,
        'window': window,
        'market_id': market_id,
        'decision': decision,
        'reason': reason,
        'module': 'crypto_1h_dir',
    }

    if signals:
        s1 = signals.get('S1', {})
        s2 = signals.get('S2', {})
        s3 = signals.get('S3', {})
        s4 = signals.get('S4', {})
        entry['signals'] = {
            'S1': {'regime': s1.get('regime'), 'raw_score': s1.get('raw_score'),
                   'z_score': s1.get('z_score')},
            'S2': {'regime': s2.get('regime'), 'raw_score': s2.get('raw_score'),
                   'funding_24h_z': s2.get('funding_24h_z')},
            'S3': {'ATR_pct': s3.get('ATR_pct'), 'ATR_pct_z': s3.get('ATR_pct_z'),
                   'atr_size_mult': s3.get('atr_size_mult')},
            'S4': {'OI_regime': s4.get('OI_regime'), 'OI_delta_24h': s4.get('OI_delta_24h'),
                   'raw_score': s4.get('raw_score')},
        }

    if composite is not None:
        entry['composite'] = composite
    if P_above is not None:
        entry['P_above'] = P_above
    if edge is not None:
        entry['edge'] = edge
    if size_usd is not None:
        entry['size_usd'] = size_usd

    try:
        DECISION_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(DECISION_LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry) + '\n')
    except Exception as e:
        logger.warning('_log_decision: failed to write: %s', e)


# ─────────────────────────── Helpers ──────────────────────────────────────────

def get_today_settlement_date() -> str:
    """Return today's date as ISO string (YYYY-MM-DD)."""
    return date.today().isoformat()


def _skip(asset, window, reason, signals=None):
    """Return a skip result dict, optionally logging."""
    log_activity(f'[Crypto1D] SKIP {asset} ({window}): {reason}')
    if signals:
        _log_decision(asset, window, signals, 'SKIP', reason)
    else:
        _log_decision(asset, window, {}, 'SKIP', reason)
    return {'entered': False, 'ticker': None, 'size_usd': 0.0, 'reason': reason}


# ─────────────────────────── Main Entry Point ─────────────────────────────────

def evaluate_crypto_1d_entry(asset: str, window: str = 'primary') -> dict:
    """
    Main entry point — run all signals, apply risk filters, place order if qualified.
    Returns {'entered': bool, 'ticker': str|None, 'size_usd': float, 'reason': str}.
    """

    # 0. Validate asset
    if asset not in ASSETS_PHASE1:
        return _skip(asset, window, 'asset_not_in_phase1')

    # 1. Cross-module guard (runs before any signal computation)
    today_settlement = get_today_settlement_date()
    if not _cross_module_guard(asset, today_settlement):
        return _skip(asset, window, 'cross_module_guard')

    # 2. Capital / cap checks
    try:
        capital = get_capital()
    except Exception as e:
        capital = getattr(config, 'CAPITAL_FALLBACK', 10000.0)
        logger.warning('evaluate_crypto_1d_entry: get_capital() failed: %s — using fallback', e)

    try:
        asset_daily_deployed = get_daily_exposure(module='crypto_1h_dir', asset=asset)
    except TypeError:
        # get_daily_exposure may not support asset= kwarg — use module-only
        try:
            asset_daily_deployed = get_daily_exposure(module='crypto_1h_dir')
        except Exception:
            asset_daily_deployed = 0.0
    except Exception:
        asset_daily_deployed = 0.0

    per_asset_cap = capital * getattr(config, 'CRYPTO_1D_PER_ASSET_CAP_PCT', 0.03)
    if asset_daily_deployed >= per_asset_cap:
        return _skip(asset, window, 'per_asset_daily_cap')

    try:
        total_1d_deployed = get_daily_exposure(module='crypto_1h_dir')
    except Exception:
        total_1d_deployed = 0.0

    daily_cap = capital * getattr(config, 'CRYPTO_1D_DAILY_CAP_PCT', 0.15)
    if total_1d_deployed >= daily_cap:
        return _skip(asset, window, 'daily_cap_reached')

    # Secondary window: global exposure gate
    if window == 'secondary':
        try:
            buying_power = get_buying_power()
            global_exposure = max(0.0, capital - buying_power)
            global_exposure_pct = global_exposure / capital if capital > 0 else 0.0
            max_secondary_exposure = getattr(config, 'CRYPTO_1D_SECONDARY_MAX_EXPOSURE_PCT', 0.50)
            if global_exposure_pct >= max_secondary_exposure:
                log_activity(
                    f'[Crypto1D] secondary skipped: global exposure '
                    f'{global_exposure_pct:.1%} >= {max_secondary_exposure:.0%}'
                )
                return _skip(asset, window, 'secondary_global_exposure')
        except Exception as e:
            logger.warning('evaluate_crypto_1d_entry: global exposure check failed: %s', e)

    # 3. Fetch market data
    okx_symbol = OKX_SYMBOLS[asset]
    try:
        candles = fetch_daily_candle(okx_symbol, lookback=30)
    except Exception as e:
        return _skip(asset, window, f'candle_fetch_error: {e}')

    if len(candles) < 15:
        return _skip(asset, window, 'insufficient_candle_data')

    current_price = candles[-1]['close']

    # 4. Compute signals
    s1 = compute_s1_momentum(candles)
    s2 = compute_s2_funding(asset)
    s3 = compute_s3_atr_band(asset, candles, current_price)
    current_oi = fetch_okx_oi(okx_symbol)
    s4 = compute_s4_oi_regime(asset, current_oi, s1_regime=s1.get('regime', 'neutral'))

    signals_dict = {'S1': s1, 'S2': s2, 'S3': s3, 'S4': s4}

    # 5. Risk filters
    if s2.get('filter_skip'):
        return _skip(asset, window, 'R6_extreme_funding', signals_dict)

    # R1: extreme volatility
    atr_pct = s3.get('ATR_pct', 0.0)
    if atr_pct > HIGH_VOL_THRESHOLD.get(asset, 0.04):
        return _skip(asset, window, f'R1_extreme_vol (ATR_pct={atr_pct:.3f})', signals_dict)

    # 6. Composite score
    composite = compute_composite_score(s1, s2, s3, s4)
    if composite['direction'] == 'no_trade':
        return _skip(asset, window, composite.get('skip_reason', 'no_trade'), signals_dict)

    # 7. MIN_EDGE threshold (stricter for secondary window)
    min_edge = getattr(config, 'CRYPTO_1D_MIN_EDGE', 0.08)
    if window == 'secondary':
        min_edge = getattr(config, 'CRYPTO_1D_SECONDARY_MIN_EDGE', min_edge * 1.5)

    # 8. Discover markets and select strike
    markets = discover_1d_markets(asset)
    if not markets:
        return _skip(asset, window, 'no_markets_available', signals_dict)

    best = select_best_strike(asset, composite['P_above'], markets,
                              direction=composite['direction'])

    if best is None or best.get('edge', -999) < min_edge:
        edge_val = best.get('edge') if best else None
        reason = f'insufficient_edge (edge={edge_val} < min={min_edge})'
        _log_decision(
            asset, window, signals_dict, 'SKIP', reason,
            composite=composite['raw_composite'], P_above=composite['P_above'],
        )
        log_activity(f'[Crypto1D] SKIP {asset} ({window}): {reason}')
        return {'entered': False, 'ticker': None, 'size_usd': 0.0, 'reason': reason}

    # 9. Additional risk filters on selected market
    ya = best.get('yes_ask', 50) or 50
    na = best.get('no_ask', 50) or 50
    spread = ya + na - 100
    if spread > 12:
        return _skip(asset, window, f'R2_wide_spread (spread={spread})', signals_dict)

    book_depth = best.get('book_depth_usd', 0) or 0
    if book_depth > 0 and book_depth < 300:
        return _skip(asset, window, f'R3_thin_book (depth={book_depth})', signals_dict)

    # 10. Compute size
    side = best.get('side', 'yes')
    cost_cents = best.get('cost_cents') or (ya if side == 'yes' else na)
    P_win = composite['P_above'] if side == 'yes' else (1.0 - composite['P_above'])

    size_usd = compute_position_size(capital, P_win, cost_cents, s3.get('ATR_pct_z', 0.0))

    # Per-asset cap trim
    remaining = per_asset_cap - asset_daily_deployed
    size_usd = min(size_usd, remaining)
    if size_usd < 10.0:
        return _skip(asset, window, 'size_below_minimum', signals_dict)

    # 11. Place order
    contracts = max(1, int(size_usd / cost_cents * 100))
    actual_cost = round(contracts * cost_cents / 100.0, 2)
    market_id = best.get('ticker', '')

    trade_opp = {
        'ticker':      market_id,
        'title':       best.get('title', market_id),
        'side':        side,
        'action':      'buy',
        'yes_price':   best.get('yes_ask'),
        'market_prob': (best.get('yes_ask', 50)) / 100.0,
        'edge':        best.get('edge'),
        'confidence':  composite['confidence'],
        'size_dollars': actual_cost,
        'contracts':   contracts,
        'source':      'crypto_1d',
        'module':      'crypto_1h_dir',
        'asset':       asset,
        'window':      window,
        'scan_price':  cost_cents,
        'fill_price':  cost_cents,
        'note': (
            f"crypto_1d {asset} {window} "
            f"P_above={composite['P_above']:.2f} "
            f"edge={best.get('edge', 0):.2f}"
        ),
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'date': str(date.today()),
    }
    trade_opp['strategy_size'] = actual_cost

    try:
        from agents.ruppert.trader.trader import Trader
        dry_run = config.DRY_RUN
        result = Trader(dry_run=dry_run).execute_opportunity(trade_opp)
    except Exception as e:
        logger.error('evaluate_crypto_1d_entry: execute_opportunity failed: %s', e)
        result = None

    # 12. Post-trade: write OI snapshot
    cache_oi_snapshot(asset, current_oi, write=True)

    # 13. Log decision
    _log_decision(
        asset=asset, window=window, signals=signals_dict,
        decision='ENTER', market_id=market_id, size_usd=actual_cost,
        composite=composite['raw_composite'], P_above=composite['P_above'],
        edge=best.get('edge'),
        reason=(
            f"composite={composite['raw_composite']:.2f} "
            f"P_above={composite['P_above']:.2f} "
            f"edge={best.get('edge', 0):.2f} "
            f"size=${actual_cost:.2f}"
        ),
    )

    if result:
        log_activity(
            f'[Crypto1D] ENTERED {asset} {market_id} {side.upper()} '
            f'{contracts}@{cost_cents}c ${actual_cost:.2f}'
        )
        return {'entered': True, 'ticker': market_id, 'size_usd': actual_cost,
                'reason': 'trade_executed'}
    else:
        log_activity(f'[Crypto1D] execute_opportunity returned falsy for {market_id}')
        return {'entered': False, 'ticker': market_id, 'size_usd': 0.0,
                'reason': 'execute_failed'}
