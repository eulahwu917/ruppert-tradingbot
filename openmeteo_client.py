"""
Open-Meteo Client — Multi-source weather data for Kalshi weather trading.

Data sources used:
  1. Open-Meteo Ensemble API — multi-model probabilistic forecast
     - ECMWF IFS 0.25° (ecmwf_ifs025) — 51 members, weight 40%
     - GFS/GEFS Seamless (gfs_seamless) — 31 members, weight 40%
     - ICON Global (icon_global)         — 40 members, weight 20%
  2. Open-Meteo Forecast API — current conditions + deterministic high
  3. NWS (National Weather Service) — official forecast used for Kalshi settlement

Ensemble approach (inspired by github.com/suislanchez/polymarket-kalshi-weather-bot):
  - Fetch ensemble members from each model; count members above threshold
  - Weighted average across models → model probability
  - Confidence = how one-sided the weighted ensemble is (agreement score)
  - Graceful fallback: if any model fails, renormalize remaining weights

Bias correction:
  - NOAA GHCND rolling bias (via ghcnd_client.get_bias) — refreshed daily
  - Falls back to hardcoded CITY_BIAS_F offsets when API unavailable

Weight rationale (per SA-2 Researcher scope report 2026-03-12):
  ECMWF IFS is 15-20% more accurate than GFS at 3-5 day range.
  ICON provides independent corroboration from DWD Germany.
  Weights: ECMWF 40% | GEFS 40% | ICON 20%
"""

import requests
import logging
from datetime import date, datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# ── Multi-Model Ensemble Configuration ───────────────────────────────────────
# Weights must sum to 1.0. If a model fails, remaining weights are renormalized.
ENSEMBLE_MODEL_WEIGHTS = {
    "ecmwf_ifs025": 0.40,   # ECMWF IFS 0.25° — best global medium-range accuracy
    "gfs_seamless":  0.40,   # GFS/GEFS 31-member — already validated in stack
    "icon_global":   0.20,   # ICON Global — independent ensemble corroboration
}

# ── Bias Correction ───────────────────────────────────────────────────────────
# Kept as hardcoded fallback when GHCND API is unavailable.
# Primary bias source: ghcnd_client.get_bias() — refreshed daily from NOAA CDO API.
# Original values from backtest_2026-03-10.json analysis.
# Expanded cities use DEFAULT_BIAS_F (3.0) until backtest data is available.
CITY_BIAS_F = {
    # Original cities (validated via backtest)
    "KXHIGHMIA":  4.0,   # Miami: +4°F (strong UHI + coastal effect)
    "KXHIGHCHI":  4.0,   # Chicago: +4°F
    "KXHIGHNY":   2.0,   # New York: +2°F
    "KXHIGHLA":   3.0,   # Los Angeles: +3°F
    "KXHIGHPHX":  3.0,   # Phoenix: +3°F
    "KXHIGHHOU":  3.0,   # Houston: +3°F
    # Expanded cities (default bias until GHCND validates, added 2026-03-13)
    "KXHIGHAUS":  0.0,   # Austin       # unvalidated — bias TBD pending GHCND backtest
    "KXHIGHDEN":  0.0,   # Denver       # unvalidated — bias TBD pending GHCND backtest
    "KXHIGHLAX":  0.0,   # Los Angeles (LAX)  # unvalidated — bias TBD pending GHCND backtest
    "KXHIGHPHIL": 0.0,   # Philadelphia # unvalidated — bias TBD pending GHCND backtest
    "KXHIGHTMIN": 0.0,   # Minneapolis  # unvalidated — bias TBD pending GHCND backtest
    "KXHIGHTDAL": 0.0,   # Dallas       # unvalidated — bias TBD pending GHCND backtest
    "KXHIGHTDC":  0.0,   # Washington DC  # unvalidated — bias TBD pending GHCND backtest
    "KXHIGHTLV":  0.0,   # Las Vegas    # unvalidated — bias TBD pending GHCND backtest
    "KXHIGHTNOU": 0.0,   # New Orleans  # unvalidated — bias TBD pending GHCND backtest
    "KXHIGHTOKC": 0.0,   # Oklahoma City  # unvalidated — bias TBD pending GHCND backtest
    "KXHIGHTSFO": 0.0,   # San Francisco  # unvalidated — bias TBD pending GHCND backtest
    "KXHIGHTSEA": 0.0,   # Seattle      # unvalidated — bias TBD pending GHCND backtest
    "KXHIGHTSATX":0.0,   # San Antonio  # unvalidated — bias TBD pending GHCND backtest
    "KXHIGHTATL": 0.0,   # Atlanta      # unvalidated — bias TBD pending GHCND backtest
}
DEFAULT_BIAS_F = 0.0  # fallback for unknown series tickers (was 3.0; reset pending GHCND backtest)

