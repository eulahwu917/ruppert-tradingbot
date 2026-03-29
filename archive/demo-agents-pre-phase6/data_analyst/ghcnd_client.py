"""
GHCND Bias Correction Client
─────────────────────────────────────────────────────────────
Replaces hardcoded per-city temperature bias offsets with NOAA
GHCND (Global Historical Climatology Network Daily) API-based
rolling bias correction.

Method:
  1. Fetch last 30 days of TMAX observations from NOAA CDO API (per city station)
  2. Fetch ERA5 reanalysis TMAX for same period from Open-Meteo Archive API
  3. bias = mean(NOAA_observed_F − ERA5_model_F) over matching days
  4. Cache result in logs/ghcnd_bias_cache.json (refresh once daily)
  5. Fall back to hardcoded offsets if token missing or API fails

NOAA CDO token: stored in secrets/kalshi_config.json as 'noaa_cdo_token'
Cache location: kalshi-bot/logs/ghcnd_bias_cache.json

Station IDs (GHCND):
  NYC = USW00094728  (Central Park / KNYC)
  CHI = USW00094846  (O'Hare / KORD)
  MIA = USW00012839  (Miami Intl / KMIA)
  LA  = USW00023174  (LAX / KLAX)
  HOU = USW00012960  (Hobby / KHOU)
  PHX = USW00023183  (Sky Harbor / KPHX)
"""

import json
import logging
import sys
import requests
from datetime import date, datetime, timedelta
from pathlib import Path

# Ensure project root is on sys.path when running standalone
_PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logger = logging.getLogger(__name__)

# ── Station & City Config ─────────────────────────────────────────────────────

GHCND_STATIONS = {
    "KXHIGHNY": {
        "station": "USW00094728",
        "name": "New York (Central Park)",
        "lat": 40.7128, "lon": -74.0060,
        "tz": "America/New_York",
    },
    "KXHIGHCHI": {
        "station": "USW00094846",
        "name": "Chicago (O'Hare)",
        "lat": 41.8781, "lon": -87.6298,
        "tz": "America/Chicago",
    },
    "KXHIGHMIA": {
        "station": "USW00012839",
        "name": "Miami International",
        "lat": 25.7617, "lon": -80.1918,
        "tz": "America/New_York",
    },
    "KXHIGHLA": {
        "station": "USW00023174",
        "name": "Los Angeles (LAX)",
        "lat": 34.0522, "lon": -118.2437,
        "tz": "America/Los_Angeles",
    },
    "KXHIGHHOU": {
        "station": "USW00012960",
        "name": "Houston (Hobby)",
        "lat": 29.7604, "lon": -95.3698,
        "tz": "America/Chicago",
    },
    "KXHIGHPHX": {
        "station": "USW00023183",
        "name": "Phoenix (Sky Harbor)",
        "lat": 33.4484, "lon": -112.0740,
        "tz": "America/Phoenix",
    },
    'KXHIGHAUS': {
        'station': 'USW00013904',
        'name': 'Austin (Bergstrom)',
        'lat': 30.1975, 'lon': -97.6664,
        'tz': 'America/Chicago',
    },
    'KXHIGHDEN': {
        'station': 'USW00003017',
        'name': 'Denver (International)',
        'lat': 39.8561, 'lon': -104.6737,
        'tz': 'America/Denver',
    },
    'KXHIGHLAX': {
        'station': 'USW00023174',
        'name': 'Los Angeles (LAX)',
        'lat': 34.0522, 'lon': -118.2437,
        'tz': 'America/Los_Angeles',
    },
    'KXHIGHPHIL': {
        'station': 'USW00013739',
        'name': 'Philadelphia (International)',
        'lat': 39.9526, 'lon': -75.1652,
        'tz': 'America/New_York',
    },
    'KXHIGHTMIN': {
        'station': 'USW00014922',
        'name': 'Minneapolis (St Paul)',
        'lat': 44.9778, 'lon': -93.2650,
        'tz': 'America/Chicago',
    },
    'KXHIGHTDAL': {
        'station': 'USW00003927',
        'name': 'Dallas (Fort Worth)',
        'lat': 32.7767, 'lon': -96.7970,
        'tz': 'America/Chicago',
    },
    'KXHIGHTDC': {
        'station': 'USW00013743',
        'name': 'Washington DC (Reagan)',
        'lat': 38.8951, 'lon': -77.0364,
        'tz': 'America/New_York',
    },
    'KXHIGHTLV': {
        'station': 'USW00023169',
        'name': 'Las Vegas (McCarran)',
        'lat': 36.1699, 'lon': -115.1398,
        'tz': 'America/Los_Angeles',
    },
    'KXHIGHTNOU': {
        'station': 'USW00012916',
        'name': 'New Orleans (Armstrong)',
        'lat': 29.9511, 'lon': -90.0715,
        'tz': 'America/Chicago',
    },
    'KXHIGHTOKC': {
        'station': 'USW00013967',
        'name': 'Oklahoma City (Will Rogers)',
        'lat': 35.4676, 'lon': -97.5164,
        'tz': 'America/Chicago',
    },
    'KXHIGHTSFO': {
        'station': 'USW00023234',
        'name': 'San Francisco (SFO)',
        'lat': 37.7749, 'lon': -122.4194,
        'tz': 'America/Los_Angeles',
    },
    'KXHIGHTSEA': {
        'station': 'USW00024233',
        'name': 'Seattle (Sea-Tac)',
        'lat': 47.6062, 'lon': -122.3321,
        'tz': 'America/Los_Angeles',
    },
    'KXHIGHTSATX': {
        'station': 'USW00012921',
        'name': 'San Antonio (International)',
        'lat': 29.4241, 'lon': -98.4936,
        'tz': 'America/Chicago',
    },
    'KXHIGHTATL': {
        'station': 'USW00013874',
        'name': 'Atlanta (Hartsfield)',
        'lat': 33.7490, 'lon': -84.3880,
        'tz': 'America/New_York',
    },
}

