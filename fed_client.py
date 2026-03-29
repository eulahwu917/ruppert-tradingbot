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
# Source: CME FedWatch /meetings/future API (authoritative) — last synced 2026-03-26.
# Past meetings kept for historical reference; future dates verified against CME.
FOMC_DECISION_DATES_2026 = [
    date(2026, 1, 29),   # past
    date(2026, 3, 18),   # past
    date(2026, 4, 29),   # CME confirmed
    date(2026, 6, 17),   # CME confirmed
    date(2026, 7, 29),   # CME confirmed
    date(2026, 9, 16),   # CME confirmed
    date(2026, 10, 28),  # CME confirmed
    date(2026, 12,  9),  # CME confirmed
]

_FOMC_CACHE_FILE = Path(__file__).parent / "logs" / "fomc_meetings_cache.json"


def refresh_fomc_calendar_from_cme() -> list[date] | None:
    """
    Fetch future FOMC meeting dates from CME /meetings/future endpoint and
    cache them to logs/fomc_meetings_cache.json.

    Returns list of future meeting dates (sorted), or None on failure.
    Call this periodically (e.g. monthly) to keep the calendar current.
    """
    token = _get_cme_oauth_token()
    if not token:
        return None
    import uuid
    try:
        r = requests.get(
            f"{_CME_API_BASE}/meetings/future",
            headers={
                "Authorization":           f"Bearer {token}",
                "CME-Application-Name":    _CME_APP_NAME,
                "CME-Application-Vendor":  _CME_APP_VENDOR,
                "CME-Application-Version": _CME_APP_VERSION,
                "CME-Request-ID":          str(uuid.uuid4()),
                "User-Agent":              f"{_CME_APP_NAME}/{_CME_APP_VERSION}",
            },
            timeout=15,
        )
        r.raise_for_status()
        payload = r.json().get("payload", [])
        dates = sorted([
            date.fromisoformat(entry["meetingDt"][:10])
            for entry in payload
            if entry.get("meetingDt")
        ])
        if dates:
            _FOMC_CACHE_FILE.parent.mkdir(exist_ok=True)
            _FOMC_CACHE_FILE.write_text(
                json.dumps({
                    "fetched_at":    datetime.now(timezone.utc).isoformat(),
                    "meeting_dates": [d.isoformat() for d in dates],
                }),
                encoding="utf-8",
            )
            logger.info(f"[FedClient] CME FOMC calendar refreshed: {[str(d) for d in dates]}")
        return dates
    except Exception as e:
        logger.warning(f"[FedClient] CME meeting fetch failed: {e}")
        return None


def get_fomc_dates() -> list[date]:
    """
    Return upcoming FOMC decision dates. Uses CME cache if fresh (<7 days),
    falls back to hardcoded FOMC_DECISION_DATES_2026.
    """
    try:
        if _FOMC_CACHE_FILE.exists():
            cached = json.loads(_FOMC_CACHE_FILE.read_text(encoding="utf-8"))
            fetched_at = datetime.fromisoformat(cached["fetched_at"])
            age_days   = (datetime.now(timezone.utc) - fetched_at).days
            if age_days < 7:
                dates = [date.fromisoformat(d) for d in cached.get("meeting_dates", [])]
                if dates:
                    return dates
    except Exception:
        pass
    return FOMC_DECISION_DATES_2026

# ── Strategy Parameters ───────────────────────────────────────────────────────
FED_MIN_EDGE        = 0.12   # 12% minimum edge to consider entry
FED_MIN_CONFIDENCE  = 0.25   # 25% minimum confidence — matches universal minimum
FED_WINDOW_MIN_DAYS = 2      # skip if < 2 days (market efficient)
FED_WINDOW_MAX_DAYS = 7      # skip if > 7 days (too early)
FED_MIN_KALSHI_PRICE = 0.15  # never trade contracts below 15¢ (favorite-longshot bias)

