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


def _safe_int(val, default=0):
    """Safely cast API numeric fields that may arrive as float strings (e.g. '2563.00')."""
    try:
        return int(float(val)) if val is not None else default
    except (ValueError, TypeError):
        return default


def _shadow_log_yes_signal(signal: dict):
    """Log YES weather signals as counterfactuals -- never executed, observation only."""
    import json
    from pathlib import Path
    from datetime import datetime, timezone
    shadow_file = Path(__file__).parent / 'logs' / 'weather_yes_shadow.jsonl'
    try:
        shadow_file.parent.mkdir(exist_ok=True)
        entry = {
            'ts': datetime.now(timezone.utc).isoformat(),
            'ticker': signal.get('ticker', ''),
            'predicted_prob': signal.get('win_prob', signal.get('prob')),
            'market_price': signal.get('market_price', signal.get('yes_ask')),
            'edge': signal.get('edge'),
            'direction': 'yes',
            'note': 'counterfactual -- direction filter blocked execution'
        }
        with open(shadow_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry) + '\n')
    except Exception:
        pass  # Never crash on shadow logging

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


def apply_volume_tier(edge: float, volume: int) -> tuple[float, str]:
    """
    Discount edge score for thin markets.

    Thin markets need higher raw edge to clear MIN_EDGE_THRESHOLD.
    Returns (adjusted_edge, tier_label) where tier_label is 'thick'/'mid'/'thin'.

    Args:
        edge: Raw edge score (model_prob - market_prob)
        volume: 24-hour volume in contracts (volume_24h_fp from Kalshi API)
    """
    if volume >= config.VOLUME_TIER_THICK:
        return edge, 'thick'
    elif volume >= config.VOLUME_TIER_MID:
        return edge * config.VOLUME_DISCOUNT_MID, 'mid'
    else:
        return edge * config.VOLUME_DISCOUNT_THIN, 'thin'


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
    """Extract temperature threshold from ticker.
    Handles both B-band (KXHIGHMIA-26MAR10-B84.5 → 84.5)
    and T-upper (KXHIGHCHI-26MAR11-T80 → 80.0) formats.
    """
    try:
        parts = ticker.split('-')
        for part in parts:
            # B-band format: B84.5 or B84
            if part.startswith('B') and len(part) > 1:
                val = part[1:]
                try:
                    return float(val)
                except ValueError:
                    pass
            # T-upper format: T80 or T84.5 (P1-4 fix: added T support)
            elif part.startswith('T') and len(part) > 1 and not part.startswith('TM'):
                val = part[1:]
                try:
                    return float(val)
                except ValueError:
                    pass
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

    # ── Ghost/penny market filter ─────────────────────────────────────────────
    if yes_ask < config.MIN_YES_ASK:
        logger.debug(
            f"[Edge] {ticker}: skipping — yes_ask={yes_ask}c below "
            f"MIN_YES_ASK={config.MIN_YES_ASK}c"
        )
        return None

    series  = get_series_from_ticker(ticker)
    market_prob = yes_ask / 100

    # ── Parse contract metadata ───────────────────────────────────────────────
    target_date = parse_date_from_ticker(ticker)
    threshold_f = parse_threshold_from_ticker(ticker)

    temp_range   = parse_temp_range_from_title(title)
    city_name    = parse_city_from_title(title)
    market_type  = classify_market_type(temp_range)

    # P1-4 fix: classify_market_type falls back to B_band when temp_range is None.
    # For T-markets (e.g. KXHIGHCHI-26MAR11-T80), title regex often fails to extract
    # a range. Use the ticker band portion (3rd segment) to infer market type.
    if market_type == "B_band" and temp_range is None and threshold_f is not None:
        parts = ticker.split('-')
        if len(parts) >= 3:
            band_part = parts[2].upper()
            if band_part.startswith('T') and not band_part.startswith('TM'):
                # T-prefix band = T_upper market (above threshold)
                market_type = "T_upper"
                logger.debug(
                    f"[Edge] {ticker}: T-market inferred from ticker band '{band_part}' "
                    f"(title regex returned None)"
                )

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

    # ── Config confidence gate (MIN_CONFIDENCE from config) ──────────────────
    min_conf = getattr(config, 'MIN_CONFIDENCE', {}).get('weather', 0.50)
    if confidence < min_conf:
        logger.info(
            f"[Edge] {ticker}: skipping — confidence {confidence:.2f} < "
            f"MIN_CONFIDENCE['weather'] {min_conf:.3f}"
        )
        return None

    # ── Model/market divergence gate ─────────────────────────────────────────
    # If |model_prob - market_prob| > MAX_MODEL_MARKET_DIVERGENCE, the market
    # is telling us something our model doesn't know (ghost market, unvalidated city,
    # warm bias error). Skip rather than fight the tape.
    # For T_lower markets, model_prob = P(high >= threshold) but market_prob = P(YES) = P(high < threshold).
    # Use semantically equivalent probability for a fair divergence comparison.
    _divergence_model = (1.0 - model_prob) if market_type == "T_lower" else model_prob
    _divergence_gap = abs(_divergence_model - market_prob)
    if _divergence_gap > config.MAX_MODEL_MARKET_DIVERGENCE:
        logger.debug(
            f"[Edge] {ticker}: skipping — model/market divergence "
            f"{_divergence_gap:.0%} exceeds threshold"
        )
        return None

    # ── T_lower probability flip ──────────────────────────────────────────────
    # The ensemble always computes P(high >= threshold_f).
    # For T_lower markets ("Will high be <X°F?"), the Kalshi YES outcome is
    # P(high < threshold), so we must flip: model_prob = 1 - P(high >= threshold).
    if market_type == "T_lower":
        model_prob = 1.0 - model_prob
        logger.debug(f"[Edge] {ticker}: T_lower market — flipped model_prob to {model_prob:.4f}")

    # ── Volume-tier edge discounting ──────────────────────────────────────────
    # Discount edge for thin markets before divergence gate and threshold check.
    # Thin markets need higher raw edge to pass. Uses volume_24h_fp from market data.
    _volume = _safe_int(market.get('volume_24h_fp', 0))
    _raw_edge = model_prob - market_prob
    _adj_edge, _volume_tier = apply_volume_tier(_raw_edge, _volume)
    if _volume_tier != 'thick':
        logger.debug(
            f"[Edge] {ticker}: volume_tier={_volume_tier} (vol={_volume}) — "
            f"edge {_raw_edge:.4f} → {_adj_edge:.4f}"
        )
    # ── Edge calculation ──────────────────────────────────────────────────────
    edge = _adj_edge

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
        'raw_edge':        round(_raw_edge, 4),
        'volume_tier':     _volume_tier,
        'volume_tier_miss': (
            _volume_tier in ('mid', 'thin') and
            abs(_raw_edge) >= config.MIN_EDGE_THRESHOLD and
            abs(_adj_edge) >= config.MIN_EDGE_THRESHOLD
        ),
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

    # Same-day cutoff handled upstream in main.py via MIN_HOURS_TO_CLOSE
    # (uses Kalshi close_time directly — no timezone math needed)

    return result


def find_opportunities(markets: list) -> list:
    """Scan all markets and return edge opportunities sorted by edge size."""
    import time as _time
    from openmeteo_client import clear_signal_cache as _clear_cache
    _clear_cache()  # fresh cache for this scan batch

    total = len(markets)
    opportunities = []
    _errors = 0
    _start = _time.monotonic()
    for idx, market in enumerate(markets):
        try:
            opp = analyze_market(market)
            if opp:
                opportunities.append(opp)
        except Exception as e:
            _errors += 1
            logger.error(f"[Edge] Error analyzing {market.get('ticker', '?')}: {e}")
        # Progress logging every 20 markets (print, not logger — no handler when imported)
        if (idx + 1) % 20 == 0 or (idx + 1) == total:
            elapsed = _time.monotonic() - _start
            print(
                f"  [Edge] Progress: {idx+1}/{total} markets analyzed "
                f"({len(opportunities)} hits, {_errors} errors, {elapsed:.0f}s elapsed)",
                flush=True,
            )

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
