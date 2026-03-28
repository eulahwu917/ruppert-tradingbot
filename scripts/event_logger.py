"""
event_logger.py — Unified event logging for all scripts.
Scripts call log_event() instead of writing to truth files.
Data Scientist synthesizes events into truth.
"""
import json
from datetime import datetime, date
from pathlib import Path

LOGS_DIR = Path(__file__).parent.parent / 'logs' / 'raw'
LOGS_DIR.mkdir(parents=True, exist_ok=True)


def log_event(event_type: str, data: dict, source: str = None) -> None:
    """
    Append an event to today's event log.

    Args:
        event_type: Event category (e.g., 'TRADE_EXECUTED', 'EXIT_TRIGGERED', 'ALERT_CANDIDATE')
        data: Event payload (dict)
        source: Script name that generated the event (auto-detected if None)

    Event types:
        TRADE_EXECUTED        - Trade placed (ticker, side, size, contracts)
        EXIT_TRIGGERED        - Exit executed (ticker, side, pnl, rule)
        SETTLEMENT            - Market settled (ticker, result, pnl)
        CIRCUIT_BREAKER       - Circuit breaker tripped (reason, loss_today)
        SCAN_COMPLETE         - Scan cycle finished (mode, counts)
        ANOMALY_DETECTED      - Data issue found (check, detail)
        ALERT_CANDIDATE       - Potential alert (level, message)
        POSITION_UPDATE       - Position state changed (ticker, side, action)
        PRICE_UPDATE          - Significant price move (ticker, old, new)
        STATE_UPDATE          - Cycle state snapshot (traded_tickers, mode)
        TRADE_FAILED          - Trade execution failed (ticker, side, error)
    """
    event = {
        'ts': datetime.now().isoformat(),
        'type': event_type,
        'source': source or _get_caller(),
        **data,
    }

    log_path = LOGS_DIR / f'events_{date.today().isoformat()}.jsonl'
    with open(log_path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(event) + '\n')


def _get_caller() -> str:
    """Auto-detect calling script name."""
    import inspect
    for frame in inspect.stack():
        filename = frame.filename
        if 'event_logger' not in filename and filename.endswith('.py'):
            return Path(filename).stem
    return 'unknown'
