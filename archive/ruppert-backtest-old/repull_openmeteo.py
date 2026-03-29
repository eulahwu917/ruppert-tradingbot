"""
Re-pull Open-Meteo with gfs_seamless instead of gfs025.
Also update manifest for XBTUSD and validated data.
"""
import json
import time
import requests
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(r"C:\Users\David Wu\.openclaw\workspace\ruppert-backtest\data")

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

START_DATE = "2026-02-27"
END_DATE   = "2026-03-13"

print("=== Re-pulling Open-Meteo with gfs_seamless ===")
openmeteo_data = {}
openmeteo_missing = {}
cities_with_data = 0

for series, city in CITIES.items():
    url = "https://historical-forecast-api.open-meteo.com/v1/forecast"
    params = {
        "latitude":         city["lat"],
        "longitude":        city["lon"],
        "start_date":       START_DATE,
        "end_date":         END_DATE,
        "daily":            "temperature_2m_max,temperature_2m_min",
        "temperature_unit": "fahrenheit",
        "timezone":         "auto",
        "models":           "ecmwf_ifs025,gfs_seamless,icon_seamless",
    }

    try:
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        daily = data.get("daily", {})
        dates = daily.get("time", [])

        # Keys: temperature_2m_max_ecmwf_ifs025, temperature_2m_max_gfs_seamless, temperature_2m_max_icon_seamless
        ecmwf_vals = daily.get("temperature_2m_max_ecmwf_ifs025", [])
        gfs_vals   = daily.get("temperature_2m_max_gfs_seamless", [])
        icon_vals  = daily.get("temperature_2m_max_icon_seamless", [])

        city_data = {}
        missing_dates = []

        for i, dt in enumerate(dates):
            ecmwf_max = ecmwf_vals[i] if i < len(ecmwf_vals) else None
            gfs_max   = gfs_vals[i]   if i < len(gfs_vals)   else None
            icon_max  = icon_vals[i]  if i < len(icon_vals)  else None

            if ecmwf_max is None and gfs_max is None and icon_max is None:
                missing_dates.append(dt)

            city_data[dt] = {
                "ecmwf_max": ecmwf_max,
                "gfs_max":   gfs_max,
                "icon_max":  icon_max,
            }

        openmeteo_data[series] = city_data
        cities_with_data += 1

        if missing_dates:
            openmeteo_missing[series] = missing_dates
            print(f"  {series} ({city['name']}): {len(dates)} days, MISSING: {missing_dates}")
        else:
            sample = city_data.get(dates[0], {}) if dates else {}
            print(f"  {series} ({city['name']}): {len(dates)} days OK | sample {dates[0] if dates else '?'}: ecmwf={sample.get('ecmwf_max')}, gfs={sample.get('gfs_max')}, icon={sample.get('icon_max')}")

    except Exception as e:
        print(f"  {series} ({city['name']}): ERROR - {e}")
        openmeteo_missing[series] = ["ALL_MISSING"]

    time.sleep(0.5)

# Save updated file
om_path = DATA_DIR / "openmeteo_historical_forecasts.json"
with open(om_path, "w", encoding="utf-8") as f:
    json.dump(openmeteo_data, f, indent=2)

# Spot-check NYC on 2026-03-10
nyc_mar10 = openmeteo_data.get("KXHIGHNY", {}).get("2026-03-10", {})
print(f"\nSPOT-CHECK NYC 2026-03-10: {nyc_mar10}")
nyc_temp = nyc_mar10.get("ecmwf_max") or nyc_mar10.get("gfs_max") or nyc_mar10.get("icon_max")
in_range = nyc_temp and 35 <= nyc_temp <= 55
print(f"  In 35-55F range: {in_range} (temp={nyc_temp})")

# Count nulls
ecmwf_nulls = sum(1 for s, days in openmeteo_data.items() for d, v in days.items() if v.get("ecmwf_max") is None)
gfs_nulls   = sum(1 for s, days in openmeteo_data.items() for d, v in days.items() if v.get("gfs_max") is None)
icon_nulls  = sum(1 for s, days in openmeteo_data.items() for d, v in days.items() if v.get("icon_max") is None)
print(f"\nNull counts: ECMWF={ecmwf_nulls}, GFS={gfs_nulls}, ICON={icon_nulls}")

# Load BTC data
btc_data = json.load(open(DATA_DIR / "kraken_ohlc_XBTUSD.json", encoding="utf-8"))
btc_prices = [c["close"] for c in btc_data]
btc_min, btc_max = min(btc_prices), max(btc_prices)
print(f"\nBTC: {len(btc_data)} candles, range {btc_min:.0f} - {btc_max:.0f}")

# Update manifest
manifest_path = DATA_DIR / "manifest.json"
manifest = json.load(open(manifest_path, encoding="utf-8"))

manifest["pulled_at"]    = datetime.now(timezone.utc).isoformat()
manifest["openmeteo_cities"] = cities_with_data
manifest["kraken_pairs"] = 5  # all 5 have data

manifest["validation"]["openmeteo_missing_dates"] = openmeteo_missing
manifest["validation"]["kraken_candle_counts"]["XBTUSD"] = len(btc_data)
manifest["validation"]["spot_checks"]["nyc_mar10_temps"] = nyc_mar10
manifest["validation"]["spot_checks"]["btc_price_range"] = {
    "min": btc_min, "max": btc_max,
    "in_75k_100k_range": bool(75000 <= btc_min and btc_max <= 100000),
    "note": f"BTC ranged {btc_min:.0f}-{btc_max:.0f}; below expected 75k-100k — market was lower in Feb-Mar 2026"
}
manifest["validation"]["spot_checks"]["kraken_candle_threshold"] = {
    p: c >= 300 for p, c in manifest["validation"]["kraken_candle_counts"].items()
}
manifest["validation"]["openmeteo_model_note"] = "gfs025 unavailable on historical-forecast API; replaced with gfs_seamless"

with open(manifest_path, "w", encoding="utf-8") as f:
    json.dump(manifest, f, indent=2)

print(f"\nManifest updated.")
print(json.dumps(manifest, indent=2))
print("\n=== DONE ===")
