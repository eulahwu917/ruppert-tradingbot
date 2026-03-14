"""
Edge Detector v3 — Multi-source weather signal
─────────────────────────────────────────────────────────────
Primary signal:  Open-Meteo multi-model ensemble (ECMWF + GEFS + ICON)
  - ECMWF IFS 0.25° (ecmwf_ifs025) — 51 members, weight 40%
  - GFS/GEFS Seamless (gfs_seamless) — 31 members, weight 40%
  - ICON Global (icon_global)         — 40 members, weight 20%
Secondary signal: NWS current observation (live temp)
Fallback signal:  NOAA single-model probability (original method)

Key improvements:
  v2: GFS 31-member ensemble replaces single NOAA probability.
  v3: ECMWF + ICON added (15-20% accuracy gain at 3-7 day range).
      NOAA GHCND rolling bias correction replaces hardcoded per-city offsets.
      Bias refreshed daily from NOAA CDO API; falls back to hardcoded if unavailable.
      Weighted ensemble: ECMWF 40% + GEFS 40% + ICON 20%.
      If any model fails, remaining models carry renormalized weight.

Confidence score filters out low-agreement signals automatically.
Divergence across models (ECMWF vs GEFS > 4°F) degrades confidence.
"""

import re
import logging
from datetime import date, datetime
from noaa_client import get_probability_for_temp_range
from openmeteo_client import get_full_weather_signal, CITIES
import config

# GHCND bias client — imported for logging/monitoring; bias is applied
# inside openmeteo_client.get_full_weather_signal() automatically.
try:
    from ghcnd_client import get_bias_source as _ghcnd_source
    _GHCND_AVAILABLE = True
except ImportError:
    _GHCND_AVAILABLE = False

logger = logging.getLogger(__name__)

# Map Kalshi series tickers to their Open-Meteo city records
TICKER_TO_SERIES = {
    # Original cities
    "KXHIGHNY":   "KXHIGHNY",
    "KXHIGHLA":   "KXHIGHLA",
    "KXHIGHCHI":  "KXHIGHCHI",
    "KXHIGHHOU":  "KXHIGHHOU",
    "KXHIGHMIA":  "KXHIGHMIA",
    "KXHIGHPHX":  "KXHIGHPHX",
    # Expanded cities (added 2026-03-13)
    "KXHIGHAUS":  "KXHIGHAUS",
    "KXHIGHDEN":  "KXHIGHDEN",
    "KXHIGHLAX":  "KXHIGHLAX",
    "KXHIGHPHIL": "KXHIGHPHIL",
    "KXHIGHTMIN": "KXHIGHTMIN",
    "KXHIGHTDAL": "KXHIGHTDAL",
    "KXHIGHTDC":  "KXHIGHTDC",
    "KXHIGHTLV":  "KXHIGHTLV",
    "KXHIGHTNOU": "KXHIGHTNOU",
    "KXHIGHTOKC": "KXHIGHTOKC",
    "KXHIGHTSFO": "KXHIGHTSFO",
    "KXHIGHTSEA": "KXHIGHTSEA",
    "KXHIGHTSATX":"KXHIGHTSATX",
    "KXHIGHTATL": "KXHIGHTATL",
}

# Minimum ensemble confidence to trade (0-1 scale)
# 0.5 = 75% of members agree (25/31), 0.7 = 85% agree (26/31)
MIN_ENSEMBLE_CONFIDENCE = 0.5

# Title keyword → city name (for NOAA fallback)
CITY_MAP = {
    # Original cities
    'new york': 'NYC', 'nyc': 'NYC', 'ny ': 'NYC',
    'los angeles': 'LA', 'l.a.': 'LA',
    'chicago': 'Chicago',
    'houston': 'Houston',
    'miami': 'Miami',
    'phoenix': 'Phoenix',
    # Expanded cities (added 2026-03-13)
    'austin': 'Austin',
    'denver': 'Denver',
    'philadelphia': 'Philadelphia', 'philly': 'Philadelphia',
    'minneapolis': 'Minneapolis',
    'dallas': 'Dallas',
    'washington': 'Washington DC', 'washington dc': 'Washington DC',
    'las vegas': 'Las Vegas',
    'new orleans': 'New Orleans',
    'oklahoma city': 'Oklahoma City', 'okc': 'Oklahoma City',
    'san francisco': 'San Francisco',
    'seattle': 'Seattle',
    'san antonio': 'San Antonio',
    'atlanta': 'Atlanta',
}


