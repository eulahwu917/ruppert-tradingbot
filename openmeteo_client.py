"""
Open-Meteo Client — Multi-source weather data for Kalshi weather trading.

Data sources used:
  1. Open-Meteo Ensemble API (NCEP GEFS, 31 members) — probabilistic forecast
  2. Open-Meteo Forecast API — current conditions + deterministic high
  3. NWS (National Weather Service) — official forecast used for Kalshi settlement

Ensemble approach (inspired by github.com/suislanchez/polymarket-kalshi-weather-bot):
  - Fetch 31 GFS ensemble members' daily max temperature forecasts
  - Count members above the contract threshold → model probability
  - Confidence = how one-sided the ensemble is (agreement score)
  - Much more robust than a single NOAA forecast probability
"""

import requests
import logging
from datetime import date, datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# ── Bias Correction ───────────────────────────────────────────────────────────
# Open-Meteo grid interpolation consistently underpredicts actual NWS airport
# station readings. Based on backtest_2026-03-10.json analysis.
CITY_BIAS_F = {
    "KXHIGHMIA": 4.0,   # Miami: +4°F (strong UHI + coastal effect)
    "KXHIGHCHI": 4.0,   # Chicago: +4°F
    "KXHIGHNY":  2.0,   # New York: +2°F
    "KXHIGHLA":  3.0,   # Los Angeles: +3°F (default — no backtest data yet)
    "KXHIGHPHX": 3.0,   # Phoenix: +3°F (default — no backtest data yet)
    "KXHIGHHOU": 3.0,   # Houston: +3°F (default — no backtest data yet)
}
DEFAULT_BIAS_F = 3.0  # fallback for unknown series tickers

# ── NWS Official Grid Points ──────────────────────────────────────────────────
# Kalshi settles using official NWS airport station readings.
# Grid points for https://api.weather.gov/gridpoints/{office}/{gridX},{gridY}/forecast
NWS_GRID_POINTS = {
    "KXHIGHNY":  {"office": "OKX", "gridX": 33,  "gridY": 37},
    "KXHIGHCHI": {"office": "LOT", "gridX": 75,  "gridY": 73},
    "KXHIGHMIA": {"office": "MFL", "gridX": 110, "gridY": 37},
    "KXHIGHPHX": {"office": "PSR", "gridX": 157, "gridY": 57},
    "KXHIGHHOU": {"office": "HGX", "gridX": 66,  "gridY": 99},
    "KXHIGHLA":  {"office": "LOX", "gridX": 155, "gridY": 45},
}

# Kalshi weather market cities with coordinates + NWS station
CITIES = {
    "KXHIGHNY": {
        "name": "New York",
        "lat": 40.7128,
        "lon": -74.0060,
        "nws_station": "KNYC",
        "timezone": "America/New_York",
    },
    "KXHIGHLA": {
        "name": "Los Angeles",
        "lat": 34.0522,
        "lon": -118.2437,
        "nws_station": "KLAX",
        "timezone": "America/Los_Angeles",
    },
    "KXHIGHCHI": {
        "name": "Chicago",
        "lat": 41.8781,
        "lon": -87.6298,
        "nws_station": "KORD",
        "timezone": "America/Chicago",
    },
    "KXHIGHHOU": {
        "name": "Houston",
        "lat": 29.7604,
        "lon": -95.3698,
        "nws_station": "KHOU",
        "timezone": "America/Chicago",
    },
    "KXHIGHMIA": {
        "name": "Miami",
        "lat": 25.7617,
        "lon": -80.1918,
        "nws_station": "KMIA",
        "timezone": "America/New_York",
    },
    "KXHIGHPHX": {
        "name": "Phoenix",
        "lat": 33.4484,
        "lon": -112.0740,
        "nws_station": "KPHX",
        "timezone": "America/Phoenix",
    },
}


