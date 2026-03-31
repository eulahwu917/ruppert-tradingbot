"""Shared utility functions for the Ruppert trader modules."""
import json
from datetime import date
from pathlib import Path

from agents.ruppert.env_config import get_paths as _get_paths
from scripts.event_logger import log_event

TRADES_DIR = _get_paths()['trades']


def load_traded_tickers() -> set:
    """Load set of already-traded tickers for dedup."""
    today = date.today().isoformat()
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
