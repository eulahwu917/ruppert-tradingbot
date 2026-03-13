"""
Fed Rate Decision Client — v1 (Option B: slow repricing / structural window)
─────────────────────────────────────────────────────────────────────────────
Signal approach: Compare CME FedWatch EOD probability to Kalshi market price
2–7 days before FOMC meeting. Edge = abs(fedwatch_prob - kalshi_price).
Entry if edge > 12% and confidence > 55%.

v1 scope (secondary window only — per SA-1 Optimizer validation 2026-03-12):
  - Targets 2-7 day window before FOMC meetings (structural mispricing).
  - Does NOT attempt to capture the 30-60 min CPI/NFP post-print window
    (requires intraday data + calendar-triggered scan — deferred to v2).
  - Uses EOD FedWatch data (free CME scrape) — sufficient for slow repricing.
  - Skip if days_to_meeting < 2 (market efficient near decision day).
  - Skip if days_to_meeting > 7 (too early for reliable edge).

Data sources (all free):
  1. CME FedWatch public page scrape — current FOMC outcome probabilities
  2. FRED FEDFUNDS series CSV — current effective federal funds rate
  3. Kalshi API (public) — KXFEDDECISION market prices

IMPORTANT notes:
  - Favorite-longshot bias: NEVER enter positions on contracts < 15¢.
  - Day-before rule: If days_to_meeting < 2, market is fully efficient. Skip.
  - Contract selection: Trade highest-edge KXFEDDECISION outcome only.

Kalshi KXFEDDECISION outcomes:
  'maintain'  — rate unchanged (hold)
  'cut_25'    — 25bps cut
  'cut_50'    — 50bps+ cut
  'hike'      — rate hike

CME FedWatch outcome mapping:
  "No Change (Unchanged)" → maintain
  "25bps decrease"        → cut_25
  "50bps decrease"        → cut_50
  "25bps increase"        → hike
"""

import json
import logging
import re
import requests
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── FOMC Calendar 2026 ────────────────────────────────────────────────────────
# Decision announced on the second day of each 2-day meeting.
# Source: federalreserve.gov — verify/update annually.
FOMC_DECISION_DATES_2026 = [
    date(2026, 1, 29),
    date(2026, 3, 18),
    date(2026, 4, 29),
    date(2026, 6, 10),
    date(2026, 7, 29),
    date(2026, 9, 16),
    date(2026, 10, 28),
    date(2026, 12,  9),
]

# ── Strategy Parameters ───────────────────────────────────────────────────────
FED_MIN_EDGE        = 0.12   # 12% minimum edge to consider entry
FED_MIN_CONFIDENCE  = 0.55   # 55% minimum confidence
FED_WINDOW_MIN_DAYS = 2      # skip if < 2 days (market efficient)
FED_WINDOW_MAX_DAYS = 7      # skip if > 7 days (too early)
FED_MIN_KALSHI_PRICE = 0.15  # never trade contracts below 15¢ (favorite-longshot bias)

# ── File Paths ────────────────────────────────────────────────────────────────
_LOGS_DIR   = Path(__file__).parent / "logs"
_SCAN_FILE  = _LOGS_DIR / "fed_scan_latest.json"

# Kalshi public markets endpoint (no auth needed for reading)
KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"


# ── FOMC Date Utilities ───────────────────────────────────────────────────────

def next_fomc_meeting() -> tuple[date | None, int]:
    """
    Return (next_decision_date, days_until_decision).
    Returns (None, -1) if no upcoming meeting in 2026 calendar.
    """
    today = date.today()
    for decision_date in sorted(FOMC_DECISION_DATES_2026):
        if decision_date >= today:
            days_left = (decision_date - today).days
            return decision_date, days_left
    return None, -1


def is_in_signal_window() -> tuple[bool, date | None, int]:
    """
    Check if we're in the 2-7 day signal window before the next FOMC meeting.

    Returns:
        (in_window: bool, meeting_date: date | None, days_to_meeting: int)
    """
    meeting_date, days_left = next_fomc_meeting()
    if meeting_date is None:
        return False, None, -1
    in_window = FED_WINDOW_MIN_DAYS <= days_left <= FED_WINDOW_MAX_DAYS
    return in_window, meeting_date, days_left


# ── FRED Data ─────────────────────────────────────────────────────────────────