def get_ensemble_probability(series_ticker: str, threshold_f: float, target_date: date) -> dict:
    """
    Fetch 31-member GEFS ensemble from Open-Meteo and compute probability
    that daily max temperature exceeds `threshold_f` on `target_date`.

    Returns:
        {
          "prob": float,        # fraction of ensemble members above threshold (0-1)
          "confidence": float,  # agreement score — how one-sided (0-1)
          "members_above": int, # count above threshold
          "total_members": int, # total ensemble members
          "forecast_highs": list[float],  # all member predictions
          "ensemble_median": float,
          "ensemble_mean": float,
          "ensemble_min": float,
          "ensemble_max": float,
          "source": "open_meteo_gefs",
          "error": None or str,
        }
    """
    city = CITIES.get(series_ticker)
    if not city:
        return {"error": f"Unknown series ticker: {series_ticker}", "prob": None}

    days_ahead = (target_date - date.today()).days
    if days_ahead < 0:
        return {"error": "Target date is in the past", "prob": None}

    forecast_days = max(days_ahead + 2, 3)  # ensure we cover target date

    try:
        url = "https://ensemble-api.open-meteo.com/v1/ensemble"
        params = {
            "latitude": city["lat"],
            "longitude": city["lon"],
            "daily": "temperature_2m_max",
            "models": "gfs_seamless",  # 31-member GFS ensemble (Open-Meteo name)
            "temperature_unit": "fahrenheit",
            "forecast_days": min(forecast_days, 16),
            "timezone": city["timezone"],
        }
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()

        # daily section contains one key per member: temperature_2m_max_member01..31
        member_keys = [k for k in data.get("daily", {}) if "temperature_2m_max" in k and "member" in k]

        if not member_keys:
            return {"error": "No ensemble members in response", "prob": None}

        # Find index for target_date
        dates = data["daily"].get("time", [])
        target_str = target_date.isoformat()
        if target_str not in dates:
            return {"error": f"Target date {target_str} not in forecast range", "prob": None}
        date_idx = dates.index(target_str)

        # Collect all member predictions for target date
        member_highs = []
        for key in member_keys:
            vals = data["daily"][key]
            if date_idx < len(vals) and vals[date_idx] is not None:
                member_highs.append(vals[date_idx])

        if not member_highs:
            return {"error": "No valid member values for target date", "prob": None}

        total = len(member_highs)
        above = sum(1 for h in member_highs if h >= threshold_f)
        prob = above / total

        # Confidence = how far from 50/50 (0 = coin flip, 1 = unanimous)
        confidence = abs(prob - 0.5) * 2

        sorted_highs = sorted(member_highs)
        median = sorted_highs[total // 2]
        mean = sum(member_highs) / total

        logger.info(
            f"[OpenMeteo] {city['name']} threshold={threshold_f}°F date={target_str}: "
            f"{above}/{total} members above → prob={prob:.2f} confidence={confidence:.2f}"
        )

        return {
            "prob": round(prob, 4),
            "confidence": round(confidence, 4),
            "members_above": above,
            "total_members": total,
            "forecast_highs": member_highs,
            "ensemble_median": round(median, 1),
            "ensemble_mean": round(mean, 1),
            "ensemble_min": round(sorted_highs[0], 1),
            "ensemble_max": round(sorted_highs[-1], 1),
            "source": "open_meteo_gefs",
            "error": None,
        }

    except Exception as e:
        logger.error(f"[OpenMeteo] Ensemble fetch failed for {series_ticker}: {e}")
        return {"error": str(e), "prob": None}


def get_current_conditions(series_ticker: str) -> dict:
    """
    Fetch current temperature + today's forecast high from Open-Meteo.
    Used for same-day contract assessment.

    Returns:
        {
          "current_temp_f": float,
          "today_high_f": float,       # deterministic forecast high
          "tomorrow_high_f": float,
          "hours_since_midnight": int,  # how far into the day we are
          "source": "open_meteo_forecast",
          "error": None or str,
        }
    """
    city = CITIES.get(series_ticker)
    if not city:
        return {"error": f"Unknown series ticker: {series_ticker}", "current_temp_f": None}

    try:
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": city["lat"],
            "longitude": city["lon"],
            "current": "temperature_2m",
            "daily": "temperature_2m_max",
            "temperature_unit": "fahrenheit",
            "forecast_days": 3,
            "timezone": city["timezone"],
        }
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()

        current_f = data.get("current", {}).get("temperature_2m")
        daily_highs = data.get("daily", {}).get("temperature_2m_max", [])
        today_high = daily_highs[0] if len(daily_highs) > 0 else None
        tomorrow_high = daily_highs[1] if len(daily_highs) > 1 else None

        # Apply city-specific bias correction to Open-Meteo forecast values
        bias = CITY_BIAS_F.get(series_ticker, DEFAULT_BIAS_F)
        if today_high is not None:
            today_high = round(today_high + bias, 1)
        if tomorrow_high is not None:
            tomorrow_high = round(tomorrow_high + bias, 1)
        if current_f is not None:
            current_f = round(current_f + bias, 1)

        # Compute hours since midnight in city timezone (approx via UTC offset from API)
        current_time_str = data.get("current", {}).get("time", "")
        hours_into_day = 12  # default mid-day assumption
        if current_time_str:
            try:
                dt = datetime.fromisoformat(current_time_str.replace("Z", "+00:00"))
                hours_into_day = dt.hour
            except Exception:
                pass

        logger.info(
            f"[OpenMeteo] {city['name']} current={current_f}°F (bias+{bias}°F) "
            f"today_high={today_high}°F tomorrow_high={tomorrow_high}°F"
        )

        return {
            "current_temp_f": current_f,
            "today_high_f": today_high,
            "tomorrow_high_f": tomorrow_high,
            "hours_since_midnight": hours_into_day,
            "bias_applied_f": bias,
            "source": "open_meteo_forecast",
            "error": None,
        }

    except Exception as e:
        logger.error(f"[OpenMeteo] Conditions fetch failed for {series_ticker}: {e}")
        return {"error": str(e), "current_temp_f": None}


