"""
Fed Rate Decision Client — v1 (Option B: slow repricing / structural window)
─────────────────────────────────────────────────────────────────────────────
Signal approach: Compare Polymarket FOMC implied probability to Kalshi market
price 2–7 days before FOMC meeting. Edge = abs(polymarket_prob - kalshi_price).
Entry if edge > 12% and confidence > 55%.

v1 scope (secondary window only — per SA-1 Optimizer validation 2026-03-12):
  - Targets 2-7 day window before FOMC meetings (structural mispricing).
  - Does NOT attempt to capture the 30-60 min CPI/NFP post-print window
    (requires intraday data + calendar-triggered scan — deferred to v2).
  - Uses Polymarket FOMC market prices (free, no auth) — sufficient for slow repricing.
  - Skip if days_to_meeting < 2 (market efficient near decision day).
  - Skip if days_to_meeting > 7 (too early for reliable edge).

Data sources (all free, no auth required):
  1. Polymarket gamma API — active FOMC rate decision market prices
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

Polymarket FOMC outcome mapping (by question text):
  "hold" / "maintain" / "unchanged" / "pause" → maintain
  "cut 25" / "25bps" / "cut rates" / "decrease" → cut_25
  "cut 50" / "50bps" / "50+"                    → cut_50
  "hike" / "increase" / "raise"                 → hike
"""

import json
import logging
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
    date(2026, 5,  7),
    date(2026, 6, 17),
    date(2026, 7, 29),
    date(2026, 9, 16),
    date(2026, 10, 28),
    date(2026, 12, 16),
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


# ── Polymarket FOMC Data ──────────────────────────────────────────────────────

# Slug config — maps FOMC decision date (ISO) → Polymarket event slug
# Slug-based lookup is the only reliable method; tag=fomc filter returns stale markets.
_FOMC_SLUGS_FILE    = Path(__file__).parent / "config" / "fomc_slugs.json"
POLYMARKET_EVENTS_URL = "https://gamma-api.polymarket.com/events"


def _classify_polymarket_outcome(question: str) -> str | None:
    """
    Map a Polymarket FOMC market question to a standard outcome name.
    Returns: 'maintain', 'cut_25', 'cut_50', 'hike', or None.

    Order matters: check cut_50 before cut_25 to avoid false matches.
    """
    q = question.lower()
    if any(w in q for w in ["cut 50", "50bps", "50 bps", "-50", "50+"]):
        return "cut_50"
    if any(w in q for w in ["cut 25", "25bps", "25 bps", "-25", "cut rates", "decrease"]):
        return "cut_25"
    if any(w in q for w in ["hold", "maintain", "unchanged", "no change", "pause"]):
        return "maintain"
    if any(w in q for w in ["hike", "increase", "raise"]):
        return "hike"
    return None