# ── NWS Official Grid Points ──────────────────────────────────────────────────
NWS_GRID_POINTS = {
    # Original cities
    "KXHIGHNY":   {"office": "OKX", "gridX": 33,  "gridY": 37},
    "KXHIGHCHI":  {"office": "LOT", "gridX": 75,  "gridY": 73},
    "KXHIGHMIA":  {"office": "MFL", "gridX": 110, "gridY": 50},
    "KXHIGHPHX":  {"office": "PSR", "gridX": 157, "gridY": 57},
    "KXHIGHHOU":  {"office": "HGX", "gridX": 66,  "gridY": 99},
    "KXHIGHLA":   {"office": "LOX", "gridX": 155, "gridY": 45},
    # Expanded cities (added 2026-03-13, grid points from api.weather.gov/points)
    "KXHIGHAUS":  {"office": "EWX", "gridX": 156, "gridY": 91},   # Austin (30.2672,-97.7431)
    "KXHIGHDEN":  {"office": "BOU", "gridX": 63,  "gridY": 62},   # Denver (39.7392,-104.9903)
    "KXHIGHLAX":  {"office": "LOX", "gridX": 148, "gridY": 41},   # Los Angeles LAX (33.9425,-118.4081)
    "KXHIGHPHIL": {"office": "PHI", "gridX": 50,  "gridY": 76},   # Philadelphia (39.9526,-75.1652)
    "KXHIGHTMIN": {"office": "MPX", "gridX": 108, "gridY": 72},   # Minneapolis (44.9778,-93.2650)
    "KXHIGHTDAL": {"office": "FWD", "gridX": 89,  "gridY": 104},  # Dallas (32.7767,-96.7970)
    "KXHIGHTDC":  {"office": "LWX", "gridX": 96,  "gridY": 72},   # Washington DC (38.9072,-77.0369)
    "KXHIGHTLV":  {"office": "VEF", "gridX": 123, "gridY": 98},   # Las Vegas (36.1699,-115.1398)
    "KXHIGHTNOU": {"office": "LIX", "gridX": 68,  "gridY": 88},   # New Orleans (29.9511,-90.0715)
    "KXHIGHTOKC": {"office": "OUN", "gridX": 97,  "gridY": 94},   # Oklahoma City (35.4676,-97.5164)
    "KXHIGHTSFO": {"office": "MTR", "gridX": 85,  "gridY": 98},   # San Francisco (37.6213,-122.3790)
    "KXHIGHTSEA": {"office": "SEW", "gridX": 124, "gridY": 61},   # Seattle (47.4502,-122.3088)
    "KXHIGHTSATX":{"office": "EWX", "gridX": 126, "gridY": 54},   # San Antonio (29.4241,-98.4936)
    "KXHIGHTATL": {"office": "FFC", "gridX": 51,  "gridY": 87},   # Atlanta (33.7490,-84.3880)
}