def get_nws_forecast_high(series_ticker: str, target_date: date) -> Optional[float]:
    """
    Fetch NWS (National Weather Service) forecast high for a city/date.
    NWS is the official data source Kalshi uses for contract settlement.
    """
    city = CITIES.get(series_ticker)
    if not city:
        return None

    try:
        station = city["nws_station"]
        url = f"https://api.weather.gov/stations/{station}/observations/latest"
        headers = {"User-Agent": "RuppertBot/1.0 (kalshi-weather-trader)"}
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()

        temp_c = data.get("properties", {}).get("temperature", {}).get("value")
        if temp_c is not None:
            temp_f = (temp_c * 9 / 5) + 32
            logger.info(f"[NWS] {city['name']} current obs: {temp_f:.1f}°F")
            return round(temp_f, 1)
        return None

    except Exception as e:
        logger.error(f"[NWS] Observation fetch failed for {series_ticker}: {e}")
        return None


def get_nws_forecast_high_official(series_ticker: str, target_date: date) -> Optional[float]:
    """
    Fetch the official NWS gridpoint forecast max temperature for a city/date.
    This is the same data source Kalshi uses for contract settlement.

    Uses https://api.weather.gov/gridpoints/{office}/{gridX},{gridY}/forecast
    Falls back to None (caller should use Open-Meteo + bias correction).

    Returns: forecast high in °F, or None on failure.
    """
    grid = NWS_GRID_POINTS.get(series_ticker)
    if not grid:
        logger.debug(f"[NWS Official] No grid point configured for {series_ticker}")
        return None

    city = CITIES.get(series_ticker, {})
    city_name = city.get("name", series_ticker)

    try:
        url = f"https://api.weather.gov/gridpoints/{grid['office']}/{grid['gridX']},{grid['gridY']}/forecast"
        headers = {"User-Agent": "RuppertKalshiBot/1.0 (weather-trading-research)"}
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        data = r.json()

        periods = data.get("properties", {}).get("periods", [])
        target_str = target_date.isoformat()  # e.g. "2026-03-11"

        # NWS periods have startTime/endTime; scan for daytime period on target date
        for period in periods:
            start = period.get("startTime", "")
            is_daytime = period.get("isDaytime", False)
            if target_str in start and is_daytime:
                temp_f = period.get("temperature")
                temp_unit = period.get("temperatureUnit", "F")
                if temp_f is not None:
                    if temp_unit == "C":
                        temp_f = round((temp_f * 9 / 5) + 32, 1)
                    logger.info(
                        f"[NWS Official] {city_name} ({grid['office']}) "
                        f"forecast high for {target_str}: {temp_f}°F"
                    )
                    return float(temp_f)

        # If no exact date match, try first daytime period as fallback
        for period in periods:
            if period.get("isDaytime", False):
                temp_f = period.get("temperature")
                if temp_f is not None:
                    logger.warning(
                        f"[NWS Official] {city_name}: exact date {target_str} not found, "
                        f"using first daytime period: {temp_f}°F"
                    )
                    return float(temp_f)

        logger.warning(f"[NWS Official] {city_name}: no daytime period found in forecast")
        return None

    except Exception as e:
        logger.warning(
            f"[NWS Official] Fetch failed for {series_ticker} "
            f"({grid['office']}): {e} — falling back to Open-Meteo+bias"
        )
        return None


