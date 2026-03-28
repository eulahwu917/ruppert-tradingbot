"""
synthesizer.py — Data Scientist event synthesizer.

Reads raw event logs and synthesizes truth files:
  - ALERT_CANDIDATE events  → logs/truth/pending_alerts.json
  - SETTLEMENT events       → logs/truth/pnl_cache.json
  - STATE_UPDATE events     → logs/truth/state.json

Called by data_agent.py after each scan cycle.
Also runnable standalone: python -m agents.data_scientist.synthesizer

Data Scientist is the SOLE writer of these truth files.
Safe to run multiple times (idempotent).
"""

import json
import sys
from datetime import date, datetime
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent.parent.parent
LOGS_DIR = PROJECT_ROOT / 'logs'
RAW_DIR = LOGS_DIR / 'raw'
TRUTH_DIR = LOGS_DIR / 'truth'

# Trades may live in logs/ (current) or logs/trades/ (after Phase 3 migration)
_TRADES_DIRS = [
    LOGS_DIR / 'trades',   # Phase 3 target
    LOGS_DIR,              # current location
]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _write_truth(filename: str, data) -> None:
    """Atomic write to a truth file in logs/truth/."""
    TRUTH_DIR.mkdir(parents=True, exist_ok=True)
    path = TRUTH_DIR / filename
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, indent=2), encoding='utf-8')
    tmp.replace(path)


def _read_truth(filename: str, default=None):
    """Read an existing truth file, returning default if missing or corrupt."""
    path = TRUTH_DIR / filename
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return default


def read_today_events(event_date: date = None) -> list:
    """
    Read all events from the specified date's event log (defaults to today).
    Returns empty list if file is missing or empty.
    """
    target_date = event_date or date.today()
    event_log = RAW_DIR / f'events_{target_date.isoformat()}.jsonl'

    if not event_log.exists():
        return []

    events = []
    for line in event_log.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            # Skip malformed lines silently
            pass
    return events


# ── Core synthesizers ──────────────────────────────────────────────────────────

def synthesize_alerts(events: list = None) -> list:
    """
    Process ALERT_CANDIDATE events from today's log.
    Appends genuinely new alerts to logs/truth/pending_alerts.json.
    Returns list of newly added alerts.
    """
    if events is None:
        events = read_today_events()

    alert_events = [e for e in events if e.get('type') == 'ALERT_CANDIDATE']

    # Load existing alerts (for dedup)
    existing = _read_truth('pending_alerts.json', default=[])
    if not isinstance(existing, list):
        existing = []

    # Dedup key: (message, ticker) — same as spec
    existing_keys = {
        (a.get('message', ''), a.get('ticker', ''))
        for a in existing
    }

    new_alerts = []
    for event in alert_events:
        key = (event.get('message', ''), event.get('ticker', ''))
        if key not in existing_keys:
            new_alerts.append({
                'level': event.get('level', 'info'),
                'message': event.get('message', ''),
                'ticker': event.get('ticker'),
                'pnl': event.get('pnl'),
                'timestamp': event.get('ts'),
            })
            existing_keys.add(key)  # prevent duplicates within same run

    if new_alerts:
        _write_truth('pending_alerts.json', existing + new_alerts)

    return new_alerts


def synthesize_pnl_cache(events: list = None) -> dict:
    """
    Recompute pnl_cache.json from trade log files.
    Uses SETTLEMENT events from today's log to incorporate settled trades
    that may not yet be reflected in trade log files.

    Returns the updated pnl_cache dict.
    """
    closed_pnl = 0.0

    # Walk all trade files (supports both current and Phase 3 paths)
    trade_files_seen = set()
    for trades_dir in _TRADES_DIRS:
        if not trades_dir.exists():
            continue
        for path in sorted(trades_dir.glob('trades_*.jsonl')):
            if path in trade_files_seen:
                continue
            trade_files_seen.add(path)
            try:
                for line in path.read_text(encoding='utf-8').splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        trade = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if trade.get('action') in ('exit', 'settle'):
                        pnl = trade.get('pnl') or trade.get('realized_pnl') or 0
                        try:
                            closed_pnl += float(pnl)
                        except (TypeError, ValueError):
                            pass
            except Exception:
                pass

    # Also incorporate SETTLEMENT events from today's event log that
    # may not have been written to trade files yet
    if events is None:
        events = read_today_events()

    settlement_events = [e for e in events if e.get('type') == 'SETTLEMENT']
    for event in settlement_events:
        pnl = event.get('pnl', 0)
        try:
            closed_pnl += float(pnl)
        except (TypeError, ValueError):
            pass

    cache = {'closed_pnl': round(closed_pnl, 2)}
    _write_truth('pnl_cache.json', cache)
    return cache


def synthesize_state(events: list = None) -> dict | None:
    """
    Build state.json from the most recent STATE_UPDATE event today.
    No-ops if no STATE_UPDATE events exist.
    Returns new state dict, or None if no updates.
    """
    if events is None:
        events = read_today_events()

    state_events = [e for e in events if e.get('type') == 'STATE_UPDATE']
    if not state_events:
        return None

    # Use most recent STATE_UPDATE
    latest = state_events[-1]
    state = {
        'traded_tickers': latest.get('traded_tickers', []),
        'last_cycle_ts': latest.get('ts', datetime.now().isoformat()),
        'last_cycle_mode': latest.get('mode'),
    }
    _write_truth('state.json', state)
    return state


# ── Entry point ────────────────────────────────────────────────────────────────

def run_synthesis(event_date: date = None) -> dict:
    """
    Run all synthesis operations for the given date (defaults to today).
    Called by data_agent.py after each scan cycle, or as a standalone cron job.

    Returns a summary dict.
    """
    TRUTH_DIR.mkdir(parents=True, exist_ok=True)

    # Read events once and pass to all synthesizers (efficiency + consistency)
    events = read_today_events(event_date)

    pnl = synthesize_pnl_cache(events)
    new_alerts = synthesize_alerts(events)
    state = synthesize_state(events)

    return {
        'events_read': len(events),
        'pnl_cache': pnl,
        'new_alerts': len(new_alerts),
        'state_updated': state is not None,
    }


if __name__ == '__main__':
    result = run_synthesis()
    print(f'[Synthesizer] Done: {result}')
    sys.exit(0)