# ── File Paths ────────────────────────────────────────────────────────────────
_LOGS_DIR   = Path(__file__).parent / "logs"
_SCAN_FILE  = _LOGS_DIR / "fed_scan_latest.json"

# Kalshi market access via KalshiClient (handles retries, orderbook enrichment, DEMO/LIVE)
from kalshi_client import KalshiClient as _KalshiClient


# ── FOMC Date Utilities ───────────────────────────────────────────────────────

def next_fomc_meeting() -> tuple[date | None, int]:
    """
    Return (next_decision_date, days_until_decision).
    Uses CME-cached dates if fresh, falls back to hardcoded calendar.
    Returns (None, -1) if no upcoming meeting found.
    """
    today = date.today()
    for decision_date in sorted(get_fomc_dates()):
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
    Fetch current Fed target rate upper bound from FRED DFEDTARU CSV.
    URL: https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFEDTARU
    DFEDTARU (daily target upper bound) is more current than FEDFUNDS (monthly, lagged).
    Returns most recent rate value, or None on failure.
    """
    try:
        url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFEDTARU"
        r   = requests.get(url, timeout=15)
        r.raise_for_status()
        lines = r.text.strip().splitlines()
        # Format: DATE,DFEDTARU\n2026-03-12,4.50\n...
        for line in reversed(lines[1:]):  # skip header, iterate recent-first
            parts = line.strip().split(",")
            if len(parts) == 2 and parts[1] not in (".", ""):
                rate = float(parts[1])
                logger.info(f"[FedClient] FRED DFEDTARU: {parts[0]} = {rate}%")
                return rate
        return None
    except Exception as e:
        logger.error(f"[FedClient] FRED fetch failed: {e}")
        return None


# ── CME FedWatch Data ────────────────────────────────────────────────────────

# CME OAuth + API constants
_CME_AUTH_URL    = "https://auth.cmegroup.com/as/token.oauth2"
_CME_API_BASE    = "https://markets.api.cmegroup.com/fedwatch/v1"
_CME_APP_NAME    = "ruppert-agent"
_CME_APP_VENDOR  = "ruppert"
_CME_APP_VERSION = "1.0.0"
_SECRETS_DIR     = Path(__file__).parent.parent / "secrets"
_CME_CONFIG_FILE = _SECRETS_DIR / "cme_config.json"
_CME_TOKEN_CACHE = _SECRETS_DIR / "cme_token_cache.json"


def _load_cme_config() -> dict | None:
    """Load CME credentials from secrets/cme_config.json."""
    try:
        return json.loads(_CME_CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error(f"[FedClient] Could not load cme_config.json: {e}")
        return None


def _get_cme_oauth_token() -> str | None:
    """
    Obtain a valid CME OAuth 2.0 bearer token.

    Checks token cache first (secrets/cme_token_cache.json).
    If expired or missing, fetches a fresh token from CME OAuth endpoint.
    Token TTL is ~1800 seconds; we refresh at 1700s to be safe.

    Returns:
        Bearer token string, or None on failure.
    """
    import base64
    now = datetime.now(timezone.utc).timestamp()

    # ── Check cache ──────────────────────────────────────────────────────────
    try:
        if _CME_TOKEN_CACHE.exists():
            cached = json.loads(_CME_TOKEN_CACHE.read_text(encoding="utf-8"))
            if cached.get("expires_at", 0) > now + 60:  # 60s buffer
                logger.debug("[FedClient] Using cached CME OAuth token")
                return cached["access_token"]
    except Exception:
        pass  # Cache read failure → just fetch fresh

    # ── Fetch fresh token ────────────────────────────────────────────────────
    cfg = _load_cme_config()
    if not cfg:
        return None

    api_id  = cfg.get("api_id", "")
    api_pwd = cfg.get("api_password", "")
    if not api_id or not api_pwd:
        logger.error("[FedClient] CME config missing api_id or api_password")
        return None

    credentials = base64.b64encode(f"{api_id}:{api_pwd}".encode()).decode()
    try:
        r = requests.post(
            _CME_AUTH_URL,
            headers={
                "Content-Type":  "application/x-www-form-urlencoded",
                "Authorization": f"Basic {credentials}",
            },
            data="grant_type=client_credentials",
            timeout=15,
        )
        r.raise_for_status()
        token_data   = r.json()
        access_token = token_data.get("access_token")
        expires_in   = int(token_data.get("expires_in", 1800))

        if not access_token:
            logger.error(f"[FedClient] CME OAuth response missing access_token: {token_data}")
            return None

        # Cache token
        try:
            _SECRETS_DIR.mkdir(exist_ok=True)
            _CME_TOKEN_CACHE.write_text(
                json.dumps({
                    "access_token": access_token,
                    "expires_at":   now + expires_in - 100,  # small buffer
                    "fetched_at":   datetime.now(timezone.utc).isoformat(),
                }),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"[FedClient] Could not cache CME token: {e}")

        logger.info(f"[FedClient] CME OAuth token obtained (expires_in={expires_in}s)")
        return access_token

    except Exception as e:
        logger.error(f"[FedClient] CME OAuth token fetch failed: {e}")
        return None


def _map_rate_range_to_outcome(lower_rt: int, upper_rt: int, current_upper_bps: int) -> str | None:
    """
    Map a CME rate range (in basis points) to a standard outcome name.

    Uses current FRED DFEDTARU upper bound as the anchor.
    Rate ranges are target rate ranges: e.g. 425-450 = 4.25%-4.50%.

    Args:
        lower_rt:           Lower rate in basis points (e.g. 425).
        upper_rt:           Upper rate in basis points (e.g. 450).
        current_upper_bps:  Current DFEDTARU upper bound in bps (e.g. 450 for 4.50%).

    Returns:
        'maintain' | 'cut_25' | 'cut_50' | 'hike' | None
    """
    delta = upper_rt - current_upper_bps  # negative = cut, positive = hike, zero = hold
    if delta == 0:
        return "maintain"
    elif delta == -25:
        return "cut_25"
    elif delta <= -50:
        return "cut_50"
    elif delta > 0:
        return "hike"
    return None  # e.g. -12.5bps — unusual, skip


def get_cme_fedwatch_probabilities(meeting_date: date) -> dict | None:
    """
    Fetch FOMC rate decision probabilities from CME FedWatch End-of-Day API.

    Auth: OAuth 2.0 client_credentials (POST to auth.cmegroup.com).
    Endpoint: GET https://markets.api.cmegroup.com/fedwatch/v1/forecasts
    Query: meetingDt=YYYY-MM-DD (fetches latest forecast for that meeting).

    Response rateRange[] entries have lowerRt/upperRt in basis points and
    probability [0-1]. Maps to standard outcomes using current FRED rate as anchor.

    Args:
        meeting_date: The FOMC decision date to look up.

    Returns:
        {'maintain': float, 'cut_25': float, ...} — probabilities sum to ~1.0
        None on auth/API failure.
    """
    token = _get_cme_oauth_token()
    if not token:
        logger.warning("[FedClient] CME OAuth token unavailable — skipping CME data")
        return None

    # Current Fed rate needed to map bps ranges to outcomes
    fed_rate = get_current_fed_rate()
    if fed_rate is None:
        logger.warning("[FedClient] FRED rate unavailable — cannot map CME rate ranges")
        return None

    current_upper_bps = round(fed_rate * 100)  # e.g. 4.50 → 450

    import uuid
    try:
        r = requests.get(
            f"{_CME_API_BASE}/forecasts",
            params={"meetingDt": meeting_date.isoformat()},
            headers={
                "Authorization":          f"Bearer {token}",
                "CME-Application-Name":   _CME_APP_NAME,
                "CME-Application-Vendor": _CME_APP_VENDOR,
                "CME-Application-Version": _CME_APP_VERSION,
                "CME-Request-ID":         str(uuid.uuid4()),
                "User-Agent":             f"{_CME_APP_NAME}/{_CME_APP_VERSION}",
            },
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()

        # Response structure: {"payload": [...], "metadata": {...}}
        # Each payload entry: {"meetingDt": "...", "reportingDt": "...", "rateRange": [...]}
        entries = data.get("payload", [])
        if not entries:
            logger.warning(f"[FedClient] CME FedWatch: empty payload for {meeting_date}")
            return None

        # Find the entry for our target meeting date
        target_key = meeting_date.isoformat()
        forecast   = None
        for entry in entries:
            if str(entry.get("meetingDt", "")).startswith(target_key):
                forecast = entry
                break
        if forecast is None:
            forecast = entries[0]  # fallback: take first (upcoming) result
            logger.info(
                f"[FedClient] CME: exact date {meeting_date} not found — "
                f"using {forecast.get('meetingDt')} instead"
            )

        rate_ranges = forecast.get("rateRange", [])
        if not rate_ranges:
            logger.warning(f"[FedClient] CME FedWatch: empty rateRange for {meeting_date}")
            return None

        probs: dict[str, float] = {}
        for rr in rate_ranges:
            lower_rt = rr.get("lowerRt")
            upper_rt = rr.get("upperRt")
            prob     = rr.get("probability")
            # Skip null probabilities (CME uses null for out-of-range buckets)
            # Skip zero probabilities (no meaningful signal)
            if lower_rt is None or upper_rt is None or prob is None or prob == 0.0:
                continue
            outcome = _map_rate_range_to_outcome(int(lower_rt), int(upper_rt), current_upper_bps)
            if outcome is None:
                logger.debug(
                    f"[FedClient] CME: unmapped range {lower_rt}-{upper_rt}bps "
                    f"(current={current_upper_bps}bps)"
                )
                continue
            # Accumulate (e.g. multiple cut ranges → cut_50 bucket)
            probs[outcome] = round(probs.get(outcome, 0.0) + float(prob), 4)

        if not probs:
            logger.warning(
                f"[FedClient] CME FedWatch: no outcomes could be mapped for {meeting_date} "
                f"(current_upper={current_upper_bps}bps, ranges={rate_ranges})"
            )
            return None

        logger.info(
            f"[FedClient] CME FedWatch probs for {meeting_date} "
            f"(anchor={current_upper_bps}bps): "
            + " ".join(f"{k}={v:.1%}" for k, v in probs.items())
        )
        return probs

    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else "?"
        logger.error(f"[FedClient] CME FedWatch HTTP {status}: {e}")
        if status == 401:
            # Invalidate cached token on auth failure
            try:
                _CME_TOKEN_CACHE.unlink(missing_ok=True)
            except Exception:
                pass
        return None
    except Exception as e:
        logger.error(f"[FedClient] CME FedWatch fetch failed: {e}")
        return None


def _fred_sanity_check(fed_rate: float, outcome: str, ensemble_p: float) -> bool:
    """
    Direction sanity gate using FRED DFEDTARU rate.

    Not a probability source — confirms which direction is physically meaningful.
    Per Optimizer spec Section 3a:
      - fed_rate <= 0.25% → rate at floor → cut prob > 30% is suspicious
      - fed_rate >= 5.5%  → rate at ceiling → hike prob > 30% is suspicious
      - Otherwise: no constraint

    Args:
        fed_rate:   Current Fed target rate upper bound from FRED DFEDTARU.
        outcome:    The signal outcome ('maintain', 'cut_25', 'cut_50', 'hike').
        ensemble_p: Ensemble probability for this outcome (0-1).

    Returns:
        True if direction is physically plausible, False if suspicious.
    """
    if fed_rate <= 0.25:
        # Rate at floor — high cut probability is suspicious
        cut_outcomes = {"cut_25", "cut_50"}
        if outcome in cut_outcomes and ensemble_p > 0.30:
            logger.warning(
                f"[FedClient] FRED sanity check: fed_rate={fed_rate}% (floor) "
                f"but {outcome} ensemble_p={ensemble_p:.1%} > 30% — flagging"
            )
            return False
    if fed_rate >= 5.5:
        # Rate at recent ceiling — high hike probability is suspicious
        if outcome == "hike" and ensemble_p > 0.30:
            logger.warning(
                f"[FedClient] FRED sanity check: fed_rate={fed_rate}% (ceiling) "
                f"but hike ensemble_p={ensemble_p:.1%} > 30% — flagging"
            )
            return False
    return True


def compute_ensemble_confidence(
    cme_p: float | None,
    poly_p: float | None,
    ensemble_p: float,
    fred_sanity_ok: bool = True,
) -> float:
    """
    Compute ensemble confidence score from probability extremity and source agreement.

    Implements Optimizer spec Section 4 exactly:
      Step 1: Base confidence from probability extremity (0.50–1.00)
      Step 2: Source agreement factor (divergence between CME and Polymarket)
      Step 3: FRED sanity gate
      Step 4: Final confidence (capped at 0.99)

    Also applies the -15% confidence multiplier when Polymarket-only (CME down).

    Args:
        cme_p:          CME FedWatch probability (None if unavailable).
        poly_p:         Polymarket probability (None if unavailable).
        ensemble_p:     Weighted ensemble probability.
        fred_sanity_ok: False if FRED sanity check flagged direction as suspicious.

    Returns:
        Confidence score in [0.50, 0.99].
    """
    # Step 1: Base confidence from probability extremity
    # 0.5 when prob = 50%, 1.0 when prob = 0% or 100%
    extremity = min(abs(ensemble_p - 0.5) * 2, 1.0)
    base_conf = 0.5 + extremity * 0.5  # range [0.50, 1.00]

    # Step 2: Source agreement factor
    if cme_p is not None and poly_p is not None:
        divergence = abs(cme_p - poly_p)
        if divergence <= 0.05:
            agreement_factor = 1.05   # < 5pp apart → strong agreement bonus
        elif divergence <= 0.10:
            agreement_factor = 1.00   # 5–10pp → neutral
        elif divergence <= 0.20:
            agreement_factor = 0.90   # 10–20pp → mild concern
        else:
            agreement_factor = 0.80   # > 20pp → significant divergence penalty
    else:
        # Single source only
        if cme_p is None and poly_p is not None:
            # Polymarket-only: -15% confidence multiplier per Optimizer spec Section 2
            agreement_factor = 0.85
        else:
            # CME-only: no penalty (CME is more authoritative)
            agreement_factor = 1.00

    # Step 3: FRED sanity gate
    fred_factor = 0.90 if not fred_sanity_ok else 1.00

    # Step 4: Final confidence (cap at 0.99)
    confidence = min(base_conf * agreement_factor * fred_factor, 0.99)
    return round(confidence, 3)


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

            # outcomePrices may be a JSON-encoded string OR already a list
            # Handle both: '["0.95", "0.05"]' and ["0.95", "0.05"]
            if isinstance(outcome_prices, str):
                try:
                    outcome_prices = json.loads(outcome_prices)
                except Exception:
                    logger.debug(f"[FedClient] outcomePrices JSON parse failed for '{question}'")
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
        _client = _KalshiClient()
        markets = _client.get_markets("KXFEDDECISION", status="open", limit=50)

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
          'prob':             float,  # ensemble YES probability for best outcome
          'confidence':       float,  # computed ensemble confidence score
          'edge':             float,  # abs(ensemble_prob - kalshi_price)
          'direction':        str,    # 'yes' or 'no'
          'outcome':          str,    # 'maintain'|'cut_25'|'cut_50'|'hike'
          'ticker':           str,    # Kalshi market ticker
          'market_price':     float,  # Kalshi YES price (0-1)
          'meeting_date':     str,    # ISO date
          'days_to_meeting':  int,
          'fed_rate':         float,  # current DFEDTARU rate
          'polymarket_probs': dict,   # all outcome probabilities from Polymarket
          'cme_probs':        dict,   # all outcome probabilities from CME (or None)
          'poly_probs':       dict,   # all outcome probabilities from Polymarket (or None)
          'ensemble_probs':   dict,   # weighted ensemble probabilities per outcome
          'source_divergence':float,  # abs(cme_p - poly_p) for best outcome (or None)
          'prob_source':      str,    # 'cme+polymarket'|'cme'|'polymarket'
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

    # ── Fetch all data sources ────────────────────────────────────────────────
    fed_rate     = get_current_fed_rate()
    cme_probs    = get_cme_fedwatch_probabilities(meeting_date)
    poly_result  = get_polymarket_fomc_probabilities(meeting_date)
    markets      = get_kalshi_fed_markets(meeting_date)

    # slug_unknown: Polymarket function already saved the no_signal result
    if (
        isinstance(poly_result, dict)
        and poly_result.get("status") == "no_signal"
        and poly_result.get("skip_reason") == "slug_unknown"
    ):
        logger.info(
            f"[FedClient] Polymarket slug unknown for {meeting_date} — "
            f"update config/fomc_slugs.json when slug becomes available"
        )
        # Pass through only if CME also unavailable
        if cme_probs is None:
            return poly_result
        # CME available — poly_result is a sentinel, treat poly_probs as None
        poly_probs = None
    else:
        poly_probs = poly_result if isinstance(poly_result, dict) else None

    # ── Fallback logic per Optimizer spec Section 2 ───────────────────────────
    cme_available  = cme_probs is not None
    poly_available = poly_probs is not None

    if not cme_available and not poly_available:
        logger.warning("[FedClient] Both CME and Polymarket unavailable — no signal")
        _result = {
            "status":          "no_signal",
            "skip_reason":     "all_prob_sources_unavailable",
            "meeting_date":    meeting_date.isoformat(),
            "days_to_meeting": days_to_meeting,
            "fed_rate":        fed_rate,
            "cme_probs":       None,
            "poly_probs":      None,
            "ensemble_probs":  None,
            "prob_source":     None,
        }
        _save_scan_result(_result)
        return _result

    if cme_available and poly_available:
        prob_source = "cme+polymarket"
        logger.info("[FedClient] Using CME (65%) + Polymarket (35%) ensemble")
    elif cme_available:
        prob_source = "cme"
        logger.info("[FedClient] CME-only (Polymarket unavailable) — no confidence penalty")
    else:
        prob_source = "polymarket"
        logger.info("[FedClient] Polymarket-only (CME unavailable) — -15% confidence penalty")

    if not markets:
        logger.warning("[FedClient] No Kalshi KXFEDDECISION markets found")
        _result = {
            "status":           "no_signal",
            "skip_reason":      "kalshi_markets_unavailable",
            "meeting_date":     meeting_date.isoformat(),
            "days_to_meeting":  days_to_meeting,
            "fed_rate":         fed_rate,
            "cme_probs":        cme_probs,
            "poly_probs":       poly_probs,
            "ensemble_probs":   None,
            "prob_source":      prob_source,
        }
        _save_scan_result(_result)
        return _result

    # ── Build ensemble probabilities for all known outcomes ───────────────────
    all_outcomes = set()
    if cme_probs:
        all_outcomes.update(cme_probs.keys())
    if poly_probs:
        all_outcomes.update(poly_probs.keys())

    ensemble_probs: dict[str, float] = {}
    for outcome in all_outcomes:
        cp = cme_probs.get(outcome) if cme_probs else None
        pp = poly_probs.get(outcome) if poly_probs else None
        if cp is not None and pp is not None:
            ep = round(0.65 * cp + 0.35 * pp, 4)
        elif cp is not None:
            ep = round(cp, 4)
        else:
            ep = round(pp, 4)  # type: ignore[arg-type]
        ensemble_probs[outcome] = ep

    # ── Find best edge opportunity across all outcomes ────────────────────────
    best_signal = None
    best_edge   = 0.0

    for market in markets:
        outcome = _classify_kalshi_outcome(market)
        if outcome is None:
            continue

        ensemble_p = ensemble_probs.get(outcome)
        if ensemble_p is None:
            continue

        yes_ask = market.get("yes_ask")
        yes_bid = market.get("yes_bid", 0)

        # WS cache overlay: use fresher WS price if available
        try:
            import market_cache
            _ticker = market.get('ticker', '')
            _cb, _ca, _stale = market_cache.get_with_staleness(_ticker)
            if not _stale and _ca is not None:
                yes_ask = round(_ca * 100)
                if _cb is not None:
                    yes_bid = round(_cb * 100)
        except ImportError:
            pass

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

        raw_edge = ensemble_p - kalshi_price
        edge     = abs(raw_edge)
        direction = "yes" if raw_edge > 0 else "no"

        # Per-outcome source values for divergence tracking
        cme_p  = cme_probs.get(outcome)  if cme_probs  else None
        poly_p = poly_probs.get(outcome) if poly_probs else None

        # Source divergence for this outcome
        source_divergence = round(abs(cme_p - poly_p), 4) if (cme_p is not None and poly_p is not None) else None

        # FRED sanity check
        fred_sanity_ok = True
        if fed_rate is not None:
            fred_sanity_ok = _fred_sanity_check(fed_rate, outcome, ensemble_p)

        # Compute ensemble confidence
        confidence = compute_ensemble_confidence(
            cme_p=cme_p,
            poly_p=poly_p,
            ensemble_p=ensemble_p,
            fred_sanity_ok=fred_sanity_ok,
        )

        if edge > best_edge:
            best_edge = edge
            best_signal = {
                "prob":              round(ensemble_p, 4),
                "confidence":        confidence,
                "edge":              round(edge, 4),
                "raw_edge":          round(raw_edge, 4),
                "direction":         direction,
                "outcome":           outcome,
                "ticker":            market.get("ticker", ""),
                "title":             market.get("title", ""),
                "market_price":      round(kalshi_price, 4),
                "yes_ask":           yes_ask,
                "yes_bid":           yes_bid,
                "meeting_date":      meeting_date.isoformat(),
                "days_to_meeting":   days_to_meeting,
                "fed_rate":          fed_rate,
                # Ensemble fields
                "cme_probs":         cme_probs,
                "poly_probs":        poly_probs,
                "ensemble_probs":    ensemble_probs,
                "source_divergence": source_divergence,
                "prob_source":       prob_source,
                # Legacy compat
                "polymarket_probs":  poly_probs,
                "signal_window":     "2-7d",
                "skip_reason":       None,
            }

    if best_signal is None:
        logger.info("[FedClient] No classifiable KXFEDDECISION outcomes found")
        _result = {
            "status":           "no_signal",
            "skip_reason":      "no_classifiable_outcomes",
            "meeting_date":     meeting_date.isoformat(),
            "days_to_meeting":  days_to_meeting,
            "fed_rate":         fed_rate,
            "cme_probs":        cme_probs,
            "poly_probs":       poly_probs,
            "ensemble_probs":   ensemble_probs,
            "prob_source":      prob_source,
            # Legacy compat
            "polymarket_probs": poly_probs,
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
        f"ensemble={best_signal['prob']:.1%} Kalshi={best_signal['market_price']:.1%} "
        f"source={prob_source} ({days_to_meeting}d to meeting)"
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
    print(f"DFEDTARU rate: {rate}%")

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