# Fallback hardcoded offsets — used when NOAA API is unavailable
# Source: backtest_2026-03-10.json analysis
HARDCODED_BIAS_F = {
    "KXHIGHNY":  2.0,
    "KXHIGHCHI": 4.0,
    "KXHIGHMIA": 4.0,
    "KXHIGHLA":  3.0,
    "KXHIGHHOU": 3.0,
    "KXHIGHPHX": 3.0,
    "KXHIGHAUS": 3.0,
    "KXHIGHDEN": 3.0,
    "KXHIGHLAX": 3.0,
    "KXHIGHPHIL": 3.0,
    "KXHIGHTMIN": 3.0,
    "KXHIGHTDAL": 3.0,
    "KXHIGHTDC": 3.0,
    "KXHIGHTLV": 3.0,
    "KXHIGHTNOU": 3.0,
    "KXHIGHTOKC": 3.0,
    "KXHIGHTSFO": 3.0,
    "KXHIGHTSEA": 3.0,
    "KXHIGHTSATX": 3.0,
    "KXHIGHTATL": 3.0,
}
DEFAULT_HARDCODED_BIAS_F = 3.0  # fallback for unknown tickers

# ── File Paths ────────────────────────────────────────────────────────────────

_CACHE_FILE   = _PROJECT_ROOT / "logs" / "ghcnd_bias_cache.json"
_SECRETS_FILE = Path(__file__).parent.parent / "secrets" / "kalshi_config.json"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_noaa_token() -> str | None:
    """Read NOAA CDO API token from secrets/kalshi_config.json."""
    try:
        data = json.loads(_SECRETS_FILE.read_text(encoding="utf-8"))
        return data.get("noaa_cdo_token")
    except Exception:
        return None


def _cache_is_fresh() -> bool:
    """Return True if cache exists and was updated today (UTC)."""
    if not _CACHE_FILE.exists():
        return False
    try:
        data = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        return data.get("updated_date", "") == date.today().isoformat()
    except Exception:
        return False


def _load_cache() -> dict:
    """Load cached biases from disk. Returns {} on failure."""
    try:
        data = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        return data.get("biases", {})
    except Exception:
        return {}


def _save_cache(biases: dict, sources: dict | None = None):
    """Write bias cache to disk."""
    try:
        _CACHE_FILE.parent.mkdir(exist_ok=True)
        payload = {
            "updated_date": date.today().isoformat(),
            "updated_at": datetime.utcnow().isoformat() + "Z",
            "biases": biases,
            "sources": sources or {},
        }
        _CACHE_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        logger.info(f"[GHCND] Bias cache saved ({len(biases)} cities)")
    except Exception as e:
        logger.warning(f"[GHCND] Could not write bias cache: {e}")


# ── NOAA CDO Fetch ────────────────────────────────────────────────────────────