# Kalshi weather market cities with coordinates + NWS station
CITIES = {
    # Original cities
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
    # Expanded cities (added 2026-03-13)
    "KXHIGHAUS": {
        "name": "Austin",
        "lat": 30.2672,
        "lon": -97.7431,
        "nws_station": "KAUS",
        "timezone": "America/Chicago",
    },
    "KXHIGHDEN": {
        "name": "Denver",
        "lat": 39.7392,
        "lon": -104.9903,
        "nws_station": "KDEN",
        "timezone": "America/Denver",
    },
    "KXHIGHLAX": {
        "name": "Los Angeles (LAX)",
        "lat": 33.9425,
        "lon": -118.4081,
        "nws_station": "KLAX",
        "timezone": "America/Los_Angeles",
    },
    "KXHIGHPHIL": {
        "name": "Philadelphia",
        "lat": 39.9526,
        "lon": -75.1652,
        "nws_station": "KPHL",
        "timezone": "America/New_York",
    },
    "KXHIGHTMIN": {
        "name": "Minneapolis",
        "lat": 44.9778,
        "lon": -93.2650,
        "nws_station": "KMSP",
        "timezone": "America/Chicago",
    },
    "KXHIGHTDAL": {
        "name": "Dallas",
        "lat": 32.7767,
        "lon": -96.7970,
        "nws_station": "KDFW",
        "timezone": "America/Chicago",
    },
    "KXHIGHTDC": {
        "name": "Washington DC",
        "lat": 38.9072,
        "lon": -77.0369,
        "nws_station": "KDCA",
        "timezone": "America/New_York",
    },
    "KXHIGHTLV": {
        "name": "Las Vegas",
        "lat": 36.1699,
        "lon": -115.1398,
        "nws_station": "KLAS",
        "timezone": "America/Los_Angeles",
    },
    "KXHIGHTNOU": {
        "name": "New Orleans",
        "lat": 29.9511,
        "lon": -90.0715,
        "nws_station": "KMSY",
        "timezone": "America/Chicago",
    },
    "KXHIGHTOKC": {
        "name": "Oklahoma City",
        "lat": 35.4676,
        "lon": -97.5164,
        "nws_station": "KOKC",
        "timezone": "America/Chicago",
    },
    "KXHIGHTSFO": {
        "name": "San Francisco",
        "lat": 37.6213,
        "lon": -122.3790,
        "nws_station": "KSFO",
        "timezone": "America/Los_Angeles",
    },
    "KXHIGHTSEA": {
        "name": "Seattle",
        "lat": 47.4502,
        "lon": -122.3088,
        "nws_station": "KSEA",
        "timezone": "America/Los_Angeles",
    },
    "KXHIGHTSATX": {
        "name": "San Antonio",
        "lat": 29.4241,
        "lon": -98.4936,
        "nws_station": "KSAT",
        "timezone": "America/Chicago",
    },
    "KXHIGHTATL": {
        "name": "Atlanta",
        "lat": 33.7490,
        "lon": -84.3880,
        "nws_station": "KATL",
        "timezone": "America/New_York",
    },
}


# ── Bias Helper ───────────────────────────────────────────────────────────────

def _get_bias(series_ticker: str) -> float:
    """
    Return temperature bias for a city.
    Primary: NOAA GHCND rolling bias (ghcnd_client, refreshed daily).
    Fallback: hardcoded CITY_BIAS_F offsets.
    """
    try:
        from ghcnd_client import get_bias as _ghcnd_bias
        return _ghcnd_bias(series_ticker)
    except Exception:
        return CITY_BIAS_F.get(series_ticker, DEFAULT_BIAS_F)


# ── Single-Model Ensemble Fetch ───────────────────────────────────────────────

