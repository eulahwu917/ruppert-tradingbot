"""Debug Open-Meteo key structure for multi-model request."""
import requests
import json

url = "https://historical-forecast-api.open-meteo.com/v1/forecast"
params = {
    "latitude":          40.7128,
    "longitude":         -74.0060,
    "start_date":        "2026-02-27",
    "end_date":          "2026-03-01",
    "daily":             "temperature_2m_max,temperature_2m_min",
    "temperature_unit":  "fahrenheit",
    "timezone":          "auto",
    "models":            "ecmwf_ifs025,gfs025,icon_seamless",
}

r = requests.get(url, params=params, timeout=30)
print("Status:", r.status_code)
data = r.json()

# Print all daily keys
daily = data.get("daily", {})
print("\nAll daily keys:")
for k in daily.keys():
    print(f"  {k!r}")

print("\nSample values for 2026-02-27 (index 0):")
for k, v in daily.items():
    if isinstance(v, list) and len(v) > 0:
        print(f"  {k!r}: {v[0]}")
