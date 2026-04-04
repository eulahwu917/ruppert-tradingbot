"""Shared utility functions for the Ruppert trader modules."""
import json
import logging
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo as _ZoneInfo

from agents.ruppert.env_config import get_paths as _get_paths
from scripts.event_logger import log_event

_LA = _ZoneInfo('America/Los_Angeles')

def _today_pdt() -> str:
    """Return today's date string in PDT/PST (America/Los_Angeles). Safe during UTC midnight."""
    return datetime.now(timezone.utc).astimezone(_LA).strftime('%Y-%m-%d')

TRADES_DIR = _get_paths()['trades']

# Canonical definition of Kalshi 15-minute crypto direction series.
# Import from here — do NOT redefine locally in crypto_15m.py or position_monitor.py.
CRYPTO_15M_SERIES = ('KXBTC15M', 'KXETH15M', 'KXXRP15M', 'KXDOGE15M', 'KXSOL15M')


def load_traded_tickers() -> set:
    """Load set of already-traded tickers for dedup."""
    today = _today_pdt()
    trade_log = TRADES_DIR / f"trades_{today}.jsonl"
    tickers = set()

    if trade_log.exists():
        for line in trade_log.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if rec.get('action') not in ('exit', 'settle'):
                    tickers.add(rec.get('ticker', ''))
            except Exception:
                pass
    return tickers


def push_alert(level, message, ticker=None, pnl=None):
    """Log alert candidate event. Data Scientist decides if it's alertworthy."""
    log_event('ALERT_CANDIDATE', {
        'level': level,
        'message': message,
        'ticker': ticker,
        'pnl': pnl,
    })


# ─────────────────────────────── Macro Event Calendar (R9) ───────────────────

def _dt(year, month, day, hour, minute=0):
    """Helper: create a UTC-aware datetime."""
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


# 2026 macro event calendar (UTC times).
# FOMC decisions: 19:00 UTC (14:00 ET)
# FOMC minutes: 19:00 UTC (14:00 ET), approx 3 weeks post-decision
# CPI releases: 13:30 UTC (08:30 ET) — BLS official schedule
# NFP releases: 13:30 UTC (08:30 ET) — BLS official schedule
#
# Sources:
#   FOMC: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
#   CPI:  https://www.bls.gov/schedule/news_release/cpi.htm
#   NFP:  https://www.bls.gov/schedule/news_release/empsit.htm
#
# NOTE: FOMC minutes dates beyond Feb 18 are calculated as T+21d — verify against
# Federal Reserve releases page before going live.
# Calendar maintenance: update with 2027 dates before January 1 2027.

MACRO_CALENDAR = [
    # ── FOMC Decision Dates 2026 ──────────────────────────────────────────────
    _dt(2026,  1, 28, 19),   # Jan 28
    _dt(2026,  3, 18, 19),   # Mar 18
    _dt(2026,  4, 29, 19),   # Apr 29
    _dt(2026,  6, 17, 19),   # Jun 17
    _dt(2026,  7, 29, 19),   # Jul 29
    _dt(2026,  9, 16, 19),   # Sep 16
    _dt(2026, 10, 28, 19),   # Oct 28
    _dt(2026, 12,  9, 19),   # Dec 9

    # ── FOMC Minutes Release Dates 2026 ───────────────────────────────────────
    _dt(2026,  2, 18, 19),   # Feb 18 (verified)
    _dt(2026,  4,  8, 19),   # Apr 8  (~3 weeks after Mar 18 — verify before deploy)
    _dt(2026,  5, 20, 19),   # May 20 (~3 weeks after Apr 29 — verify before deploy)
    _dt(2026,  7,  8, 19),   # Jul 8  (~3 weeks after Jun 17 — verify before deploy)
    _dt(2026,  8, 19, 19),   # Aug 19 (~3 weeks after Jul 29 — verify before deploy)
    _dt(2026, 10,  7, 19),   # Oct 7  (~3 weeks after Sep 16 — verify before deploy)
    _dt(2026, 11, 18, 19),   # Nov 18 (~3 weeks after Oct 28 — verify before deploy)
    _dt(2026, 12, 30, 19),   # Dec 30 (~3 weeks after Dec 9  — verify before deploy)

    # ── CPI Release Dates 2026 (BLS official) ─────────────────────────────────
    _dt(2026,  1, 13, 13, 30),
    _dt(2026,  2, 13, 13, 30),
    _dt(2026,  3, 11, 13, 30),
    _dt(2026,  4, 10, 13, 30),
    _dt(2026,  5, 12, 13, 30),
    _dt(2026,  6, 10, 13, 30),
    _dt(2026,  7, 14, 13, 30),
    _dt(2026,  8, 12, 13, 30),
    _dt(2026,  9, 11, 13, 30),
    _dt(2026, 10, 14, 13, 30),
    _dt(2026, 11, 10, 13, 30),
    _dt(2026, 12, 10, 13, 30),

    # ── NFP Release Dates 2026 (BLS official) ─────────────────────────────────
    _dt(2026,  1,  9, 13, 30),
    _dt(2026,  2, 11, 13, 30),
    _dt(2026,  3,  6, 13, 30),
    _dt(2026,  4,  3, 13, 30),
    _dt(2026,  5,  8, 13, 30),
    _dt(2026,  6,  5, 13, 30),
    _dt(2026,  7,  2, 13, 30),
    _dt(2026,  8,  7, 13, 30),
    _dt(2026,  9,  4, 13, 30),
    _dt(2026, 10,  2, 13, 30),
    _dt(2026, 11,  6, 13, 30),
    _dt(2026, 12,  4, 13, 30),
]

# ── Startup guard: log ERROR if current year has no calendar entries ──────────
_startup_year = datetime.now(timezone.utc).year
_year_event_count = sum(1 for e in MACRO_CALENDAR if e.year == _startup_year)
if _year_event_count == 0:
    logging.getLogger(__name__).error(
        '[R9] STARTUP WARNING: MACRO_CALENDAR contains 0 events for %d. '
        'R9 macro filter will be INACTIVE. Update the calendar in utils.py.',
        _startup_year
    )


def has_macro_event_within(minutes_before: int = 120, minutes_after: int = 60) -> bool:
    """Return True if now is within a macro event blackout window.

    Checks against MACRO_CALENDAR (FOMC decisions, FOMC minutes, CPI, NFP).
    Returns True if current UTC time is within `minutes_before` before OR
    `minutes_after` after any scheduled event.

    Defaults: 120 min before (2h pre-event), 60 min after (1h post-event).

    Called by R9 in crypto_15m.evaluate_crypto_15m_entry().
    """
    _logger = logging.getLogger(__name__)
    now = datetime.now(timezone.utc)

    current_year = now.year
    year_events = [e for e in MACRO_CALENDAR if e.year == current_year]

    # AC-9: Loud warning at call time if calendar is empty for current year
    if not year_events:
        _logger.error(
            '[R9] MACRO_CALENDAR has NO events for year %d — R9 filter is INACTIVE. '
            'Update the calendar in utils.py before running live.',
            current_year
        )
        # Fail safe: return False (no block). Conservative for profitability.
        return False

    for event_time in year_events:
        window_start = event_time - timedelta(minutes=minutes_before)
        window_end = event_time + timedelta(minutes=minutes_after)
        if window_start <= now <= window_end:
            return True
    return False
