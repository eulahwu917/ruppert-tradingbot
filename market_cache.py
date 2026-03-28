"""
market_cache.py — Shared in-memory price cache
All modules read from this instead of calling Kalshi REST for prices.
WS feed populates the cache; REST is fallback only.

Thread-safe: all reads/writes go through _lock.
Persistence: cache survives restarts via logs/price_cache.json.
"""

import time
import json
import logging
import threading
from pathlib import Path

import config as cfg

logger = logging.getLogger(__name__)

CACHE_FILE = Path(__file__).parent / 'logs' / 'price_cache.json'
STALE_THRESHOLD = getattr(cfg, 'WS_CACHE_STALE_SECONDS', 60)
PURGE_THRESHOLD = getattr(cfg, 'WS_CACHE_PURGE_SECONDS', 300)

_cache = {}         # {ticker: {bid, ask, updated_at, source}}
_lock = threading.Lock()


# ─────────────────────────────── Core API ─────────────────────────────────────

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
    if dead:
        logger.debug('[MarketCache] Purged %d stale entries', len(dead))


def snapshot() -> dict:
    """Return a shallow copy of the cache (for diagnostics)."""
    with _lock:
        return dict(_cache)


# ─────────────────────────────── Persistence ──────────────────────────────────

def persist():
    """Write cache to disk (call on graceful shutdown)."""
    with _lock:
        data = dict(_cache)
    try:
        CACHE_FILE.parent.mkdir(exist_ok=True)
        tmp = CACHE_FILE.with_suffix('.tmp')
        tmp.write_text(json.dumps(data), encoding='utf-8')
        tmp.replace(CACHE_FILE)
        logger.debug('[MarketCache] Persisted %d entries to disk', len(data))
    except Exception as e:
        logger.warning('[MarketCache] Persist failed: %s', e)


def load():
    """Load cache from disk on startup (stale entries will fall back to REST naturally)."""
    if not CACHE_FILE.exists():
        return
    try:
        data = json.loads(CACHE_FILE.read_text(encoding='utf-8'))
        with _lock:
            _cache.update(data)
        logger.info('[MarketCache] Loaded %d entries from disk', len(data))
    except Exception as e:
        logger.warning('[MarketCache] Load failed: %s', e)


# ─────────────────────────────── Helper ───────────────────────────────────────

def get_market_price(ticker: str, fallback_client=None) -> dict | None:
    """
    Cache-first price lookup. Returns {yes_bid, yes_ask, no_bid, no_ask, source}
    in cent integers, or None.
    Falls back to REST via fallback_client if cache is stale/missing.
    """
    bid_d, ask_d, is_stale = get_with_staleness(ticker)
    if not is_stale and bid_d is not None:
        return {
            'yes_bid': round(bid_d * 100),
            'yes_ask': round(ask_d * 100),
            'no_bid':  round((1 - ask_d) * 100),
            'no_ask':  round((1 - bid_d) * 100),
            'source': 'ws_cache',
        }
    # Stale or missing — fall back to REST
    if fallback_client:
        try:
            market = fallback_client.get_market(ticker)
            if market:
                bid = market.get('yes_bid_dollars', 0)
                ask = market.get('yes_ask_dollars', 0)
                if bid and ask:
                    update(ticker, float(bid), float(ask), source='rest')
                return {
                    'yes_bid': round(float(bid) * 100) if bid else None,
                    'yes_ask': round(float(ask) * 100) if ask else None,
                    'no_bid':  round((1 - float(ask)) * 100) if ask else None,
                    'no_ask':  round((1 - float(bid)) * 100) if bid else None,
                    'source': 'rest',
                }
        except Exception:
            pass
    # No fallback_client — try internal REST
    try:
        from kalshi_client import KalshiClient
        client = KalshiClient()
        market = client.get_market(ticker)
        if not market:
            return None
        bid = market.get('yes_bid_dollars', 0)
        ask = market.get('yes_ask_dollars', 0)
        if bid and ask:
            update(ticker, float(bid), float(ask), source='rest')
        return {
            'yes_bid': round(float(bid) * 100) if bid else None,
            'yes_ask': round(float(ask) * 100) if ask else None,
            'no_bid':  round((1 - float(ask)) * 100) if ask else None,
            'no_ask':  round((1 - float(bid)) * 100) if bid else None,
            'source': 'rest',
        }
    except Exception as e:
        logger.warning('[MarketCache] REST fallback failed for %s: %s', ticker, e)
        # If we have stale data, return it rather than nothing
        if bid_d is not None and ask_d is not None:
            return {
                'yes_bid': round(bid_d * 100),
                'yes_ask': round(ask_d * 100),
                'no_bid':  round((1 - ask_d) * 100),
                'no_ask':  round((1 - bid_d) * 100),
                'source': 'ws_cache_stale',
            }
        return None