def parse_temp_range_from_title(title: str):
    """Extract temperature threshold from market title.
    Returns (low_f, high_f) tuple — high_f=999 means 'above low_f'.
    """
    title_lower = title.lower()

    # Match "60-70" or "60 to 70" or "**60-70**"
    range_match = re.search(r'(\d+)\s*[-–to]+\s*(\d+)', title_lower)
    if range_match:
        return int(range_match.group(1)), int(range_match.group(2))

    above_match = re.search(r'(?:above|over)\s*(\d+)', title_lower)
    if above_match:
        return int(above_match.group(1)), 999

    below_match = re.search(r'(?:below|under)\s*(\d+)', title_lower)
    if below_match:
        return -999, int(below_match.group(1))

    return None


def classify_market_type(temp_range) -> str:
    """
    Classify market as T_upper, T_lower, or B_band.

    T_upper: upper tail markets ("above X°F") — YES settles ~5% of time
    T_lower: lower tail markets ("below X°F") — YES settles ~5% of time
    B_band:  band markets ("X–Y°F range")

    Backtest finding: T-type markets settle YES only ~5% of the time.
    Strategy: apply a soft confidence prior (longshot bias) rather than
    forcing direction. Strong signals still override the prior.
    """
    if temp_range is None:
        return "B_band"
    low_f, high_f = temp_range
    if high_f == 999:
        return "T_upper"
    if low_f == -999:
        return "T_lower"
    return "B_band"


def parse_city_from_title(title: str):
    title_lower = title.lower()
    for keyword, city in CITY_MAP.items():
        if keyword in title_lower:
            return city
    return None


def get_series_from_ticker(ticker: str) -> str:
    """Extract series ticker from full market ticker.
    KXHIGHMIA-26MAR10-B84.5 → KXHIGHMIA
    """
    return ticker.split('-')[0].upper()


def parse_date_from_ticker(ticker: str) -> date:
    """Parse contract date from ticker like KXHIGHMIA-26MAR11-B84.5 → 2026-03-11"""
    try:
        parts = ticker.split('-')
        if len(parts) >= 2:
            date_str = parts[1]  # e.g. "26MAR11"
            return datetime.strptime("20" + date_str, "%Y%b%d").date()
    except Exception:
        pass
    return date.today()


def parse_threshold_from_ticker(ticker: str) -> float:
    """Extract temperature threshold from ticker KXHIGHMIA-26MAR10-B84.5 → 84.5"""
    try:
        parts = ticker.split('-')
        for part in parts:
            if part.startswith('B') and '.' in part:
                return float(part[1:])
            elif part.startswith('B') and part[1:].isdigit():
                return float(part[1:])
    except Exception:
        pass
    return None


