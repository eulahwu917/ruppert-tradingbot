"""Test if gfs_seamless works better for historical forecast."""
import requests

url = "https://historical-forecast-api.open-meteo.com/v1/forecast"

# Test with gfs_seamless
params = {
    "latitude":          40.7128,
    "longitude":         -74.0060,
    "start_date":        "2026-02-27",
    "end_date":          "2026-03-01",
    "daily":             "temperature_2m_max",
    "temperature_unit":  "fahrenheit",
    "timezone":          "auto",
    "models":            "gfs_seamless",
}
r = requests.get(url, params=params, timeout=30)
data = r.json()
daily = data.get("daily", {})
print("gfs_seamless keys:", list(daily.keys()))
print("Values:", daily.get("temperature_2m_max", [])[:3])

# Test with gfs025
params["models"] = "gfs025"
r2 = requests.get(url, params=params, timeout=30)
data2 = r2.json()
daily2 = data2.get("daily", {})
print("\ngfs025 keys:", list(daily2.keys()))
vals = {k: v[:3] for k, v in daily2.items() if k != "time"}
print("Values:", vals)