def get_full_weather_signal(series_ticker: str, threshold_f: float, target_date: date) -> dict:
    """
    Master function: combine ensemble probability + current conditions + NWS obs.
    Returns a unified signal with confidence score for edge detection.

    Signal logic:
      - Primary: ensemble probability from 31-member GEFS
      - Secondary: deterministic forecast high vs threshold
      - Tertiary (same-day): current temp vs threshold + hours remaining
      - Fallback: NOAA (handled in edge_detector.py)

    Same-day adjustment:
      If target_date == today and we're past 2pm local time:
        - Weight current observed temp heavily
        - If current_temp already exceeds threshold → prob approaches 1.0
        - If today_high forecast already below threshold by 3°F+ → prob approaches 0.0
    """
    # Apply bias: ensemble members underpredict by bias_f, so lower the threshold
    # by the bias before comparing — equivalent to adding bias to each member value.
    bias = CITY_BIAS_F.get(series_ticker, DEFAULT_BIAS_F)
    effective_threshold = threshold_f - bias

    ensemble = get_ensemble_probability(series_ticker, effective_threshold, target_date)
    conditions = get_current_conditions(series_ticker)

    # Try NWS official forecast first; fall back to legacy observation call
    nws_official = get_nws_forecast_high_official(series_ticker, target_date)
    nws_current = nws_official if nws_official is not None else get_nws_forecast_high(series_ticker, target_date)

    is_same_day = (target_date == date.today())
    result = {
        "series_ticker": series_ticker,
        "threshold_f": threshold_f,
        "effective_threshold_f": round(effective_threshold, 1),
        "bias_applied_f": bias,
        "target_date": target_date.isoformat(),
        "is_same_day": is_same_day,
        "ensemble": ensemble,
        "conditions": conditions,
        "nws_current_f": nws_current,
        "nws_official_f": nws_official,
        "final_prob": None,
        "final_confidence": None,
        "skip_reason": None,
    }

    # Determine final probability
    if ensemble.get("prob") is not None:
        prob = ensemble["prob"]
        confidence = ensemble["confidence"]

        # Same-day adjustment: weight current conditions
        if is_same_day and conditions.get("today_high_f") is not None:
            today_high = conditions["today_high_f"]
            current_temp = conditions.get("current_temp_f")
            hours = conditions.get("hours_since_midnight", 12)

            # Late in day (>= 14h) and current temp well above threshold → near certain YES
            if hours >= 14 and current_temp is not None and current_temp >= threshold_f:
                prob = 0.95
                confidence = 0.90
                result["skip_reason"] = "same_day_temp_already_exceeded"

            # Late in day and forecast high well below threshold → near certain NO
            elif hours >= 14 and today_high < threshold_f - 2:
                prob = 0.05
                confidence = 0.90

            # Blend ensemble with deterministic forecast
            else:
                det_prob = 1.0 if today_high >= threshold_f else 0.0
                # Weighted blend: ensemble 60%, deterministic 40%
                prob = 0.6 * prob + 0.4 * det_prob
                confidence = ensemble["confidence"] * 0.8  # slightly less confident same-day

        result["final_prob"] = round(prob, 4)
        result["final_confidence"] = round(confidence, 4)
    else:
        result["skip_reason"] = f"ensemble_failed: {ensemble.get('error')}"

    return result


if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO)
    print("\n=== Open-Meteo Test ===\n")

    # Test current conditions for all cities
    for ticker in CITIES:
        cond = get_current_conditions(ticker)
        print(f"{ticker}: current={cond.get('current_temp_f')}°F  today_high={cond.get('today_high_f')}°F  tmrw_high={cond.get('tomorrow_high_f')}°F")

    print("\n=== Ensemble Test (Miami, 84.5°F, tomorrow) ===\n")
    tomorrow = date.today() + timedelta(days=1)
    result = get_full_weather_signal("KXHIGHMIA", 84.5, tomorrow)
    print(json.dumps(result, indent=2, default=str))
