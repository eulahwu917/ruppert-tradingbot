"""
polymarket_client.py — Shared Polymarket signal layer for Ruppert trading bot.

READ-ONLY signal data only. No trading (geo-locked).
Imported by: crypto_client.py, geopolitical_scanner.py, sports_odds_collector.py

DS — 2026-03-31
"""

import json
import logging
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# ─── API base URLs ────────────────────────────────────────────────────────────
GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE  = "https://clob.polymarket.com"
DATA_BASE  = "https://data-api.polymarket.com"

REQUEST_TIMEOUT = 10  # seconds

# ─── In-process cache ─────────────────────────────────────────────────────────
# Structure: { key: (value, expires_at_epoch_float) }
_cache: dict = {}


def _cached(key: str, fn, ttl_seconds: int):
    """
    Return cached value for key if still fresh, otherwise call fn(), cache and return result.
    fn must be a zero-arg callable that returns the fresh value.
    """
    now = time.time()
    if key in _cache:
        value, expires_at = _cache[key]
        if now < expires_at:
            return value

    value = fn()
    _cache[key] = (value, now + ttl_seconds)
    return value


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _parse_yes_price(outcome_prices_raw) -> Optional[float]:
    """Parse outcomePrices JSON string → YES price float, or None on failure."""
    try:
        if isinstance(outcome_prices_raw, str):
            prices = json.loads(outcome_prices_raw)
        else:
            prices = outcome_prices_raw
        return float(prices[0])
    except Exception:
        return None


def _parse_clob_yes_token(clob_token_ids_raw) -> Optional[str]:
    """Parse clobTokenIds JSON string → YES token id string, or None on failure."""
    try:
        if isinstance(clob_token_ids_raw, str):
            tokens = json.loads(clob_token_ids_raw)
        else:
            tokens = clob_token_ids_raw
        return tokens[0]
    except Exception:
        return None


def _build_market_dict(market: dict) -> Optional[dict]:
    """
    Convert a raw Gamma market object to the normalised internal dict.
    Returns None if the market is closed or data is malformed.
    """
    try:
        if market.get("closed"):
            return None

        yes_price = _parse_yes_price(market.get("outcomePrices"))
        clob_yes_token = _parse_clob_yes_token(market.get("clobTokenIds"))

        return {
            "question":       market.get("question", ""),
            "yes_price":      yes_price,
            "volume_24h":     float(market.get("volume24hr") or 0),
            "end_date":       market.get("endDate") or market.get("endDateIso"),
            "clob_yes_token": clob_yes_token,
            "last_trade":     float(market.get("lastTradePrice") or 0),
        }
    except Exception:
        return None


def _fetch_markets_for_keyword(keyword: str, limit: int = 20) -> list[dict]:
    """Raw fetch — do not call directly; use get_markets_by_keyword (cached)."""
    url = f"{GAMMA_BASE}/public-search"
    params = {"q": keyword, "limit": limit}
    resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()

    results = []
    for event in data.get("events", []):
        # Filter: active and not closed at the event level
        if not event.get("active") or event.get("closed"):
            continue
        for market in event.get("markets", []):
            parsed = _build_market_dict(market)
            if parsed:
                results.append(parsed)

    return results


# ─── Public API ───────────────────────────────────────────────────────────────

def get_markets_by_keyword(keyword: str, limit: int = 20) -> list[dict]:
    """
    Search active Polymarket markets by keyword.

    Returns list of dicts:
        question, yes_price, volume_24h, end_date, clob_yes_token, last_trade

    Filters to active, non-closed markets only.
    Cache: 5-minute TTL per keyword.
    Returns [] on any error.
    """
    cache_key = f"markets:{keyword}:{limit}"
    try:
        return _cached(
            cache_key,
            lambda: _fetch_markets_for_keyword(keyword, limit),
            ttl_seconds=300,  # 5 minutes
        )
    except Exception as exc:
        logger.warning("polymarket get_markets_by_keyword('%s') failed: %s", keyword, exc)
        return []