def get_polymarket_fomc_probabilities(meeting_date: date) -> dict | None:
    """
    Fetch FOMC rate decision probabilities from Polymarket via direct slug lookup.

    Endpoint: https://gamma-api.polymarket.com/events?slug=<slug>

    Slug-based lookup is the only reliable method — the tag=fomc filter returns
    unrelated old markets and cannot be trusted. Slugs are maintained in
    logs/fomc_slugs.json keyed by FOMC decision date (ISO format).

    Flow:
      1. Load fomc_slugs.json
      2. Look up slug for meeting_date
      3. If slug is None/missing → save no_signal(slug_unknown) and return sentinel
      4. Fetch /events?slug=<slug>
      5. Parse all outcome markets; classify each by question text
      6. Return {outcome: YES_price} dict (all values in [0, 1])

    Returns:
        - {'maintain': float, ...}    on success
        - {"status": "no_signal", "skip_reason": "slug_unknown", ...}  if slug not yet known
        - None                        on API / parse error
    """
    date_key = meeting_date.isoformat()  # e.g. "2026-03-18"

    # ── 1. Load slug config ──────────────────────────────────────────────────
    try:
        with open(_FOMC_SLUGS_FILE, encoding="utf-8") as f:
            fomc_slugs: dict = json.load(f)
    except Exception as e:
        logger.error(f"[FedClient] Could not load fomc_slugs.json: {e}")
        return None

    # ── 2. Look up slug ──────────────────────────────────────────────────────
    slug = fomc_slugs.get(date_key)  # None if key missing or value is null

    # ── 3. Slug unknown → early exit ─────────────────────────────────────────
    if not slug:
        logger.info(
            f"[FedClient] No Polymarket slug configured for {date_key} — "
            f"update config/fomc_slugs.json when slug becomes available"
        )
        days_left = (meeting_date - date.today()).days
        no_signal: dict = {
            "status":          "no_signal",
            "skip_reason":     "slug_unknown",
            "meeting_date":    date_key,
            "days_to_meeting": days_left,
        }
        _save_scan_result(no_signal)
        return no_signal  # sentinel dict — caller must check status

    # ── 4. Fetch event by slug ───────────────────────────────────────────────
    try:
        r = requests.get(POLYMARKET_EVENTS_URL, params={"slug": slug}, timeout=15)
        r.raise_for_status()
        events = r.json()

        if not events:
            logger.warning(f"[FedClient] No Polymarket event returned for slug '{slug}'")
            return None

        event   = events[0] if isinstance(events, list) else events
        markets = event.get("markets", [])

        if not markets:
            logger.warning(f"[FedClient] Event '{slug}' has no nested markets")
            return None

        # ── 5. Parse outcome markets ─────────────────────────────────────────
        # Primary target: "no change" market — the outcome we care most about.
        # outcomePrices: ["<yes_price>", "<no_price>"] as string floats (0-1 scale)
        probs: dict[str, float] = {}
        for m in markets:
            question       = m.get("question", "")
            outcome_prices = m.get("outcomePrices", [])
            if not outcome_prices:
                continue

            # Prefer explicit "no change" check before general classifier
            if "no change" in question.lower():
                try:
                    yes_price = float(outcome_prices[0])
                    probs["maintain"] = round(yes_price, 4)
                    logger.info(
                        f"[FedClient] Polymarket no-change prob: {yes_price:.1%} "
                        f"('{question}', slug: {slug})"
                    )
                except (ValueError, IndexError) as exc:
                    logger.warning(
                        f"[FedClient] outcomePrices parse error for '{question}': {exc}"
                    )
                continue

            # Classify remaining outcomes via keyword mapping
            outcome = _classify_polymarket_outcome(question)
            if outcome is None:
                logger.debug(f"[FedClient] Polymarket: unclassified question — '{question}'")
                continue
            try:
                yes_price = float(outcome_prices[0])
                probs[outcome] = round(yes_price, 4)
            except (ValueError, IndexError) as exc:
                logger.debug(
                    f"[FedClient] Polymarket price parse error for '{question}': {exc}"
                )

        if not probs:
            logger.warning(
                f"[FedClient] Event '{slug}': markets found but none could be classified"
            )
            return None

        logger.info(
            f"[FedClient] Polymarket probs for {meeting_date} (slug={slug}): "
            + " ".join(f"{k}={v:.1%}" for k, v in probs.items())
        )
        return probs

    except Exception as e:
        logger.error(f"[FedClient] Polymarket FOMC fetch failed (slug={slug}): {e}")
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
    Main signal function. Compare Polymarket FOMC implied probabilities to
    Kalshi market prices and compute edge for the upcoming FOMC meeting.

    Filters:
      - Only fires 2-7 days before meeting (secondary window)
      - Requires edge > 12% and confidence > 55%
      - Never enters contracts priced below 15¢ (favorite-longshot bias)

    Args:
        kalshi_client: KalshiClient instance (optional — uses public endpoint if None)

    Returns:
        Signal dict or None if no actionable opportunity.
        {
          'prob':             float,  # Polymarket YES price for best outcome
          'confidence':       float,  # computed confidence score
          'edge':             float,  # abs(polymarket_prob - kalshi_price)
          'direction':        str,    # 'yes' or 'no'
          'outcome':          str,    # 'maintain'|'cut_25'|'cut_50'|'hike'
          'ticker':           str,    # Kalshi market ticker
          'market_price':     float,  # Kalshi YES price (0-1)
          'meeting_date':     str,    # ISO date
          'days_to_meeting':  int,
          'fed_rate':         float,  # current FEDFUNDS rate
          'polymarket_probs': dict,   # all outcome probabilities from Polymarket
          'prob_source':      str,    # 'polymarket'
          'signal_window':    '2-7d',
          'skip_reason':      None,
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
        _save_scan_result({
            "status":        "no_signal",
            "skip_reason":   "outside_window",
            "reason":        reason,
            "meeting_date":  meeting_date.isoformat() if meeting_date else None,
            "days_to_meeting": days_to_meeting,
        })
        return None

    logger.info(f"[FedClient] In signal window: {days_to_meeting} days to {meeting_date} FOMC")

    # Fetch data
    fed_rate        = get_current_fed_rate()
    polymarket_probs = get_polymarket_fomc_probabilities(meeting_date)
    markets          = get_kalshi_fed_markets(meeting_date)

    # slug_unknown: function already saved the no_signal result — just pass it through
    if (
        isinstance(polymarket_probs, dict)
        and polymarket_probs.get("status") == "no_signal"
        and polymarket_probs.get("skip_reason") == "slug_unknown"
    ):
        logger.info(
            f"[FedClient] Polymarket slug unknown for {meeting_date} — "
            f"update config/fomc_slugs.json when slug becomes available"
        )
        return polymarket_probs

    if not polymarket_probs:
        logger.warning("[FedClient] No Polymarket FOMC probability data — cannot compute edge")
        _result = {
            "status":          "no_signal",
            "skip_reason":     "polymarket_unavailable",
            "meeting_date":    meeting_date.isoformat(),
            "days_to_meeting": days_to_meeting,
            "fed_rate":        fed_rate,
        }
        _save_scan_result(_result)
        return _result

    if not markets:
        logger.warning("[FedClient] No Kalshi KXFEDDECISION markets found")
        _result = {
            "status":           "no_signal",
            "skip_reason":      "kalshi_markets_unavailable",
            "meeting_date":     meeting_date.isoformat(),
            "days_to_meeting":  days_to_meeting,
            "fed_rate":         fed_rate,
            "polymarket_probs": polymarket_probs,
            "prob_source":      "polymarket",
        }
        _save_scan_result(_result)
        return _result

    # Find best edge opportunity across all outcomes
    best_signal = None
    best_edge   = 0.0

    for market in markets:
        outcome = _classify_kalshi_outcome(market)
        if outcome is None:
            continue

        polymarket_p = polymarket_probs.get(outcome)
        if polymarket_p is None:
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

        raw_edge = polymarket_p - kalshi_price

        # Confidence: higher when Polymarket probability is extreme (>70% or <30%)
        # and when prices agree directionally
        base_conf = min(abs(polymarket_p - 0.5) * 2, 1.0)  # 0 at 50-50, 1.0 at 0% or 100%
        confidence = round(0.5 + base_conf * 0.5, 3)       # compress to [0.50, 1.00] range

        # Direction: BUY YES if Polymarket prob > Kalshi price, BUY NO otherwise
        direction = "yes" if raw_edge > 0 else "no"
        edge      = abs(raw_edge)

        if edge > best_edge:
            best_edge = edge
            best_signal = {
                "prob":             round(polymarket_p, 4),
                "confidence":       confidence,
                "edge":             round(edge, 4),
                "raw_edge":         round(raw_edge, 4),
                "direction":        direction,
                "outcome":          outcome,
                "ticker":           market.get("ticker", ""),
                "title":            market.get("title", ""),
                "market_price":     round(kalshi_price, 4),
                "yes_ask":          yes_ask,
                "yes_bid":          yes_bid,
                "meeting_date":     meeting_date.isoformat(),
                "days_to_meeting":  days_to_meeting,
                "fed_rate":         fed_rate,
                "polymarket_probs": polymarket_probs,
                "prob_source":      "polymarket",
                "signal_window":    "2-7d",
                "skip_reason":      None,
            }

    if best_signal is None:
        logger.info("[FedClient] No classifiable KXFEDDECISION outcomes found")
        _result = {
            "status":           "no_signal",
            "skip_reason":      "no_classifiable_outcomes",
            "meeting_date":     meeting_date.isoformat(),
            "days_to_meeting":  days_to_meeting,
            "fed_rate":         fed_rate,
            "polymarket_probs": polymarket_probs,
            "prob_source":      "polymarket",
        }
        _save_scan_result(_result)
        return _result

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
        f"Polymarket={best_signal['prob']:.1%} Kalshi={best_signal['market_price']:.1%} "
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

def run_fed_scan() -> dict | None:
    """
    Run a Fed scan cycle. Returns signal dict or None.
    Trade execution is handled by ruppert_cycle.py (strategy gate + logger.log_trade).
    dry_run is intentionally not a parameter here — execution mode is determined
    by the DRY_RUN flag in ruppert_cycle.py (the caller).
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
        print(f"\nFetching Polymarket FOMC probabilities for {mtg}...")
        probs = get_polymarket_fomc_probabilities(mtg)
        if probs:
            for outcome, p in probs.items():
                print(f"  {outcome:12} {p:.1%}")
        else:
            print("  Polymarket data unavailable (no active FOMC markets found)")

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