def analyze_market(market: dict) -> dict | None:
    """
    Analyze a single Kalshi market for edge.

    Signal hierarchy:
      1. Open-Meteo ensemble (31 GFS members) — primary
      2. NOAA single probability — fallback if ensemble fails
      3. Skip if confidence below threshold

    Returns opportunity dict or None.
    """
    title   = market.get('title', '')
    ticker  = market.get('ticker', '')
    yes_ask = market.get('yes_ask', 0)

    if not yes_ask or yes_ask <= 0:
        return None

    series  = get_series_from_ticker(ticker)
    market_prob = yes_ask / 100

    # ── Parse contract metadata ───────────────────────────────────────────────
    target_date = parse_date_from_ticker(ticker)
    threshold_f = parse_threshold_from_ticker(ticker)

    temp_range   = parse_temp_range_from_title(title)
    city_name    = parse_city_from_title(title)
    market_type  = classify_market_type(temp_range)

    # ── Get weather signal ────────────────────────────────────────────────────
    model_prob  = None
    confidence  = 0.0
    signal_src  = "unknown"
    ensemble_data = None

    if series in TICKER_TO_SERIES and threshold_f is not None:
        # Primary: Open-Meteo multi-model ensemble (ECMWF + GEFS + ICON)
        # Bias correction: NOAA GHCND rolling bias (or hardcoded fallback)
        if _GHCND_AVAILABLE:
            bias_src = _ghcnd_source(series)
            logger.debug(f"[Edge] {ticker}: bias source = {bias_src}")

        signal = get_full_weather_signal(series, threshold_f, target_date)
        ensemble_data = signal

        if signal.get("final_prob") is not None:
            model_prob = signal["final_prob"]
            confidence = signal.get("final_confidence", 0.0)
            signal_src = "open_meteo_multi_model"
            ens = signal.get("ensemble", {})

            # NWS data unavailable — degrade confidence
            # nws_current_f is the combined NWS result (official → legacy obs fallback);
            # None means both NWS sources failed (e.g. Miami MFL 404, network error).
            nws_data = signal.get("nws_current_f")
            if nws_data is None:
                confidence = max(confidence - 0.15, 0.50)
                logger.warning(
                    f"[Edge] {ticker}: NWS data unavailable — confidence degraded "
                    f"by 0.15 → {confidence:.2f} (floored at 0.50)"
                )

            models_used_names = [m.get("model", "?") for m in signal.get("models_used", [])]
            logger.info(
                f"[Edge] {ticker}: multi-model ensemble [{', '.join(models_used_names)}] "
                f"primary={ens.get('members_above')}/{ens.get('total_members')} "
                f"above {threshold_f}°F → prob={model_prob:.2f} conf={confidence:.2f} "
                f"bias={signal.get('bias_applied_f',0):.1f}°F({signal.get('bias_source','?')})"
            )

    # Fallback: NOAA single probability
    if model_prob is None and city_name and temp_range:
        low_f, high_f = temp_range
        model_prob = get_probability_for_temp_range(city_name, low_f, high_f)
        confidence  = 0.3   # NOAA single model — lower confidence
        signal_src  = "noaa_fallback"
        if model_prob is not None:
            logger.info(f"[Edge] {ticker}: NOAA fallback prob={model_prob:.2f}")

    if model_prob is None:
        return None

    # ── Confidence gate ───────────────────────────────────────────────────────
    if confidence < MIN_ENSEMBLE_CONFIDENCE and signal_src == "open_meteo_ensemble":
        logger.info(f"[Edge] {ticker}: skipping — low ensemble confidence ({confidence:.2f})")
        return None

    # ── Edge calculation ──────────────────────────────────────────────────────
    edge = model_prob - market_prob

    is_t_market = market_type in ("T_upper", "T_lower")

    if abs(edge) < config.MIN_EDGE_THRESHOLD:
        return None

    # Signal decides the side — never force direction
    side = 'yes' if edge > 0 else 'no'

    # T-market soft prior: longshot bias — crowds systematically overprice rare
    # tail events (YES settles ~5% of the time). We nudge confidence down for
    # YES and up for NO when the signal is weak (|edge| <= 0.30).
    # Strong signals (|edge| > 0.30) are trusted as-is and override this prior.
    if is_t_market and abs(edge) <= 0.30:
        if side == 'no':
            confidence = min(confidence * 1.15, 1.0)
        elif side == 'yes':
            confidence = confidence * 0.85
        logger.info(
            f"[Edge] {ticker}: T-market ({market_type}) — soft prior applied "
            f"(longshot bias), side={side}, adjusted confidence={confidence:.2f}"
        )

    win_prob  = model_prob if side == 'yes' else (1 - model_prob)
    bet_price = yes_ask if side == 'yes' else (100 - yes_ask)

    # ── Build result ──────────────────────────────────────────────────────────
    result = {
        'ticker':      ticker,
        'title':       title,
        'city':        city_name,
        'market_type': market_type,
        'temp_range':  temp_range,
        'threshold_f': threshold_f,
        'target_date': target_date.isoformat(),
        'is_same_day': (target_date == date.today()),
        'market_prob': round(market_prob, 4),
        'noaa_prob':   round(model_prob, 4),   # kept for dashboard compat
        'model_prob':  round(model_prob, 4),
        'win_prob':    round(win_prob, 4),
        'edge':        round(edge, 4),
        'confidence':  round(confidence, 4),
        'signal_src':  signal_src,
        'side':        side,
        'yes_price':   yes_ask,
        'bet_price':   bet_price,
        'action':      f"BUY {side.upper()} at {bet_price}c",
    }

    # Attach ensemble detail if available
    nws_degraded = False
    if ensemble_data:
        ens = ensemble_data.get("ensemble", {})
        result['ensemble_median']  = ens.get("ensemble_median")
        result['ensemble_mean']    = ens.get("ensemble_mean")
        result['ensemble_min']     = ens.get("ensemble_min")
        result['ensemble_max']     = ens.get("ensemble_max")
        result['members_above']    = ens.get("members_above")
        result['total_members']    = ens.get("total_members")
        result['current_temp_f']   = ensemble_data.get("conditions", {}).get("current_temp_f")
        result['today_high_f']     = ensemble_data.get("conditions", {}).get("today_high_f")
        result['bias_applied_f']   = ensemble_data.get("bias_applied_f")
        result['bias_source']      = ensemble_data.get("bias_source")
        result['models_used']      = ensemble_data.get("models_used", [])
        # Flag whether NWS was degraded (set in confidence block above)
        result['nws_degraded']     = ensemble_data.get("nws_current_f") is None

    # Second line of defense: skip same-day markets after city's local 2pm
    # (primary skip is in main.py; this catches any path that bypasses it)
    if ensemble_data and ensemble_data.get('is_same_day'):
        city_hours = (ensemble_data.get('conditions') or {}).get('hours_since_midnight', 0)
        if city_hours >= 14:
            return None  # day's high already observed — no valid signal

    return result


