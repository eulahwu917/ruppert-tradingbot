"""
terminal_signal_logger.py — Logs the 'terminal signal' for crypto_15m_dir positions
approaching their close window.

Shadow-only: no trading decisions are changed. Captures one record per position per
close window so we can compare terminal signal vs entry signal over time.
"""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Resolve workspace root and add to path for imports
_WORKSPACE_ROOT = Path(__file__).parent.parent.parent  # workspace/
if str(_WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE_ROOT))

from agents.ruppert.env_config import get_paths as _get_paths  # noqa: E402

logger = logging.getLogger(__name__)

_env_paths = _get_paths()
LOGS_DIR = _env_paths['logs']
TERMINAL_LOG_DIR = LOGS_DIR / 'terminal_signals'

# Time gate: only log when position is within this many seconds of close
TERMINAL_WINDOW_SECONDS = 90

# In-memory dedup set: tracks position_keys already logged this session
_logged_keys: set[str] = set()


def _get_seconds_to_close(close_time: str | None) -> float | None:
    """Return seconds until market close, or None if close_time unavailable."""
    if not close_time:
        return None
    try:
        close_dt = datetime.fromisoformat(close_time.replace('Z', '+00:00'))
        now_utc = datetime.now(tz=timezone.utc)
        return (close_dt - now_utc).total_seconds()
    except Exception:
        return None


def maybe_log_terminal(ticker: str, position: dict, current_signal: float,
                       close_time: str | None = None):
    """Log the terminal signal for a crypto_15m_dir position approaching close.

    Args:
        ticker:         Market ticker string
        position:       Position dict from position_tracker._tracked
        current_signal: Current yes_bid value (the live market signal at this tick)
        close_time:     ISO 8601 UTC close time string from WS message
    """
    # 5.1 — Module filter (FIRST LINE)
    if position.get('module') != 'crypto_15m_dir':
        return

    # 5.2 — Time gate
    seconds_left = _get_seconds_to_close(close_time)
    if seconds_left is None or seconds_left > TERMINAL_WINDOW_SECONDS:
        return

    # Don't log if already past close
    if seconds_left < 0:
        return

    # 5.3 — Dedup check: one record per position per close window
    side = position.get('side', 'yes')
    position_key = f"{ticker}::{side}"
    if position_key in _logged_keys:
        return
    _logged_keys.add(position_key)

    # 5.4 — Build and write terminal signal record
    entry_price = position.get('entry_price')
    entry_raw_score = position.get('entry_raw_score')
    quantity = position.get('quantity', 0)

    record = {
        'timestamp': datetime.now(tz=timezone.utc).isoformat(),
        'ticker': ticker,
        'side': side,
        'module': 'crypto_15m_dir',
        'entry_price': entry_price,
        'entry_raw_score': entry_raw_score,
        'terminal_signal': current_signal,
        'seconds_to_close': round(seconds_left, 1),
        'contracts': quantity,
        'title': position.get('title', ''),
        'outcome': None,  # backfilled after settlement
    }

    try:
        TERMINAL_LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = TERMINAL_LOG_DIR / f'terminal_{datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")}.jsonl'
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(record) + '\n')
        logger.info(
            '[TerminalSignal] Logged %s %s | terminal_signal=%s entry_raw_score=%s secs_left=%.0f',
            ticker, side, current_signal, entry_raw_score, seconds_left
        )
    except Exception as e:
        logger.warning('[TerminalSignal] Failed to write record for %s: %s', ticker, e)


def backfill_outcome(ticker: str, side: str, outcome: str):
    """Backfill WIN/LOSS outcome for a terminal signal record after settlement.

    Args:
        ticker:  Market ticker
        side:    Position side ('yes' or 'no')
        outcome: 'WIN' or 'LOSS'
    """
    today_str = datetime.now(tz=timezone.utc).strftime('%Y-%m-%d')
    log_path = TERMINAL_LOG_DIR / f'terminal_{today_str}.jsonl'

    if not log_path.exists():
        return

    try:
        lines = log_path.read_text(encoding='utf-8').strip().split('\n')
        updated = []
        matched = False
        for line in lines:
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get('ticker') == ticker and rec.get('side') == side and rec.get('outcome') is None:
                rec['outcome'] = outcome
                matched = True
            updated.append(json.dumps(rec))

        if matched:
            log_path.write_text('\n'.join(updated) + '\n', encoding='utf-8')
            logger.info('[TerminalSignal] Backfilled outcome=%s for %s %s', outcome, ticker, side)
    except Exception as e:
        logger.warning('[TerminalSignal] Backfill failed for %s %s: %s', ticker, side, e)


def clear_session_dedup():
    """Clear the in-memory dedup set. Call at session/day boundary if needed."""
    _logged_keys.clear()
