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
import sys
import threading
from pathlib import Path

# Ensure project root is on sys.path when running standalone
# Resolve workspace root and add to path (agents.ruppert.* + config shim)
_AGENTS_ROOT = Path(__file__).parent.parent.parent  # workspace/agents
_WORKSPACE_ROOT = _AGENTS_ROOT.parent               # workspace/
if str(_WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE_ROOT))

from agents.ruppert.env_config import get_paths as _get_paths
import config as cfg

logger = logging.getLogger(__name__)

CACHE_FILE = _get_paths()['logs'] / 'price_cache.json'
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
    orig_bid_d, orig_ask_d = bid_d, ask_d   # preserve before REST block
    if fallback_client:
        try:
            market = fallback_client.get_market(ticker)
            if market:
                bid = market.get('yes_bid')
                ask = market.get('yes_ask')
                rest_bid_d = float(bid) / 100.0 if bid is not None else None
                rest_ask_d = float(ask) / 100.0 if ask is not None else None
                if rest_bid_d is not None and rest_ask_d is not None:
                    update(ticker, rest_bid_d, rest_ask_d, source='rest')
                    return {
                        'yes_bid': bid,
                        'yes_ask': ask,
                        'no_bid':  round((1 - rest_ask_d) * 100),
                        'no_ask':  round((1 - rest_bid_d) * 100),
                        'source': 'rest',
                    }
                # REST returned market but null prices — fall through to stale
        except Exception:
            pass
    # Use original stale values
    if orig_bid_d is not None and orig_ask_d is not None:
        return {
            'yes_bid': round(orig_bid_d * 100),
            'yes_ask': round(orig_ask_d * 100),
            'no_bid':  round((1 - orig_ask_d) * 100),
            'no_ask':  round((1 - orig_bid_d) * 100),
            'source': 'ws_cache_stale',
        }
    return None
