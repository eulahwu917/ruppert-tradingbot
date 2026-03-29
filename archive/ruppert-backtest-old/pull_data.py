"""
SA-3 Researcher — Historical Data Pull for Backtesting Framework
Date range: 2026-02-27 through 2026-03-13
"""

import json
import time
import requests
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(r"C:\Users\David Wu\.openclaw\workspace\ruppert-backtest\data")
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ── City coordinates (from openmeteo_client.py) ──────────────────────────────
CITIES = {
    "KXHIGHNY":    {"name": "New York",           "lat": 40.7128,  "lon": -74.0060},
    "KXHIGHCHI":   {"name": "Chicago",            "lat": 41.8781,  "lon": -87.6298},
    "KXHIGHMIA":   {"name": "Miami",              "lat": 25.7617,  "lon": -80.1918},
    "KXHIGHHOU":   {"name": "Houston",            "lat": 29.7604,  "lon": -95.3698},
    "KXHIGHPHX":   {"name": "Phoenix",            "lat": 33.4484,  "lon": -112.0740},
    "KXHIGHLA":    {"name": "Los Angeles",        "lat": 34.0522,  "lon": -118.2437},
    "KXHIGHAUS":   {"name": "Austin",             "lat": 30.2672,  "lon": -97.7431},
    "KXHIGHDEN":   {"name": "Denver",             "lat": 39.7392,  "lon": -104.9903},
    "KXHIGHLAX":   {"name": "Los Angeles (LAX)",  "lat": 33.9425,  "lon": -118.4081},
    "KXHIGHPHIL":  {"name": "Philadelphia",       "lat": 39.9526,  "lon": -75.1652},
    "KXHIGHTMIN":  {"name": "Minneapolis",        "lat": 44.9778,  "lon": -93.2650},
    "KXHIGHTDAL":  {"name": "Dallas",             "lat": 32.7767,  "lon": -96.7970},
    "KXHIGHTDC":   {"name": "Washington DC",      "lat": 38.9072,  "lon": -77.0369},
    "KXHIGHTLV":   {"name": "Las Vegas",          "lat": 36.1699,  "lon": -115.1398},
    "KXHIGHTNOU":  {"name": "New Orleans",        "lat": 29.9511,  "lon": -90.0715},
    "KXHIGHTOKC":  {"name": "Oklahoma City",      "lat": 35.4676,  "lon": -97.5164},
    "KXHIGHTSFO":  {"name": "San Francisco",      "lat": 37.6213,  "lon": -122.3790},
    "KXHIGHTSEA":  {"name": "Seattle",            "lat": 47.4502,  "lon": -122.3088},
    "KXHIGHTSATX": {"name": "San Antonio",        "lat": 29.4241,  "lon": -98.4936},
    "KXHIGHTATL":  {"name": "Atlanta",            "lat": 33.7490,  "lon": -84.3880},
}

SERIES_LIST = list(CITIES.keys())

START_DATE = "2026-02-27"
END_DATE   = "2026-03-13"

# ─────────────────────────────────────────────────────────────────────────────
# DATA SOURCE 1: Kalshi Settled Weather Markets
# ─────────────────────────────────────────────────────────────────────────────
print("\n=== KALSHI: Pulling settled weather markets ===")
kalshi_markets = []
kalshi_series_with_data = []
kalshi_series_empty = []

KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"