def _fetch_noaa_tmax(station_id: str, start_date: str, end_date: str, token: str) -> dict:
    """
    Fetch NOAA GHCND TMAX observations for a station.

    Args:
        station_id: bare station ID (e.g. "USW00094728")
        start_date: "YYYY-MM-DD"
        end_date: "YYYY-MM-DD"
        token: NOAA CDO API token

    Returns:
        {"YYYY-MM-DD": tmax_f, ...} or {} on failure.

    Note: NOAA CDO returns TMAX in tenths of degrees Celsius (raw units).
    Conversion: tmax_f = (raw_value / 10.0) * 9/5 + 32
    """
    url = "https://www.ncdc.noaa.gov/cdo-web/api/v2/data"
    params = {
        "datasetid":  "GHCND",
        "stationid":  f"GHCND:{station_id}",
        "datatypeid": "TMAX",
        "startdate":  start_date,
        "enddate":    end_date,
        "limit":      1000,
    }
    headers = {"token": token}

    try:
        r = requests.get(url, params=params, headers=headers, timeout=25)
        r.raise_for_status()
        data = r.json()
        results = data.get("results", [])
        if not results:
            logger.warning(f"[GHCND] No TMAX results for station GHCND:{station_id} "
                           f"({start_date} → {end_date})")
            return {}

        obs = {}
        for item in results:
            if item.get("datatype") != "TMAX":
                continue
            raw_date = item.get("date", "")[:10]  # "2026-01-01T00:00:00" → "2026-01-01"
            raw_value = item.get("value")
            if raw_value is None:
                continue
            # NOAA GHCND TMAX: tenths of degrees Celsius
            tmax_c = float(raw_value) / 10.0
            tmax_f = tmax_c * 9.0 / 5.0 + 32.0
            obs[raw_date] = round(tmax_f, 1)

        logger.info(f"[GHCND] Station {station_id}: fetched {len(obs)} TMAX observations "
                    f"({start_date} → {end_date})")
        return obs

    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response else "?"
        logger.error(f"[GHCND] NOAA API HTTP {status} for station {station_id}: {e}")
        return {}
    except Exception as e:
        logger.error(f"[GHCND] NOAA fetch failed for station {station_id}: {e}")
        return {}


# ── ERA5 Archive Fetch ────────────────────────────────────────────────────────

