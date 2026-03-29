# signal_simulator.py — Ruppert Backtest Framework
# Simulates edge signals from historical data — NO live API calls.
# Mirrors logic from edge_detector.py and crypto_client.py.

import math
from datetime import datetime, timezone, timedelta
from data_loader import get_price_at_time


# ---------------------------------------------------------------------------
# Weather signal
# ---------------------------------------------------------------------------

# Model weights matching live edge_detector.py ensemble
_WEATHER_WEIGHTS = {
    "ecmwf": 0.40,
    "gfs":   0.40,
    "icon":  0.20,
}

# Bias corrections per city series (from live config — mirror, don't import)
# Keys match actual Kalshi series names observed in data
_SERIES_BIAS = {
    "KXHIGHNY":   3.0,
    "KXHIGHCHI":  2.0,
    "KXHIGHMIA":  4.0,
    "KXHIGHLAX":  2.5,
    "KXHIGHPHX":  2.0,
    "KXHIGHTATL": 3.0,
    "KXHIGHDEN":  2.0,
    "KXHIGHTDAL": 3.0,
    "KXHIGHTSEA": 2.0,
    "KXHIGHTSFO": 2.5,
    "KXHIGHTDC":  3.0,
    "KXHIGHTMIN": 2.0,
    "KXHIGHTLV":  2.0,
    "KXHIGHTOKC": 2.5,
    "KXHIGHTSATX":3.0,
    "KXHIGHAUS":  2.5,
    "KXHIGHTHOU": 3.0,
    "KXHIGHHOU":  3.0,
    "KXHIGHPHIL": 3.0,
}


def _extract_series_city(series: str) -> str:
    """Extract 3-letter city code from series like KXHIGHCHI → CHI."""
    return series.replace("KXHIGH", "").replace("KXLOW", "")


def simulate_weather_signal(
    series: str,
    target_date: str,
    threshold_f: float,
    scan_hour_utc: int,
    forecasts: dict,
) -> dict:
    """
    Simulate the weather edge signal for a historical date using stored forecast data.

    Args:
        series:       Kalshi series, e.g. 'KXHIGHCHI'
        target_date:  ISO date string, e.g. '2026-03-10'
        threshold_f:  Temperature threshold in °F, e.g. 46.5
        scan_hour_utc: Hour of day (UTC) when the scan runs: 7, 12, 15, or 22
        forecasts:    Dict from load_openmeteo_forecasts()

    Returns dict:
        {
            'prob':        float,   # ensemble probability 0..1
            'confidence':  float,   # confidence score 0..1
            'edge':        float,   # |market_prob - model_prob|
            'direction':   str,     # 'YES' or 'NO'
            'noaa_prob':   float,   # same as prob (no NOAA data in backtest)
            'market_prob': float,   # inferred from market yes_ask
            'skip':        bool,    # True if same-day + scan too late
            'reason':      str,
        }
    """
    empty = {
        "prob": 0.0,
        "confidence": 0.0,
        "edge": 0.0,
        "direction": "UNKNOWN",
        "noaa_prob": 0.0,
        "market_prob": 0.5,
        "skip": True,
        "reason": "",
    }

    # ---- 1. Same-day skip logic ----
    # If the target date is the same as the scan date and the scan is at/after hour 14 UTC,
    # the market is too close to settlement — skip.
    try:
        target_dt = datetime.strptime(target_date, "%Y-%m-%d")
    except ValueError:
        empty["reason"] = f"invalid target_date: {target_date}"
        return empty

    # In backtest we use target_date as scan_date (each day's data is self-contained)
    # We apply same_day_skip based on scan_hour_utc
    if scan_hour_utc >= 14:
        empty["skip"] = True
        empty["reason"] = "same_day skip: scan_hour >= 14"
        return empty

    # ---- 2. Look up forecast data ----
    series_forecasts = forecasts.get(series, {})
    day_data = series_forecasts.get(target_date)
    if day_data is None:
        empty["reason"] = f"no forecast data for {series}/{target_date}"
        return empty

    ecmwf_max = day_data.get("ecmwf_max")
    gfs_max   = day_data.get("gfs_max")
    icon_max  = day_data.get("icon_max")

    # ---- 3. Apply city bias correction ----
    bias = _SERIES_BIAS.get(series, 2.5)
    adjusted_threshold = threshold_f - bias  # lower threshold = higher ensemble hit rate

    # ---- 4. Ensemble probability (soft, not hard count) ----
    # Each model contributes its weight if it forecasts >= adjusted_threshold.
    # Missing model data = 0 contribution but we renorm weights.
    available = {}
    if ecmwf_max is not None:
        available["ecmwf"] = float(ecmwf_max)
    if gfs_max is not None:
        available["gfs"] = float(gfs_max)
    if icon_max is not None:
        available["icon"] = float(icon_max)

    if not available:
        empty["reason"] = "no model data available"
        return empty

    total_weight = sum(_WEATHER_WEIGHTS[m] for m in available)
    if total_weight <= 0:
        empty["reason"] = "zero weight"
        return empty

    weighted_prob = sum(
        _WEATHER_WEIGHTS[m] * (1.0 if v >= adjusted_threshold else 0.0)
        for m, v in available.items()
    ) / total_weight

    # ---- 5. Confidence: agreement between models ----
    votes = [(1.0 if v >= adjusted_threshold else 0.0) for v in available.values()]
    if len(votes) >= 2:
        agree = sum(1 for v in votes if v == votes[0]) / len(votes)
    else:
        agree = 1.0
    confidence = agree * (total_weight / 1.0)  # penalise missing models

    # ---- 6. Direction and edge ----
    # We use yes_ask as market_prob proxy — passed in per-market during backtest_engine.
    # Here we return the model probability; edge is computed in backtest_engine where
    # market_prob is available from the settled market data.
    # TODO: B markets (bracket) — direction logic not yet implemented
    # Currently filtered out in backtest_engine.py before reaching here
    direction = "YES" if weighted_prob >= 0.5 else "NO"

    return {
        "prob":        round(weighted_prob, 4),
        "confidence":  round(min(confidence, 1.0), 4),
        "edge":        0.0,        # computed in backtest_engine with market_prob
        "direction":   direction,
        "noaa_prob":   round(weighted_prob, 4),  # no NOAA in backtest
        "market_prob": 0.5,        # placeholder; caller sets this
        "skip":        False,
        "reason":      "ok",
    }