def _fetch_model_ensemble(series_ticker: str, threshold_f: float,
                          target_date: date, model: str) -> dict:
    """
    Fetch one model's ensemble members from Open-Meteo and compute probability
    that daily max temperature meets or exceeds `threshold_f` on `target_date`.

    Args:
        series_ticker: e.g. "KXHIGHMIA"
        threshold_f:   already bias-adjusted threshold in °F
        target_date:   date to evaluate
        model:         Open-Meteo model name (e.g. "ecmwf_ifs025")

    Returns:
        {
          "model": str,
          "prob": float or None,
          "confidence": float,
          "members_above": int,
          "total_members": int,
          "forecast_highs": list[float],
          "ensemble_median": float,
          "ensemble_mean": float,
          "ensemble_min": float,
          "ensemble_max": float,
          "error": None or str,
        }
    """
    city = CITIES.get(series_ticker)
    if not city:
        return {"model": model, "error": f"Unknown series ticker: {series_ticker}", "prob": None}

    days_ahead = (target_date - date.today()).days
    if days_ahead < 0:
        return {"model": model, "error": "Target date is in the past", "prob": None}

    forecast_days = max(days_ahead + 2, 3)

    try:
        url = "https://ensemble-api.open-meteo.com/v1/ensemble"
        params = {
            "latitude":         city["lat"],
            "longitude":        city["lon"],
            "daily":            "temperature_2m_max",
            "models":           model,
            "temperature_unit": "fahrenheit",
            "forecast_days":    min(forecast_days, 16),
            "timezone":         city["timezone"],
        }
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()

        member_keys = [
            k for k in data.get("daily", {})
            if "temperature_2m_max" in k and "member" in k
        ]

        if not member_keys:
            return {"model": model, "error": f"No ensemble members in response for {model}", "prob": None}

        dates      = data["daily"].get("time", [])
        target_str = target_date.isoformat()
        if target_str not in dates:
            return {
                "model": model,
                "error": f"Target date {target_str} not in forecast range for {model}",
                "prob": None,
            }
        date_idx = dates.index(target_str)

        member_highs = []
        for key in member_keys:
            vals = data["daily"][key]
            if date_idx < len(vals) and vals[date_idx] is not None:
                member_highs.append(vals[date_idx])

        if not member_highs:
            return {"model": model, "error": f"No valid member values for {model} on {target_str}", "prob": None}

        total      = len(member_highs)
        above      = sum(1 for h in member_highs if h >= threshold_f)
        prob       = above / total
        confidence = abs(prob - 0.5) * 2

        sorted_highs = sorted(member_highs)
        median = sorted_highs[total // 2]
        mean   = sum(member_highs) / total

        logger.info(
            f"[OpenMeteo/{model}] {city['name']} threshold={threshold_f:.1f}°F "
            f"date={target_str}: {above}/{total} above → prob={prob:.2f}"
        )

        return {
            "model":           model,
            "prob":            round(prob, 4),
            "confidence":      round(confidence, 4),
            "members_above":   above,
            "total_members":   total,
            "forecast_highs":  member_highs,
            "ensemble_median": round(median, 1),
            "ensemble_mean":   round(mean, 1),
            "ensemble_min":    round(sorted_highs[0], 1),
            "ensemble_max":    round(sorted_highs[-1], 1),
            "error":           None,
        }

    except Exception as e:
        logger.error(f"[OpenMeteo/{model}] Ensemble fetch failed for {series_ticker}: {e}")
        return {"model": model, "error": str(e), "prob": None}


# ── Multi-Model Ensemble (public API) ────────────────────────────────────────

def get_ensemble_probability(series_ticker: str, threshold_f: float, target_date: date) -> dict:
    """
    Fetch multi-model ensemble (ECMWF IFS + GEFS + ICON) and compute
    weighted-average probability that daily max temperature meets or
    exceeds `threshold_f` on `target_date`.

    Weights: ECMWF 40%, GEFS 40%, ICON 20% (renormalized if any model fails).

    Returns:
        {
          "prob": float,           # weighted ensemble probability (0–1)
          "confidence": float,     # weighted agreement score (0–1)
          "members_above": int,    # from primary model (ECMWF preferred)
          "total_members": int,
          "forecast_highs": list,
          "ensemble_median": float,
          "ensemble_mean": float,
          "ensemble_min": float,
          "ensemble_max": float,
          "source": "open_meteo_multi_model",
          "models_used": list[dict],   # [{model, weight, prob, members}, ...]
          "model_details": dict,       # per-model results
          "error": None or str,
        }
    """
    # Fetch all models (independent calls for clean error isolation)
    model_results = {}
    for model in ENSEMBLE_MODEL_WEIGHTS:
        model_results[model] = _fetch_model_ensemble(
            series_ticker, threshold_f, target_date, model
        )

    # Filter to successful models
    successful = {m: r for m, r in model_results.items() if r.get("prob") is not None}

    if not successful:
        errors = {m: r.get("error") for m, r in model_results.items()}
        logger.error(f"[OpenMeteo] All ensemble models failed for {series_ticker}: {errors}")
        return {
            "error": f"All ensemble models failed: {errors}",
            "prob": None,
            "models_used": [],
            "source": "open_meteo_multi_model",
        }

    # Renormalize weights for successful models
    raw_weights    = {m: ENSEMBLE_MODEL_WEIGHTS[m] for m in successful}
    total_weight   = sum(raw_weights.values())
    norm_weights   = {m: w / total_weight for m, w in raw_weights.items()}

    # Weighted combination
    weighted_prob = sum(norm_weights[m] * successful[m]["prob"] for m in successful)
    weighted_conf = sum(norm_weights[m] * successful[m]["confidence"] for m in successful)

    # Primary model for member stats (ECMWF preferred, else first available)
    primary = "ecmwf_ifs025" if "ecmwf_ifs025" in successful else next(iter(successful))
    prim    = successful[primary]

    # Compose models_used list for logging / dashboard
    models_used = [
        {
            "model":   m,
            "weight":  round(norm_weights[m], 3),
            "prob":    successful[m]["prob"],
            "members": successful[m].get("total_members"),
            "mean_f":  successful[m].get("ensemble_mean"),
        }
        for m in successful
    ]

    city_name = CITIES.get(series_ticker, {}).get("name", series_ticker)
    model_summary = ", ".join(
        f"{m}={successful[m]['prob']:.2f}(w={norm_weights[m]:.2f})" for m in successful
    )
    logger.info(
        f"[OpenMeteo] {city_name} multi-model weighted: {model_summary} "
        f"→ prob={weighted_prob:.3f} conf={weighted_conf:.3f}"
    )

    return {
        "prob":            round(weighted_prob, 4),
        "confidence":      round(weighted_conf, 4),
        "members_above":   prim.get("members_above"),
        "total_members":   prim.get("total_members"),
        "forecast_highs":  prim.get("forecast_highs", []),
        "ensemble_median": prim.get("ensemble_median"),
        "ensemble_mean":   prim.get("ensemble_mean"),
        "ensemble_min":    prim.get("ensemble_min"),
        "ensemble_max":    prim.get("ensemble_max"),
        "source":          "open_meteo_multi_model",
        "models_used":     models_used,
        "model_details": {
            m: {
                "prob":          r["prob"],
                "confidence":    r["confidence"],
                "total_members": r.get("total_members"),
                "mean_f":        r.get("ensemble_mean"),
                "error":         r.get("error"),
            }
            for m, r in model_results.items()
        },
        "error": None,
    }


def get_current_conditions(series_ticker: str) -> dict:
    """
    Fetch current temperature + today's forecast high from Open-Meteo.
    Used for same-day contract assessment.

    Returns:
        {
          "current_temp_f": float,
          "today_high_f": float,
          "tomorrow_high_f": float,
          "hours_since_midnight": int,
          "bias_applied_f": float,
          "bias_source": str,
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
            "latitude":         city["lat"],
            "longitude":        city["lon"],
            "current":          "temperature_2m",
            "daily":            "temperature_2m_max",
            "temperature_unit": "fahrenheit",
            "forecast_days":    3,
            "timezone":         city["timezone"],
        }
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()

        current_f    = data.get("current", {}).get("temperature_2m")
        daily_highs  = data.get("daily", {}).get("temperature_2m_max", [])
        today_high   = daily_highs[0] if len(daily_highs) > 0 else None
        tomorrow_high = daily_highs[1] if len(daily_highs) > 1 else None

        # Apply GHCND-based bias correction (falls back to hardcoded if needed)
        try:
            from ghcnd_client import get_bias as _ghcnd_bias, get_bias_source
            bias        = _ghcnd_bias(series_ticker)
            bias_source = get_bias_source(series_ticker)
        except Exception:
            bias        = CITY_BIAS_F.get(series_ticker, DEFAULT_BIAS_F)
            bias_source = "hardcoded_import_error"

        if today_high is not None:
            today_high = round(today_high + bias, 1)
        if tomorrow_high is not None:
            tomorrow_high = round(tomorrow_high + bias, 1)
        if current_f is not None:
            current_f = round(current_f + bias, 1)

        # Hours since midnight in city timezone (approximate from UTC offset)
        current_time_str = data.get("current", {}).get("time", "")
        hours_into_day   = 12  # default mid-day
        if current_time_str:
            try:
                dt             = datetime.fromisoformat(current_time_str.replace("Z", "+00:00"))
                hours_into_day = dt.hour
            except Exception:
                pass

        logger.info(
            f"[OpenMeteo] {city['name']} current={current_f}°F "
            f"(bias+{bias:.1f}°F/{bias_source}) "
            f"today_high={today_high}°F tomorrow_high={tomorrow_high}°F"
        )

        return {
            "current_temp_f":     current_f,
            "today_high_f":       today_high,
            "tomorrow_high_f":    tomorrow_high,
            "hours_since_midnight": hours_into_day,
            "bias_applied_f":     bias,
            "bias_source":        bias_source,
            "source":             "open_meteo_forecast",
            "error":              None,
        }

    except Exception as e:
        logger.error(f"[OpenMeteo] Conditions fetch failed for {series_ticker}: {e}")
        return {"error": str(e), "current_temp_f": None}


def get_nws_forecast_high(series_ticker: str, target_date: date) -> Optional[float]:
    """
    Fetch NWS (National Weather Service) current observation.
    NWS is the official data source Kalshi uses for contract settlement.
    """
    city = CITIES.get(series_ticker)
    if not city:
        return None

    try:
        station = city["nws_station"]
        url     = f"https://api.weather.gov/stations/{station}/observations/latest"
        headers = {"User-Agent": "RuppertBot/1.0 (kalshi-weather-trader)"}
        r       = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        data    = r.json()

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

    city      = CITIES.get(series_ticker, {})
    city_name = city.get("name", series_ticker)

    try:
        url     = f"https://api.weather.gov/gridpoints/{grid['office']}/{grid['gridX']},{grid['gridY']}/forecast"
        headers = {"User-Agent": "RuppertKalshiBot/1.0 (weather-trading-research)"}
        r       = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        data    = r.json()

        periods    = data.get("properties", {}).get("periods", [])
        target_str = target_date.isoformat()

        for period in periods:
            start      = period.get("startTime", "")
            is_daytime = period.get("isDaytime", False)
            if target_str in start and is_daytime:
                temp_f    = period.get("temperature")
                temp_unit = period.get("temperatureUnit", "F")
                if temp_f is not None:
                    if temp_unit == "C":
                        temp_f = round((temp_f * 9 / 5) + 32, 1)
                    logger.info(
                        f"[NWS Official] {city_name} ({grid['office']}) "
                        f"forecast high for {target_str}: {temp_f}°F"
                    )
                    return float(temp_f)

        # Fallback: first daytime period
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
    Master function: combine multi-model ensemble probability + current conditions + NWS obs.
    Returns a unified signal with confidence score for edge detection.

    Signal logic:
      - Primary: weighted ensemble (ECMWF 40% + GEFS 40% + ICON 20%)
      - Secondary: deterministic forecast high vs threshold (same-day blend)
      - Tertiary (same-day): current temp vs threshold + hours remaining

    Bias correction:
      - GHCND-based rolling bias (refreshed daily) applied to effective_threshold
      - Falls back to hardcoded per-city offsets if NOAA API unavailable

    Same-day adjustment:
      If target_date == today and we're past 2pm local time:
        - Weight current observed temp heavily
        - If current_temp already exceeds threshold → prob approaches 1.0
        - If today_high forecast already below threshold by 3°F+ → prob approaches 0.0
    """
    from datetime import date as _date
    if isinstance(target_date, str):
        target_date = _date.fromisoformat(target_date)

    # Bias: GHCND (dynamic) preferred, hardcoded fallback
    try:
        from ghcnd_client import get_bias as _ghcnd_bias, get_bias_source
        bias        = _ghcnd_bias(series_ticker)
        bias_source = get_bias_source(series_ticker)
    except Exception:
        bias        = CITY_BIAS_F.get(series_ticker, DEFAULT_BIAS_F)
        bias_source = "hardcoded_import_error"

    # Ensemble members underpredict by bias_f → lower threshold equivalently
    effective_threshold = threshold_f - bias

    ensemble   = get_ensemble_probability(series_ticker, effective_threshold, target_date)
    conditions = get_current_conditions(series_ticker)

    # NWS official → legacy observation fallback
    nws_official = get_nws_forecast_high_official(series_ticker, target_date)
    nws_current  = nws_official if nws_official is not None else get_nws_forecast_high(series_ticker, target_date)

    is_same_day = (target_date == date.today())
    result = {
        "series_ticker":       series_ticker,
        "threshold_f":         threshold_f,
        "effective_threshold_f": round(effective_threshold, 1),
        "bias_applied_f":      round(bias, 2),
        "bias_source":         bias_source,
        "target_date":         target_date.isoformat(),
        "is_same_day":         is_same_day,
        "ensemble":            ensemble,
        "conditions":          conditions,
        "nws_current_f":       nws_current,
        "nws_official_f":      nws_official,
        "models_used":         ensemble.get("models_used", []),
        "final_prob":          None,
        "final_confidence":    None,
        "skip_reason":         None,
    }

    # Determine final probability
    if ensemble.get("prob") is not None:
        prob       = ensemble["prob"]
        confidence = ensemble["confidence"]

        # Same-day adjustment: weight current conditions
        if is_same_day and conditions.get("today_high_f") is not None:
            today_high   = conditions["today_high_f"]
            current_temp = conditions.get("current_temp_f")
            hours        = conditions.get("hours_since_midnight", 12)

            if hours >= 14 and current_temp is not None and current_temp >= threshold_f:
                prob       = 0.95
                confidence = 0.90
                result["skip_reason"] = "same_day_temp_already_exceeded"
            elif hours >= 14 and today_high < threshold_f - 2:
                prob       = 0.05
                confidence = 0.90
            else:
                # After 4pm (hours>=16): current_temp is better proxy than stale forecast high
                # At 6pm the day's actual high is observed; declining temps won't recover
                if hours >= 16 and current_temp is not None:
                    det_prob = 1.0 if current_temp >= threshold_f else (
                        0.3 if current_temp >= threshold_f - 3 else 0.0
                    )
                else:
                    det_prob = 1.0 if today_high >= threshold_f else 0.0
                prob = 0.6 * prob + 0.4 * det_prob
                confidence = confidence * 0.8

        result["final_prob"]       = round(prob, 4)
        result["final_confidence"] = round(confidence, 4)
    else:
        result["skip_reason"] = f"ensemble_failed: {ensemble.get('error')}"

    return result


if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO)
    print("\n=== Open-Meteo Multi-Model Test ===\n")

    for ticker in CITIES:
        cond = get_current_conditions(ticker)
        print(
            f"{ticker}: current={cond.get('current_temp_f')}°F  "
            f"today_high={cond.get('today_high_f')}°F  "
            f"bias={cond.get('bias_applied_f')}°F({cond.get('bias_source')})"
        )

    print("\n=== Multi-Model Ensemble Test (Miami, 84.5°F, tomorrow) ===\n")
    tomorrow = date.today() + timedelta(days=1)
    result   = get_full_weather_signal("KXHIGHMIA", 84.5, tomorrow)
    print(json.dumps(result, indent=2, default=str))
    print("\nModels used:")
    for m in result.get("models_used", []):
        print(f"  {m['model']:20} weight={m['weight']:.2f}  prob={m['prob']:.3f}  "
              f"members={m['members']}")
