# data_loader.py — Ruppert Backtest Framework
# Loads historical data files from the data/ directory.
# No live API calls. All data is static files produced by Researcher.

import json
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"


def load_kalshi_weather() -> list:
    """
    Load kalshi_settled_weather.json.
    Returns a list of settled Kalshi weather market dicts.
    Expected fields per market: ticker, series, settle_date, threshold_f,
        yes_ask, last_price, status, title, etc.
    """
    path = DATA_DIR / "kalshi_settled_weather.json"
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    # Accept both a top-level list or a dict with a 'markets' key
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("markets", [])
    return []


def load_kalshi_crypto() -> list:
    """
    Load kalshi_settled_crypto.json.
    Returns [] if file is missing (crypto data is optional).
    Expected fields per market: ticker, series, settle_date,
        yes_ask, last_price, status, title, etc.
    """
    path = DATA_DIR / "kalshi_settled_crypto.json"
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("markets", [])
    return []


def load_openmeteo_forecasts() -> dict:
    """
    Load openmeteo_historical_forecasts.json.

    Returns a nested dict:
        {
            series_name: {
                date_str: {
                    'ecmwf_max': float,
                    'gfs_max':   float,
                    'icon_max':  float,
                }
            }
        }

    The JSON file produced by Researcher should have this structure directly,
    or a flat list of records that get re-shaped here.
    """
    path = DATA_DIR / "openmeteo_historical_forecasts.json"
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    # If already nested dict, return as-is
    if isinstance(raw, dict):
        # Quick sanity: check if top-level values are dicts themselves
        first = next(iter(raw.values()), None)
        if isinstance(first, dict):
            return raw
        # Might be a list wrapped in a dict key
        return raw

    # Flat list format: [{series, date, ecmwf_max, gfs_max, icon_max}, ...]
    if isinstance(raw, list):
        forecasts: dict = {}
        for rec in raw:
            series = rec.get("series", "")
            date = rec.get("date", rec.get("target_date", ""))
            if not series or not date:
                continue
            if series not in forecasts:
                forecasts[series] = {}
            # GFS key is "gfs_max" in all stored data files.
            # Source model is "gfs_seamless" (via repull_openmeteo.py), NOT "gfs025".
            # The raw API key "temperature_2m_max_gfs_seamless" is normalised to "gfs_max" at pull time.
            forecasts[series][date] = {
                "ecmwf_max": rec.get("ecmwf_max"),
                "gfs_max":   rec.get("gfs_max"),   # gfs_seamless model → stored as gfs_max
                "icon_max":  rec.get("icon_max"),
            }
        return forecasts

    return {}


def load_kraken_ohlc(pair: str) -> list:
    """
    Load kraken_ohlc_{pair}.json.
    Returns list of OHLC candle dicts (or lists).
    Expected candle format (list): [time, open, high, low, close, vwap, volume, count]
    or dict format: {time, open, high, low, close, volume}
    """
    filename = f"kraken_ohlc_{pair}.json"
    path = DATA_DIR / filename
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    # Kraken API returns {"result": {"PAIR": [[...], ...], "last": ...}}
    if isinstance(data, dict):
        result = data.get("result", data)
        if isinstance(result, dict):
            # Find the candle array — skip the 'last' key
            for k, v in result.items():
                if k != "last" and isinstance(v, list):
                    return v
        if isinstance(result, list):
            return result
    if isinstance(data, list):
        return data
    return []


def get_price_at_time(candles: list, unix_ts: int) -> float:
    """
    Find the candle closest to unix_ts and return its close price.
    Handles both list-format candles [time, open, high, low, close, ...]
    and dict-format candles {"time": ..., "close": ...}.
    Returns 0.0 if candles list is empty.
    """
    if not candles:
        return 0.0

    def candle_time(c):
        if isinstance(c, (list, tuple)):
            return int(c[0])
        if isinstance(c, dict):
            return int(c.get("time", c.get("timestamp", 0)))
        return 0

    def candle_close(c):
        if isinstance(c, (list, tuple)):
            return float(c[4])  # index 4 = close in Kraken OHLC
        if isinstance(c, dict):
            return float(c.get("close", c.get("c", 0.0)))
        return 0.0

    best = min(candles, key=lambda c: abs(candle_time(c) - unix_ts))
    return candle_close(best)
