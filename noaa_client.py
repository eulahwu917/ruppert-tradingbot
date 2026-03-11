"""
NOAA/NWS Weather Data Client
Fetches official forecast data — free, no API key needed.
Used to compare against Kalshi market prices.
"""
import requests
from datetime import datetime, timedelta

# NWS grid points for major cities (lat/lon → grid mapping)
CITY_COORDS = {
    'NYC':     (40.7128, -74.0060),
    'LA':      (34.0522, -118.2437),
    'Chicago': (41.8781, -87.6298),
    'Houston': (29.7604, -95.3698),
    'Phoenix': (33.4484, -112.0740),
    'Miami':   (25.7617, -80.1918),
}

NWS_BASE = 'https://api.weather.gov'
HEADERS = {'User-Agent': 'KalshiWeatherBot/1.0 (contact@ruppertbot.com)'}


def get_forecast_url(lat, lon):
    """Get the forecast URL for a lat/lon coordinate."""
    resp = requests.get(f'{NWS_BASE}/points/{lat},{lon}', headers=HEADERS, timeout=10)
    resp.raise_for_status()
    return resp.json()['properties']['forecast']


def get_hourly_forecast_url(lat, lon):
    """Get the hourly forecast URL for a lat/lon coordinate."""
    resp = requests.get(f'{NWS_BASE}/points/{lat},{lon}', headers=HEADERS, timeout=10)
    resp.raise_for_status()
    return resp.json()['properties']['forecastHourly']


def get_daily_high_forecast(city, target_date=None):
    """
    Get the forecasted daily high temperature for a city.
    Returns dict with temperature, unit, probability info.
    target_date: datetime.date object (defaults to tomorrow)
    """
    if target_date is None:
        target_date = (datetime.now() + timedelta(days=1)).date()

    if city not in CITY_COORDS:
        raise ValueError(f"City {city} not in supported list: {list(CITY_COORDS.keys())}")

    lat, lon = CITY_COORDS[city]

    try:
        forecast_url = get_forecast_url(lat, lon)
        resp = requests.get(forecast_url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        periods = resp.json()['properties']['periods']

        # Find the daytime period for target date
        for period in periods:
            period_date = datetime.fromisoformat(period['startTime']).date()
            if period_date == target_date and period['isDaytime']:
                return {
                    'city': city,
                    'date': str(target_date),
                    'high_temp_f': period['temperature'],
                    'unit': period['temperatureUnit'],
                    'short_forecast': period['shortForecast'],
                    'detailed_forecast': period['detailedForecast'],
                    'source': 'NOAA/NWS'
                }

        return None

    except Exception as e:
        print(f"[NOAA] Error fetching forecast for {city}: {e}")
        return None


def get_probability_for_temp_range(city, low_f, high_f, target_date=None):
    """
    Estimate probability that a city's daily high falls within [low_f, high_f].
    Uses NOAA forecast as the central estimate with a simple distribution.
    
    Returns: float probability between 0.0 and 1.0
    """
    forecast = get_daily_high_forecast(city, target_date)
    if not forecast:
        return None

    noaa_temp = forecast['high_temp_f']

    # Simple normal distribution approximation
    # NWS forecasts have ~3-5°F standard deviation at 24-48hr range
    import math
    std_dev = 4.0  # degrees F uncertainty

    def normal_cdf(x, mean, std):
        return 0.5 * (1 + math.erf((x - mean) / (std * math.sqrt(2))))

    prob = normal_cdf(high_f, noaa_temp, std_dev) - normal_cdf(low_f, noaa_temp, std_dev)
    return round(max(0.0, min(1.0, prob)), 4)


if __name__ == '__main__':
    # Test the client
    print("Testing NOAA client...")
    forecast = get_daily_high_forecast('NYC')
    if forecast:
        print(f"NYC forecast: {forecast}")
        prob = get_probability_for_temp_range('NYC', 60, 70)
        print(f"Probability NYC high is 60-70°F: {prob}")
    else:
        print("Failed to fetch forecast")