def get_current_fed_rate() -> float | None:
    """
    Fetch current effective federal funds rate from FRED CSV.
    URL: https://fred.stlouisfed.org/graph/fredgraph.csv?id=FEDFUNDS
    Returns most recent monthly rate value, or None on failure.
    """
    try:
        url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=FEDFUNDS"
        r   = requests.get(url, timeout=15)
        r.raise_for_status()
        lines = r.text.strip().splitlines()
        # Format: DATE,FEDFUNDS\n2026-02-01,4.33\n...
        for line in reversed(lines[1:]):  # skip header, iterate recent-first
            parts = line.strip().split(",")
            if len(parts) == 2 and parts[1] not in (".", ""):
                rate = float(parts[1])
                logger.info(f"[FedClient] FRED FEDFUNDS: {parts[0]} = {rate}%")
                return rate
        return None
    except Exception as e:
        logger.error(f"[FedClient] FRED fetch failed: {e}")
        return None


# ── CME FedWatch Scrape ───────────────────────────────────────────────────────

def _parse_fedwatch_json(data: dict, meeting_date: date) -> dict | None:
    """
    Parse CME FedWatch JSON response into {outcome: probability} dict.
    Tries multiple known CME response formats.

    Returns:
        {'maintain': float, 'cut_25': float, 'cut_50': float, 'hike': float}
        or None if parsing fails.
    """
    try:
        # Format A: meetingData list
        meeting_data = data.get("meetingData") or data.get("meetings") or []
        target_str   = meeting_date.strftime("%Y%m%d")

        for meeting in meeting_data:
            m_date = str(meeting.get("meetingDate", "") or meeting.get("date", ""))
            if target_str not in m_date and meeting_date.isoformat() not in m_date:
                continue

            probs = (meeting.get("probabilities") or
                     meeting.get("data", {}) or
                     meeting.get("impliedProbabilities", {}))
            if not probs:
                continue

            # Normalize keys to standard outcome names
            def _find(keys):
                for k in keys:
                    for pk, pv in probs.items():
                        if k.lower() in pk.lower():
                            return float(pv) / 100.0 if float(pv) > 1 else float(pv)
                return None

            result = {
                "maintain": _find(["unchanged", "no change", "hold", "maintain"]),
                "cut_25":   _find(["25bps decrease", "25 bps", "-25", "cut 25"]),
                "cut_50":   _find(["50bps", "50 bps", "-50", "cut 50", "50+"]),
                "hike":     _find(["increase", "hike", "+25", "raise"]),
            }
            if any(v is not None for v in result.values()):
                # Fill None with 0.0
                return {k: (v if v is not None else 0.0) for k, v in result.items()}

        return None

    except Exception as e:
        logger.debug(f"[FedClient] FedWatch JSON parse error: {e}")
        return None