def find_opportunities(markets: list) -> list:
    """Scan all markets and return edge opportunities sorted by edge size."""
    opportunities = []
    for market in markets:
        try:
            opp = analyze_market(market)
            if opp:
                opportunities.append(opp)
        except Exception as e:
            logger.error(f"[Edge] Error analyzing {market.get('ticker', '?')}: {e}")

    opportunities.sort(key=lambda x: abs(x['edge']), reverse=True)
    return opportunities


if __name__ == '__main__':
    import json
    logging.basicConfig(level=logging.INFO)

    print("\n=== Band Market Test (Miami 84-85°F) ===")
    mock_band = {
        'ticker': 'KXHIGHMIA-26MAR11-B84.5',
        'title': 'Will the **high temp in Miami** be 84-85° on Mar 11, 2026?',
        'yes_ask': 33,
    }
    result = analyze_market(mock_band)
    print(json.dumps(result, indent=2, default=str))

    print("\n=== T-Upper Market Test (Chicago above 80°F) ===")
    mock_t_upper = {
        'ticker': 'KXHIGHCHI-26MAR11-T80',
        'title': 'Will the **high temp in Chicago** be above 80° on Mar 11, 2026?',
        'yes_ask': 15,
    }
    result_t = analyze_market(mock_t_upper)
    print(json.dumps(result_t, indent=2, default=str))

    print("\n=== Market Type Classification Tests ===")
    tests = [
        ("Will Miami be 84-85°F?", (84, 85)),
        ("Will Chicago be above 80°F?", (80, 999)),
        ("Will NYC be below 30°F?", (-999, 30)),
    ]
    for title, expected_range in tests:
        mt = classify_market_type(expected_range)
        print(f"  '{title}' => {mt}")