def get_live_price(clob_token_id: str) -> Optional[float]:
    """
    Get real-time midpoint price for a market token from the CLOB.

    Returns float in [0, 1] or None on error.
    No cache — always fresh.
    """
    try:
        url = f"{CLOB_BASE}/midpoint"
        resp = requests.get(url, params={"token_id": clob_token_id}, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        return float(data["mid"])
    except Exception as exc:
        logger.warning("polymarket get_live_price('%s') failed: %s", clob_token_id, exc)
        return None


def _fetch_wallet_positions(wallet_address: str) -> list[dict]:
    """Raw fetch — do not call directly; use get_wallet_positions (cached)."""
    url = f"{DATA_BASE}/positions"
    resp = requests.get(url, params={"user": wallet_address, "limit": 50}, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    raw = resp.json()

    positions = []
    for pos in raw:
        try:
            positions.append({
                "title":     pos.get("title", ""),
                "outcome":   pos.get("outcome", ""),
                "yes_price": float(pos.get("curPrice") or 0),
                "size":      float(pos.get("size") or 0),
                "cash_pnl":  float(pos.get("cashPnl") or 0),
                "pct_pnl":   float(pos.get("percentPnl") or 0),
                "avg_price": float(pos.get("avgPrice") or 0),
                "end_date":  pos.get("endDate"),
            })
        except Exception:
            continue

    return positions


def get_wallet_positions(wallet_address: str) -> list[dict]:
    """
    Get current open positions for a wallet address.

    Returns list of dicts:
        title, outcome, yes_price, size, cash_pnl, pct_pnl, avg_price, end_date

    Cache: 10-minute TTL per wallet.
    Returns [] on any error.
    """
    cache_key = f"wallet:{wallet_address}"
    try:
        return _cached(
            cache_key,
            lambda: _fetch_wallet_positions(wallet_address),
            ttl_seconds=600,  # 10 minutes
        )
    except Exception as exc:
        logger.warning("polymarket get_wallet_positions('%s') failed: %s", wallet_address, exc)
        return []


def get_smart_money_signal(wallet_addresses: list[str], keyword: str) -> dict:
    """
    Aggregate directional signal from multiple smart money wallets for markets
    matching keyword.

    Returns:
        yes_count      int    — wallets with a YES position in matched markets
        no_count       int    — wallets with a NO position in matched markets
        net_signal     float  — (yes_count - no_count) / total, range [-1, 1]
                                0.0 when no positions found
        wallets_checked int   — number of wallets successfully queried
        markets_matched list  — unique market titles matched across wallets

    Returns zeroed dict on any error — never raises.
    """
    _EMPTY = {
        "yes_count": 0,
        "no_count": 0,
        "net_signal": 0.0,
        "wallets_checked": 0,
        "markets_matched": [],
    }

    try:
        keyword_lower = keyword.lower()
        yes_count = 0
        no_count = 0
        wallets_checked = 0
        markets_seen: set[str] = set()

        for wallet in wallet_addresses:
            positions = get_wallet_positions(wallet)
            if positions is None:
                continue
            wallets_checked += 1

            for pos in positions:
                title = pos.get("title", "")
                if keyword_lower not in title.lower():
                    continue

                markets_seen.add(title)
                outcome = (pos.get("outcome") or "").upper()
                if outcome == "YES":
                    yes_count += 1
                elif outcome == "NO":
                    no_count += 1

        total = yes_count + no_count
        net_signal = (yes_count - no_count) / total if total > 0 else 0.0

        return {
            "yes_count":       yes_count,
            "no_count":        no_count,
            "net_signal":      round(net_signal, 4),
            "wallets_checked": wallets_checked,
            "markets_matched": sorted(markets_seen),
        }
    except Exception as exc:
        logger.warning("polymarket get_smart_money_signal(keyword='%s') failed: %s", keyword, exc)
        return _EMPTY


# Crypto asset → search term mapping
_CRYPTO_KEYWORDS: dict[str, list[str]] = {
    "BTC":  ["bitcoin up", "btc up", "bitcoin 15min", "btc 15min", "bitcoin 1hr", "btc 1hr"],
    "ETH":  ["ethereum up", "eth up", "ethereum 15min", "eth 15min", "ethereum 1hr", "eth 1hr"],
    "XRP":  ["xrp up", "ripple up", "xrp 15min", "xrp 1hr"],
    "DOGE": ["doge up", "dogecoin up", "doge 15min", "doge 1hr"],
    "SOL":  ["solana up", "sol up", "solana 15min", "sol 15min", "solana 1hr", "sol 1hr"],
}

# Short-window preference: score higher for these substrings in market title
_SHORT_WINDOW_TERMS = ["15min", "15 min", "1hr", "1 hr", "1-hr", "1h ", "30min", "30 min"]


def _score_crypto_market(market: dict) -> int:
    """Higher score = preferred market (short-window, high volume)."""
    title_lower = (market.get("question") or "").lower()
    score = 0
    for term in _SHORT_WINDOW_TERMS:
        if term in title_lower:
            score += 10
            break
    if market.get("volume_24h", 0) > 1000:
        score += 1
    return score


def _fetch_crypto_consensus(asset: str) -> Optional[dict]:
    """Raw fetch for get_crypto_consensus — not cached directly."""
    asset = asset.upper()
    keywords = _CRYPTO_KEYWORDS.get(asset)
    if not keywords:
        logger.warning("polymarket get_crypto_consensus: unknown asset '%s'", asset)
        return None

    candidates = []
    for kw in keywords:
        markets = get_markets_by_keyword(kw, limit=10)
        # get_markets_by_keyword already filters to active+non-closed
        for m in markets:
            q_lower = (m.get("question") or "").lower()
            # Must mention the asset and be directional (up/down/higher/lower/rise/fall)
            asset_lower = asset.lower()
            if asset_lower not in q_lower:
                continue
            directional_terms = ["up", "down", "higher", "lower", "above", "below", "rise", "fall"]
            if not any(t in q_lower for t in directional_terms):
                continue
            if m.get("yes_price") is None:
                continue
            candidates.append(m)

    if not candidates:
        return None

    # Pick highest-scored candidate (prefer short window, then volume)
    best = max(candidates, key=_score_crypto_market)

    return {
        "asset":        asset,
        "yes_price":    best["yes_price"],
        "market_title": best["question"],
        "volume_24h":   best.get("volume_24h", 0.0),
        "source":       "polymarket",
    }


def get_crypto_consensus(asset: str) -> Optional[dict]:
    """
    Get Polymarket consensus price for a crypto asset short-term direction.

    asset: 'BTC' | 'ETH' | 'XRP' | 'DOGE' | 'SOL'

    Searches for active short-term Up/Down markets; prefers 15min/1hr windows.

    Returns:
        asset         str   — normalised asset symbol
        yes_price     float — Polymarket probability of UP (0–1)
        market_title  str   — matched market question
        volume_24h    float — 24-hour volume
        source        str   — 'polymarket'

    Returns None if no relevant market found or on error.
    Cache: 5 minutes.
    """
    cache_key = f"crypto_consensus:{asset.upper()}"
    try:
        return _cached(
            cache_key,
            lambda: _fetch_crypto_consensus(asset),
            ttl_seconds=300,  # 5 minutes
        )
    except Exception as exc:
        logger.warning("polymarket get_crypto_consensus('%s') failed: %s", asset, exc)
        return None


_GEO_DEFAULT_KEYWORDS = [
    "ceasefire", "war", "invasion", "sanctions", "conflict", "nuclear"
]


def _fetch_geo_signals(keywords: list[str]) -> list[dict]:
    """Raw fetch for get_geo_signals."""
    seen_questions: set[str] = set()
    results = []

    for kw in keywords:
        markets = get_markets_by_keyword(kw, limit=15)
        for m in markets:
            q = m.get("question", "")
            if q in seen_questions:
                continue
            seen_questions.add(q)
            results.append({
                "question":  q,
                "yes_price": m.get("yes_price"),
                "volume_24h": m.get("volume_24h", 0.0),
                "end_date":  m.get("end_date"),
                "category":  "geo",
            })

    return results


def get_geo_signals(keywords: list[str] = None) -> list[dict]:
    """
    Get active geo/conflict Polymarket markets.

    Default keywords: ceasefire, war, invasion, sanctions, conflict, nuclear

    Returns list of dicts:
        question, yes_price, volume_24h, end_date, category='geo'

    Cache: 10 minutes (keyed on sorted keyword list).
    Returns [] on any error.
    """
    kws = sorted(keywords) if keywords else sorted(_GEO_DEFAULT_KEYWORDS)
    cache_key = f"geo_signals:{','.join(kws)}"
    try:
        return _cached(
            cache_key,
            lambda: _fetch_geo_signals(kws),
            ttl_seconds=600,  # 10 minutes
        )
    except Exception as exc:
        logger.warning("polymarket get_geo_signals failed: %s", exc)
        return []


# ─── Macro / Economics signals ───────────────────────────────────────────────

_MACRO_KEYWORDS: list[str] = [
    "fed rate", "interest rate", "inflation", "CPI",
    "recession", "unemployment", "GDP", "tariff",
]


def _fetch_macro_signals() -> list[dict]:
    """Raw fetch for get_macro_signals."""
    seen_questions: set[str] = set()
    results = []

    for kw in _MACRO_KEYWORDS:
        markets = get_markets_by_keyword(kw, limit=15)
        for m in markets:
            q = m.get("question", "")
            if q in seen_questions:
                continue
            seen_questions.add(q)
            results.append({
                "question":   q,
                "yes_price":  m.get("yes_price"),
                "volume_24h": m.get("volume_24h", 0.0),
                "end_date":   m.get("end_date"),
                "category":   "macro",
            })

    return results


def get_macro_signals() -> list[dict]:
    """
    Get active macro/economics Polymarket markets.

    Searches: fed rate, interest rate, inflation, CPI, recession,
              unemployment, GDP, tariff.

    Returns list of dicts:
        question, yes_price, volume_24h, end_date, category='macro'

    Cache: 10 minutes.
    Returns [] on any error.
    """
    cache_key = "macro_signals"
    try:
        return _cached(
            cache_key,
            _fetch_macro_signals,
            ttl_seconds=600,
        )
    except Exception as exc:
        logger.warning("polymarket get_macro_signals failed: %s", exc)
        return []