def _fetch_era5_tmax(lat: float, lon: float, timezone: str,
                     start_date: str, end_date: str) -> dict:
    """
    Fetch ERA5 reanalysis TMAX from Open-Meteo Archive API.
    Used as the model reference for computing bias vs. observed GHCND values.

    Returns:
        {"YYYY-MM-DD": tmax_f, ...} or {} on failure.
    """
    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude":         lat,
        "longitude":        lon,
        "start_date":       start_date,
        "end_date":         end_date,
        "daily":            "temperature_2m_max",
        "temperature_unit": "fahrenheit",
        "timezone":         timezone,
    }
    try:
        r = requests.get(url, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
        dates = data.get("daily", {}).get("time", [])
        temps = data.get("daily", {}).get("temperature_2m_max", [])
        result = {}
        for d, t in zip(dates, temps):
            if t is not None:
                result[d] = round(float(t), 1)
        logger.info(f"[GHCND] ERA5 archive: {len(result)} days for ({lat:.3f},{lon:.3f})")
        return result
    except Exception as e:
        logger.error(f"[GHCND] ERA5 archive fetch failed for ({lat},{lon}): {e}")
        return {}


# ── Bias Calculation ──────────────────────────────────────────────────────────

def compute_station_bias(ticker: str, token: str, lookback_days: int = 30) -> float | None:
    """
    Compute model bias for a city: mean(NOAA_observed_F − ERA5_model_F)
    over the last `lookback_days` days.

    Positive bias means the model systematically underestimates actual
    station temperature → we add this value to model forecasts.

    Returns:
        float bias in °F, or None if insufficient data.
    """
    station_cfg = GHCND_STATIONS.get(ticker)
    if not station_cfg:
        logger.warning(f"[GHCND] No station config for {ticker}")
        return None

    # Use yesterday as end (today's data is often incomplete until midnight)
    # Query window: yesterday as the end date (today's observations are often incomplete
    # until midnight); start is lookback_days before today for exactly lookback_days days.
    end_date   = (date.today() - timedelta(days=1)).isoformat()
    start_date = (date.today() - timedelta(days=lookback_days)).isoformat()

    noaa_obs  = _fetch_noaa_tmax(station_cfg["station"], start_date, end_date, token)
    era5_data = _fetch_era5_tmax(
        station_cfg["lat"], station_cfg["lon"],
        station_cfg["tz"], start_date, end_date
    )

    if not noaa_obs or not era5_data:
        logger.warning(f"[GHCND] {ticker}: insufficient data "
                       f"(noaa={len(noaa_obs)}, era5={len(era5_data)})")
        return None

    # Compute bias on days where both sources have data
    diffs = []
    for d in sorted(noaa_obs):
        if d in era5_data:
            diff = noaa_obs[d] - era5_data[d]
            diffs.append(diff)

    if len(diffs) < 5:
        logger.warning(f"[GHCND] {ticker}: only {len(diffs)} matching days — "
                       f"need ≥5 for reliable bias (falling back to hardcoded)")
        return None

    bias = round(sum(diffs) / len(diffs), 2)
    logger.info(
        f"[GHCND] {station_cfg['name']}: bias={bias:+.2f}°F "
        f"(n={len(diffs)} days, {start_date}→{end_date})"
    )
    return bias


# ── Cache Refresh ─────────────────────────────────────────────────────────────

def refresh_bias_cache() -> dict:
    """
    Refresh GHCND bias cache for all configured cities.
    Computes NOAA/ERA5 rolling bias; falls back to hardcoded for failures.

    Returns:
        {ticker: bias_f} dict (all cities, fallback used where needed).
    """
    token = _load_noaa_token()
    if not token:
        logger.warning("[GHCND] No noaa_cdo_token in secrets — using hardcoded fallbacks for all cities")
        return {}

    biases  = {}
    sources = {}  # track 'ghcnd' vs 'hardcoded' per ticker

    for ticker in GHCND_STATIONS:
        try:
            bias = compute_station_bias(ticker, token)
            if bias is not None:
                biases[ticker]  = bias
                sources[ticker] = "ghcnd"
            else:
                fallback = HARDCODED_BIAS_F.get(ticker, DEFAULT_HARDCODED_BIAS_F)
                biases[ticker]  = fallback
                sources[ticker] = "hardcoded_fallback"
                logger.info(f"[GHCND] {ticker}: GHCND failed, using hardcoded {fallback}°F")
        except Exception as e:
            fallback = HARDCODED_BIAS_F.get(ticker, DEFAULT_HARDCODED_BIAS_F)
            biases[ticker]  = fallback
            sources[ticker] = "hardcoded_error"
            logger.error(f"[GHCND] Error computing bias for {ticker}: {e} — "
                         f"using hardcoded {fallback}°F")

    _save_cache(biases, sources)
    return biases


# ── Public API ────────────────────────────────────────────────────────────────

def get_bias(ticker: str) -> float:
    """
    Get temperature bias correction for a city ticker.

    Lookup order:
      1. Fresh daily cache (logs/ghcnd_bias_cache.json updated today)
      2. Refresh cache from NOAA API if stale and token available
      3. Hardcoded fallback offsets

    Returns:
        bias in °F — add this value to model forecasts to align with
        actual station observations.
    """
    # 1. Try fresh cache
    if _cache_is_fresh():
        cached = _load_cache()
        if ticker in cached:
            return float(cached[ticker])

    # 2. Try to refresh cache (only if we have a token)
    if _load_noaa_token():
        try:
            fresh = refresh_bias_cache()
            if ticker in fresh:
                return float(fresh[ticker])
        except Exception as e:
            logger.warning(f"[GHCND] Cache refresh failed: {e} — using hardcoded fallback")

    # 3. Hardcoded fallback
    bias = HARDCODED_BIAS_F.get(ticker, DEFAULT_HARDCODED_BIAS_F)
    logger.info(f"[GHCND] {ticker}: using hardcoded fallback bias={bias}°F")
    return bias


def get_bias_source(ticker: str) -> str:
    """Return 'ghcnd', 'hardcoded_fallback', or 'hardcoded_error' for logging."""
    if _cache_is_fresh():
        try:
            raw = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
            return raw.get("sources", {}).get(ticker, "unknown")
        except Exception:
            pass
    return "hardcoded_fallback"


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    print("=== GHCND Bias Client Test ===\n")
    for t in GHCND_STATIONS:
        bias = get_bias(t)
        src  = get_bias_source(t)
        print(f"  {t:12}  bias={bias:+.2f}°F  source={src}")