def get_fedwatch_probabilities(meeting_date: date) -> dict | None:
    """
    Fetch CME FedWatch implied probabilities for an FOMC meeting.

    Tries two CME endpoints sequentially; returns None if both fail.

    Returns:
        {'maintain': float, 'cut_25': float, 'cut_50': float, 'hike': float}
        All values in [0, 1]. Or None on failure.
    """
    # Known CME FedWatch API endpoints (public, no auth needed)
    endpoints = [
        "https://www.cmegroup.com/CmeWS/mvc/FedWatch/currentFedWatchTool.getCMEFedWatchToolData.json",
        "https://www.cmegroup.com/CmeWS/mvc/FedWatch/fedwatchtool.getCMEFedWatchToolData.json",
    ]
    headers = {
        "User-Agent":  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept":      "application/json, text/plain, */*",
        "Referer":     "https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html",
    }

    for url in endpoints:
        try:
            r = requests.get(url, headers=headers, timeout=20)
            if r.status_code == 200:
                data   = r.json()
                result = _parse_fedwatch_json(data, meeting_date)
                if result:
                    logger.info(
                        f"[FedClient] FedWatch probs for {meeting_date}: "
                        f"maintain={result.get('maintain', 0):.1%} "
                        f"cut_25={result.get('cut_25', 0):.1%} "
                        f"cut_50={result.get('cut_50', 0):.1%}"
                    )
                    return result
        except Exception as e:
            logger.debug(f"[FedClient] FedWatch endpoint {url} failed: {e}")
            continue

    # HTML fallback: scrape probability from FedWatch tool page
    logger.warning("[FedClient] CME JSON endpoints failed — trying HTML scrape fallback")
    return _scrape_fedwatch_html(meeting_date)


def _scrape_fedwatch_html(meeting_date: date) -> dict | None:
    """
    Fallback: parse FedWatch probabilities from CME HTML page.
    Looks for embedded JSON data in script tags.
    Returns probability dict or None.
    """
    try:
        url     = "https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        r       = requests.get(url, headers=headers, timeout=20)
        r.raise_for_status()
        html = r.text

        # Look for JSON blobs containing probability data
        json_matches = re.findall(r'window\.__PRELOADED_STATE__\s*=\s*({.*?})\s*;', html, re.DOTALL)
        for match in json_matches:
            try:
                data   = json.loads(match)
                result = _parse_fedwatch_json(data, meeting_date)
                if result:
                    return result
            except Exception:
                continue

        logger.warning(f"[FedClient] HTML scrape could not extract FedWatch data for {meeting_date}")
        return None

    except Exception as e:
        logger.error(f"[FedClient] HTML scrape failed: {e}")
        return None


# ── Kalshi KXFEDDECISION Fetch ────────────────────────────────────────────────

def get_kalshi_fed_markets(meeting_date: date) -> list:
    """
    Fetch KXFEDDECISION markets from Kalshi public API for a given meeting.

    Returns list of market dicts, or [] on failure.
    Each dict includes: ticker, title, yes_ask, yes_bid, outcome_type.
    """
    try:
        url    = f"{KALSHI_BASE}/markets"
        params = {
            "series_ticker": "KXFEDDECISION",
            "status":        "open",
            "limit":         50,
        }
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        markets = r.json().get("markets", [])

        # Filter to markets relevant to the target meeting
        date_filters = [
            meeting_date.strftime("%y%b").upper(),   # "26MAR"
            meeting_date.strftime("%B").upper(),     # "MARCH"
            str(meeting_date.year),                  # "2026"
        ]

        relevant = []
        for m in markets:
            title  = (m.get("title", "") or "").upper()
            ticker = (m.get("ticker", "") or "").upper()
            if any(f in title or f in ticker for f in date_filters):
                relevant.append(m)

        if not relevant:
            # Fallback: take all open KXFEDDECISION markets if no date match
            relevant = markets
            logger.warning(
                f"[FedClient] No KXFEDDECISION markets matched date {meeting_date} — "
                f"returning all {len(markets)} open markets"
            )

        logger.info(f"[FedClient] Found {len(relevant)} KXFEDDECISION markets for {meeting_date}")
        return relevant

    except Exception as e:
        logger.error(f"[FedClient] Kalshi KXFEDDECISION fetch failed: {e}")
        return []


# ── Outcome Mapping ───────────────────────────────────────────────────────────

def _classify_kalshi_outcome(market: dict) -> str | None:
    """
    Map a Kalshi KXFEDDECISION market to a standard outcome name.
    Returns: 'maintain', 'cut_25', 'cut_50', 'hike', or None.
    """
    title  = (market.get("title", "") or "").lower()
    ticker = (market.get("ticker", "") or "").lower()
    text   = title + " " + ticker

    if any(w in text for w in ["maintain", "unchanged", "hold", "no change"]):
        return "maintain"
    if any(w in text for w in ["cut 25", "25bps", "25 bps", "decrease 25", "-25"]):
        return "cut_25"
    if any(w in text for w in ["cut 50", "50bps", "50 bps", "decrease 50", "-50", "50+"]):
        return "cut_50"
    if any(w in text for w in ["hike", "increase", "raise", "+25", "25bps increase"]):
        return "hike"
    return None


# ── Signal Computation ────────────────────────────────────────────────────────

def get_fed_signal(kalshi_client=None) -> dict | None:
    """
    Main signal function. Compare CME FedWatch probabilities to Kalshi market
    prices and compute edge for the upcoming FOMC meeting.

    Filters:
      - Only fires 2-7 days before meeting (secondary window)
      - Requires edge > 12% and confidence > 55%
      - Never enters contracts priced below 15¢ (favorite-longshot bias)

    Args:
        kalshi_client: KalshiClient instance (optional — uses public endpoint if None)

    Returns:
        Signal dict or None if no actionable opportunity.
        {
          'prob':          float,   # FedWatch probability for best outcome
          'confidence':    float,   # computed confidence score
          'edge':          float,   # abs(fedwatch_prob - kalshi_price)
          'direction':     str,     # 'yes' or 'no'
          'outcome':       str,     # 'maintain'|'cut_25'|'cut_50'|'hike'
          'ticker':        str,     # Kalshi market ticker
          'market_price':  float,   # Kalshi YES price (0-1)
          'meeting_date':  str,     # ISO date
          'days_to_meeting': int,
          'fed_rate':      float,   # current FEDFUNDS rate
          'fedwatch_probs': dict,   # all outcome probabilities from CME
          'signal_window': '2-7d',
          'skip_reason':   None,
        }
    """
    in_window, meeting_date, days_to_meeting = is_in_signal_window()

    if not in_window or meeting_date is None:
        reason = (
            f"days_to_meeting={days_to_meeting} — "
            + ("too close (market efficient)" if days_to_meeting < FED_WINDOW_MIN_DAYS
               else "too far out" if days_to_meeting > FED_WINDOW_MAX_DAYS
               else "no upcoming meeting in calendar")
        )
        logger.info(f"[FedClient] Outside signal window — skipping ({reason})")
        return None

    logger.info(f"[FedClient] In signal window: {days_to_meeting} days to {meeting_date} FOMC")

    # Fetch data
    fed_rate      = get_current_fed_rate()
    fedwatch_probs = get_fedwatch_probabilities(meeting_date)
    markets        = get_kalshi_fed_markets(meeting_date)

    if not fedwatch_probs:
        logger.warning("[FedClient] No FedWatch probability data — cannot compute edge")
        return {
            "skip_reason":     "fedwatch_unavailable",
            "meeting_date":    meeting_date.isoformat(),
            "days_to_meeting": days_to_meeting,
            "fed_rate":        fed_rate,
        }

    if not markets:
        logger.warning("[FedClient] No Kalshi KXFEDDECISION markets found")
        return {
            "skip_reason":     "kalshi_markets_unavailable",
            "meeting_date":    meeting_date.isoformat(),
            "days_to_meeting": days_to_meeting,
            "fed_rate":        fed_rate,
            "fedwatch_probs":  fedwatch_probs,
        }

    # Find best edge opportunity across all outcomes
    best_signal = None
    best_edge   = 0.0

    for market in markets:
        outcome = _classify_kalshi_outcome(market)
        if outcome is None:
            continue

        fedwatch_p = fedwatch_probs.get(outcome)
        if fedwatch_p is None:
            continue

        yes_ask = market.get("yes_ask")
        yes_bid = market.get("yes_bid", 0)
        if yes_ask is None or yes_ask <= 0:
            continue

        # Use midpoint when bid exists; else ask (conservative)
        if yes_bid and yes_bid > 0:
            kalshi_price = (yes_ask + yes_bid) / 2.0 / 100.0
        else:
            kalshi_price = yes_ask / 100.0

        # Favorite-longshot bias: skip contracts below 15¢
        if kalshi_price < FED_MIN_KALSHI_PRICE:
            logger.debug(
                f"[FedClient] Skipping {outcome} ({market.get('ticker','')}): "
                f"price={kalshi_price:.2f} < {FED_MIN_KALSHI_PRICE} (longshot bias filter)"
            )
            continue

        raw_edge = fedwatch_p - kalshi_price

        # Confidence: higher when FedWatch probability is extreme (>70% or <30%)
        # and when prices agree directionally
        base_conf = min(abs(fedwatch_p - 0.5) * 2, 1.0)  # 0 at 50-50, 1.0 at 0% or 100%
        confidence = round(0.5 + base_conf * 0.5, 3)     # compress to [0.50, 1.00] range

        # Direction: BUY YES if FedWatch prob > Kalshi price, BUY NO otherwise
        direction = "yes" if raw_edge > 0 else "no"
        edge      = abs(raw_edge)

        if edge > best_edge:
            best_edge = edge
            best_signal = {
                "prob":          round(fedwatch_p, 4),
                "confidence":    confidence,
                "edge":          round(edge, 4),
                "raw_edge":      round(raw_edge, 4),
                "direction":     direction,
                "outcome":       outcome,
                "ticker":        market.get("ticker", ""),
                "title":         market.get("title", ""),
                "market_price":  round(kalshi_price, 4),
                "yes_ask":       yes_ask,
                "yes_bid":       yes_bid,
                "meeting_date":  meeting_date.isoformat(),
                "days_to_meeting": days_to_meeting,
                "fed_rate":      fed_rate,
                "fedwatch_probs": fedwatch_probs,
                "signal_window": "2-7d",
                "skip_reason":   None,
            }

    if best_signal is None:
        logger.info("[FedClient] No classifiable KXFEDDECISION outcomes found")
        return {
            "skip_reason":     "no_classifiable_outcomes",
            "meeting_date":    meeting_date.isoformat(),
            "days_to_meeting": days_to_meeting,
            "fed_rate":        fed_rate,
            "fedwatch_probs":  fedwatch_probs,
        }

    # Strategy gates
    if best_signal["edge"] < FED_MIN_EDGE:
        logger.info(
            f"[FedClient] Edge {best_signal['edge']:.1%} < threshold {FED_MIN_EDGE:.1%} — skip"
        )
        best_signal["skip_reason"] = f"edge_below_threshold ({best_signal['edge']:.1%})"
        _save_scan_result(best_signal)
        return None

    if best_signal["confidence"] < FED_MIN_CONFIDENCE:
        logger.info(
            f"[FedClient] Confidence {best_signal['confidence']:.1%} < threshold "
            f"{FED_MIN_CONFIDENCE:.1%} — skip"
        )
        best_signal["skip_reason"] = f"confidence_below_threshold ({best_signal['confidence']:.1%})"
        _save_scan_result(best_signal)
        return None

    logger.info(
        f"[FedClient] SIGNAL: {best_signal['outcome'].upper()} {best_signal['direction'].upper()} "
        f"edge={best_signal['edge']:.1%} conf={best_signal['confidence']:.1%} "
        f"FedWatch={best_signal['prob']:.1%} Kalshi={best_signal['market_price']:.1%} "
        f"({days_to_meeting}d to meeting)"
    )

    _save_scan_result(best_signal)
    return best_signal


def _save_scan_result(signal: dict):
    """Write latest Fed scan result to logs/fed_scan_latest.json for dashboard."""
    try:
        _LOGS_DIR.mkdir(exist_ok=True)
        payload = {
            "scan_ts":         datetime.now(timezone.utc).isoformat(),
            "scan_date":       date.today().isoformat(),
            **signal,
        }
        _SCAN_FILE.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    except Exception as e:
        logger.warning(f"[FedClient] Could not save scan result: {e}")


# ── Scan-Only (no trade logic) ────────────────────────────────────────────────

def run_fed_scan(dry_run: bool = True) -> dict | None:
    """
    Run a Fed scan cycle. Returns signal dict or None.
    Trade execution is handled by ruppert_cycle.py (strategy gate + logger.log_trade).
    """
    signal = get_fed_signal()
    if signal and not signal.get("skip_reason"):
        logger.info(
            f"[FedClient] Actionable signal: {signal['outcome']} {signal['direction'].upper()} "
            f"@ {signal['market_price']:.0%} edge={signal['edge']:.1%}"
        )
    return signal


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    print("=== Fed Client Self-Test ===\n")

    in_w, mtg, days = is_in_signal_window()
    print(f"Next FOMC: {mtg}  |  Days to meeting: {days}  |  In window: {in_w}")

    rate = get_current_fed_rate()
    print(f"FEDFUNDS rate: {rate}%")

    if mtg:
        print(f"\nFetching FedWatch probabilities for {mtg}...")
        probs = get_fedwatch_probabilities(mtg)
        if probs:
            for outcome, p in probs.items():
                print(f"  {outcome:12} {p:.1%}")
        else:
            print("  FedWatch data unavailable (scrape may need updating)")

        print(f"\nFetching Kalshi KXFEDDECISION markets...")
        markets = get_kalshi_fed_markets(mtg)
        print(f"  Found {len(markets)} markets")
        for m in markets[:5]:
            print(f"  {m.get('ticker','')} YES={m.get('yes_ask')}¢ / {m.get('title','')[:60]}")

    print("\nRunning full Fed signal...")
    sig = get_fed_signal()
    if sig:
        if sig.get("skip_reason"):
            print(f"  Skipped: {sig['skip_reason']}")
        else:
            print(f"  SIGNAL: {sig['outcome']} {sig['direction'].upper()} "
                  f"edge={sig['edge']:.1%} conf={sig['confidence']:.1%}")
    else:
        print("  No signal (outside window or no data)")