for series in SERIES_LIST:
    url = f"{KALSHI_BASE}/markets"
    params = {
        "series_ticker": series,
        "status": "settled",
        "limit": 50,
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        markets = data.get("markets", [])
        
        # Extract only the fields we need
        extracted = []
        for m in markets:
            extracted.append({
                "ticker":        m.get("ticker"),
                "series_ticker": m.get("series_ticker"),
                "close_time":    m.get("close_time"),
                "last_price":    m.get("last_price"),
                "yes_ask":       m.get("yes_ask"),
                "yes_bid":       m.get("yes_bid"),
                "open_time":     m.get("open_time"),
                "subtitle":      m.get("subtitle"),
            })
        
        kalshi_markets.extend(extracted)
        
        if len(extracted) > 0:
            kalshi_series_with_data.append(series)
            print(f"  {series}: {len(extracted)} settled markets")
        else:
            kalshi_series_empty.append(series)
            print(f"  {series}: 0 results (EMPTY)")
            
    except Exception as e:
        print(f"  {series}: ERROR — {e}")
        kalshi_series_empty.append(series)
    
    time.sleep(0.1)

# Save Kalshi data
kalshi_path = DATA_DIR / "kalshi_settled_weather.json"
with open(kalshi_path, "w", encoding="utf-8") as f:
    json.dump(kalshi_markets, f, indent=2)

print(f"\nKalshi: {len(kalshi_markets)} total markets saved to {kalshi_path}")

# ─────────────────────────────────────────────────────────────────────────────
# DATA SOURCE 2: Open-Meteo Historical Forecast API
# ─────────────────────────────────────────────────────────────────────────────
print("\n=== OPEN-METEO: Pulling historical forecast data ===")

openmeteo_data = {}
openmeteo_missing = {}
cities_with_data = 0

for series, city in CITIES.items():
    url = "https://historical-forecast-api.open-meteo.com/v1/forecast"
    params = {
        "latitude":          city["lat"],
        "longitude":         city["lon"],
        "start_date":        START_DATE,
        "end_date":          END_DATE,
        "daily":             "temperature_2m_max,temperature_2m_min",
        "temperature_unit":  "fahrenheit",
        "timezone":          "auto",
        "models":            "ecmwf_ifs025,gfs025,icon_seamless",
    }
    
    try:
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        
        # Parse per-model daily data
        # The response may have model-specific keys or combined daily
        city_data = {}
        missing_dates = []
        
        daily = data.get("daily", {})
        dates = daily.get("time", [])
        
        # Model key naming: Open-Meteo uses different key patterns per model
        # For multi-model requests, keys are: temperature_2m_max (primary) 
        # and model-specific keys when multiple models requested
        
        # Extract per-model max temps
        # When multiple models specified, response includes model-prefixed keys
        ecmwf_key  = "temperature_2m_max"  # default or ecmwf_ifs025_temperature_2m_max
        gfs_key    = "temperature_2m_max"
        icon_key   = "temperature_2m_max"
        
        # Check for model-specific keys
        all_keys = list(daily.keys())
        ecmwf_candidates = [k for k in all_keys if "ecmwf" in k and "max" in k]
        gfs_candidates   = [k for k in all_keys if "gfs" in k and "max" in k]
        icon_candidates  = [k for k in all_keys if "icon" in k and "max" in k]
        
        if ecmwf_candidates:
            ecmwf_key = ecmwf_candidates[0]
        if gfs_candidates:
            gfs_key = gfs_candidates[0]
        if icon_candidates:
            icon_key = icon_candidates[0]
        
        ecmwf_vals = daily.get(ecmwf_key, [])
        gfs_vals   = daily.get(gfs_key, [])
        icon_vals  = daily.get(icon_key, [])
        
        # If all the same key (single combined), try temperature_2m_max
        main_vals = daily.get("temperature_2m_max", [])
        
        for i, dt in enumerate(dates):
            ecmwf_max = ecmwf_vals[i] if i < len(ecmwf_vals) else None
            gfs_max   = gfs_vals[i]   if i < len(gfs_vals)   else None
            icon_max  = icon_vals[i]  if i < len(icon_vals)  else None
            
            # If model-specific keys all map to same key, use main_vals
            if ecmwf_key == gfs_key == icon_key:
                main_val = main_vals[i] if i < len(main_vals) else None
                ecmwf_max = gfs_max = icon_max = main_val
            
            if ecmwf_max is None and gfs_max is None and icon_max is None:
                missing_dates.append(dt)
            
            city_data[dt] = {
                "ecmwf_max": ecmwf_max,
                "gfs_max":   gfs_max,
                "icon_max":  icon_max,
            }
        
        openmeteo_data[series] = city_data
        
        if missing_dates:
            openmeteo_missing[series] = missing_dates
            print(f"  {series} ({city['name']}): {len(dates)} days, MISSING: {missing_dates}")
        else:
            print(f"  {series} ({city['name']}): {len(dates)} days OK — keys: {ecmwf_key[:20]}, {gfs_key[:20]}, {icon_key[:20]}")
        
        cities_with_data += 1
        
    except Exception as e:
        print(f"  {series} ({city['name']}): ERROR — {e}")
        openmeteo_missing[series] = ["ALL_MISSING"]
    
    time.sleep(0.5)

# Save Open-Meteo data
om_path = DATA_DIR / "openmeteo_historical_forecasts.json"
with open(om_path, "w", encoding="utf-8") as f:
    json.dump(openmeteo_data, f, indent=2)

print(f"\nOpen-Meteo: {cities_with_data} cities saved to {om_path}")

# Spot-check: NYC on 2026-03-10
nyc_data = openmeteo_data.get("KXHIGHNY", {})
nyc_mar10 = nyc_data.get("2026-03-10", {})
print(f"SPOT-CHECK NYC 2026-03-10: {nyc_mar10}")

# ─────────────────────────────────────────────────────────────────────────────
# DATA SOURCE 3: Kraken Historical OHLC
# ─────────────────────────────────────────────────────────────────────────────
print("\n=== KRAKEN: Pulling 1h OHLC data ===")

# Unix timestamp for 2026-02-27 00:00 UTC
dt_feb27 = datetime(2026, 2, 27, 0, 0, 0, tzinfo=timezone.utc)
since_ts = int(dt_feb27.timestamp())
print(f"Since timestamp: {since_ts} ({dt_feb27.isoformat()})")

KRAKEN_PAIRS = {
    "XBTUSD": "XBTUSD",
    "ETHUSD": "ETHUSD",
    "XRPUSD": "XRPUSD",
    "SOLUSD": "SOLUSD",
    "DOGEUSD": "DOGEUSD",
}

kraken_candle_counts = {}

for pair, pair_name in KRAKEN_PAIRS.items():
    url = "https://api.kraken.com/0/public/OHLC"
    params = {
        "pair":     pair_name,
        "interval": 60,
        "since":    since_ts,
    }
    
    try:
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        
        if data.get("error"):
            print(f"  {pair}: API error — {data['error']}")
            kraken_candle_counts[pair] = 0
            continue
        
        result = data.get("result", {})
        # Remove 'last' key (cursor, not candle data)
        candles_raw = None
        for key, val in result.items():
            if key != "last":
                candles_raw = val
                break
        
        if not candles_raw:
            print(f"  {pair}: No candle data in response")
            kraken_candle_counts[pair] = 0
            continue
        
        # Filter to our date range (2026-02-27 to 2026-03-13)
        dt_end = datetime(2026, 3, 13, 23, 59, 59, tzinfo=timezone.utc)
        end_ts = int(dt_end.timestamp())
        
        candles = []
        for c in candles_raw:
            ts = int(c[0])
            if since_ts <= ts <= end_ts:
                candles.append({
                    "timestamp": ts,
                    "open":      float(c[1]),
                    "high":      float(c[2]),
                    "low":       float(c[3]),
                    "close":     float(c[4]),
                    "volume":    float(c[6]),
                })
        
        kraken_candle_counts[pair] = len(candles)
        
        # Save to file
        out_path = DATA_DIR / f"kraken_ohlc_{pair}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(candles, f, indent=2)
        
        # Spot-check BTC price range
        check_note = ""
        if pair == "XBTUSD" and candles:
            prices = [c["close"] for c in candles]
            price_min, price_max = min(prices), max(prices)
            in_range = 75000 <= price_min and price_max <= 100000
            check_note = f" | price range ${price_min:,.0f}-${price_max:,.0f} {'✓ IN RANGE' if in_range else '⚠ OUT OF RANGE'}"
        
        print(f"  {pair}: {len(candles)} candles{check_note}")
        
    except Exception as e:
        print(f"  {pair}: ERROR — {e}")
        kraken_candle_counts[pair] = 0
    
    time.sleep(0.3)

# ─────────────────────────────────────────────────────────────────────────────
# WRITE MANIFEST
# ─────────────────────────────────────────────────────────────────────────────
print("\n=== Writing manifest ===")

manifest = {
    "pulled_at":              datetime.now(timezone.utc).isoformat(),
    "date_range":             {"start": START_DATE, "end": END_DATE},
    "kalshi_weather_markets": len(kalshi_markets),
    "openmeteo_cities":       cities_with_data,
    "kraken_pairs":           len([p for p, c in kraken_candle_counts.items() if c > 0]),
    "validation": {
        "kalshi_series_with_data":  kalshi_series_with_data,
        "kalshi_series_empty":      kalshi_series_empty,
        "openmeteo_missing_dates":  openmeteo_missing,
        "kraken_candle_counts":     kraken_candle_counts,
        "spot_checks": {
            "nyc_mar10_temps":        nyc_mar10,
            "kraken_candle_threshold": {p: c >= 300 for p, c in kraken_candle_counts.items()},
        }
    }
}

manifest_path = DATA_DIR / "manifest.json"
with open(manifest_path, "w", encoding="utf-8") as f:
    json.dump(manifest, f, indent=2)

print(f"Manifest saved to {manifest_path}")
print(json.dumps(manifest, indent=2))
print("\n=== DONE ===")