# ---------------------------------------------------------------------------
# Crypto signal
# ---------------------------------------------------------------------------

# Kraken pair map: series prefix → pair name (matches actual kraken_ohlc_*.json filenames)
_SERIES_TO_PAIR = {
    "KXBTC":  "XBTUSD",
    "KXETH":  "ETHUSD",
    "KXSOL":  "SOLUSD",
    "KXDOGE": "DOGEUSD",
    "KXXRP":  "XRPUSD",
    "KXBNB":  "BNBUSD",
}


def simulate_crypto_signal(
    series: str,
    target_date: str,
    scan_hour_utc: int,
    kraken_candles: dict,
) -> dict:
    """
    Simplified crypto momentum signal using Kraken OHLC data.
    Computes 24h price change at scan_hour_utc on target_date.
    If change >+2% → bullish (YES). If <-2% → bearish (NO). Else neutral.

    Args:
        series:        e.g. 'KXBTC'
        target_date:   ISO date string
        scan_hour_utc: UTC hour of the scan
        kraken_candles: {pair: [candle_list]} from data_loader

    Returns dict:
        {
            'prob':       float,
            'confidence': float,
            'edge':       float,
            'direction':  str,
            'change_24h': float,
            'skip':       bool,
            'reason':     str,
        }
    """
    empty = {
        "prob": 0.5,
        "confidence": 0.0,
        "edge": 0.0,
        "direction": "NEUTRAL",
        "change_24h": 0.0,
        "skip": True,
        "reason": "",
    }

    pair = _SERIES_TO_PAIR.get(series)
    if pair is None:
        # Try stripping KXBTC → BTC-style fallback
        pair = series.replace("KX", "") + "USD"

    candles = kraken_candles.get(pair, kraken_candles.get(pair.lower(), []))
    if not candles:
        empty["reason"] = f"no candle data for pair {pair}"
        return empty

    try:
        target_dt = datetime.strptime(target_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        empty["reason"] = f"invalid target_date: {target_date}"
        return empty

    # Scan timestamp: target_date at scan_hour_utc
    scan_ts = int((target_dt + timedelta(hours=scan_hour_utc)).timestamp())
    # 24h earlier
    prev_ts = scan_ts - 86400

    price_now  = get_price_at_time(candles, scan_ts)
    price_prev = get_price_at_time(candles, prev_ts)

    if price_prev <= 0:
        empty["reason"] = "zero prev price"
        return empty

    change_24h = (price_now - price_prev) / price_prev  # fractional

    # Signal thresholds
    BULL_THRESH = 0.02   # +2%
    BEAR_THRESH = -0.02  # -2%

    if change_24h > BULL_THRESH:
        direction = "YES"
        # Probability scales with momentum magnitude, capped at 0.80
        prob = min(0.50 + abs(change_24h) * 5, 0.80)
        confidence = min(0.40 + abs(change_24h) * 3, 0.75)
    elif change_24h < BEAR_THRESH:
        direction = "NO"
        prob = min(0.50 + abs(change_24h) * 5, 0.80)
        confidence = min(0.40 + abs(change_24h) * 3, 0.75)
    else:
        direction = "NEUTRAL"
        prob = 0.50
        confidence = 0.20

    return {
        "prob":       round(prob, 4),
        "confidence": round(confidence, 4),
        "edge":       0.0,   # set in backtest_engine
        "direction":  direction,
        "change_24h": round(change_24h, 6),
        "skip":       False,
        "reason":     "ok",
    }
