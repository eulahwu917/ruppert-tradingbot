"""
terminal_signal_logger.py — Logs the 'terminal signal' for crypto_dir_15m positions
approaching their close window.

Shadow-only: no trading decisions are changed. Captures one record per position per
close window so we can compare terminal signal vs entry signal over time.
"""

import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import portalocker
import pytz

# Resolve workspace root and add to path for imports
_WORKSPACE_ROOT = Path(__file__).parent.parent.parent  # workspace/
if str(_WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE_ROOT))

from agents.ruppert.env_config import get_paths as _get_paths  # noqa: E402

logger = logging.getLogger(__name__)

_env_paths = _get_paths()
LOGS_DIR = _env_paths['logs']
TERMINAL_LOG_DIR = LOGS_DIR / 'terminal_signals'
LOCK_FILE = os.path.join(TERMINAL_LOG_DIR, 'terminal_signals.lock')

# Time gate: only log when position is within this many seconds of close
TERMINAL_WINDOW_SECONDS = 90

# In-memory dedup set: tracks position_keys already logged this session
_logged_keys: set[str] = set()


def _get_seconds_to_close(ticker: str) -> float | None:
    """Return seconds until market close by parsing the ticker string.

    Ticker format: KXBTC15M-26MAR281315-15
    Date part: YYMMMDDhhmm — encodes close time in America/New_York.
    Uses pytz for DST-correct conversion.
    """
    if not ticker:
        return None
    try:
        parts = ticker.split('-')
        if len(parts) < 2:
            return None
        date_part = parts[1]
        m = re.match(r'(\d{2})([A-Z]{3})(\d{2})(\d{2})(\d{2})', date_part)
        if not m:
            return None
        yr = 2000 + int(m.group(1))
        mon_str = m.group(2)
        day = int(m.group(3))
        hour = int(m.group(4))
        minute = int(m.group(5))
        mon_map = {'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
                   'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12}
        mon = mon_map.get(mon_str, 1)
        est = pytz.timezone('America/New_York')
        close_est = est.localize(datetime(yr, mon, day, hour, minute))
        close_dt = close_est.astimezone(timezone.utc)
        now_utc = datetime.now(tz=timezone.utc)
        return (close_dt - now_utc).total_seconds()
    except Exception:
        return None


def maybe_log_terminal(ticker: str, position: dict, current_signal: float,
                       close_time: str | None = None):
    """Log the terminal signal for a crypto_dir_15m position approaching close.

    Args:
        ticker:         Market ticker string
        position:       Position dict from position_tracker._tracked
        current_signal: Current yes_bid value (the live market signal at this tick)
        close_time:     Unused (kept for call-site compat); close time is parsed from ticker
    """
    # 5.1 — Module filter (FIRST LINE)
    if position.get('module') != 'crypto_dir_15m':
        return

    # 5.2 — Time gate (parse close time from ticker using pytz)
    seconds_left = _get_seconds_to_close(ticker)
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

    # 5.4 — Derive terminal_direction, entry_direction, signal_flipped
    # Import config for threshold
    try:
        import config
        threshold = getattr(config, 'CRYPTO_SIGNAL_THRESHOLD', 0.55)
        if isinstance(getattr(config, 'MIN_CONFIDENCE', None), dict):
            threshold = config.MIN_CONFIDENCE.get('crypto_dir_15m', threshold)
    except ImportError:
        threshold = 0.55

    terminal_direction = 'yes' if current_signal > threshold else 'no'
    entry_direction = position.get('entry_direction', position.get('side', '')).lower()
    signal_flipped = (terminal_direction != entry_direction)

    # 5.5 — Build and write terminal signal record
    entry_price = position.get('entry_price')
    entry_raw_score = position.get('entry_raw_score')
    quantity = position.get('quantity', 0)

    record = {
        'timestamp': datetime.now(tz=timezone.utc).isoformat(),
        'ticker': ticker,
        'side': side,
        'module': 'crypto_dir_15m',
        'entry_price': entry_price,
        'entry_raw_score': entry_raw_score,
        'terminal_signal': current_signal,
        'entry_direction': entry_direction,
        'terminal_direction': terminal_direction,
        'signal_flipped': signal_flipped,
        'seconds_to_close': round(seconds_left, 1),
        'contracts': quantity,
        'title': position.get('title', ''),
        'outcome': None,  # backfilled after settlement
    }

    try:
        TERMINAL_LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = TERMINAL_LOG_DIR / f'terminal_{datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")}.jsonl'
        with portalocker.Lock(LOCK_FILE, timeout=5):
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(record) + '\n')
                f.flush()
                os.fsync(f.fileno())
        logger.info(
            '[TerminalSignal] Logged %s %s | terminal_signal=%s terminal_dir=%s entry_dir=%s flipped=%s secs_left=%.0f',
            ticker, side, current_signal, terminal_direction, entry_direction, signal_flipped, seconds_left
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
        with portalocker.Lock(LOCK_FILE, timeout=30):
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
                tmp_path = log_path.with_suffix('.tmp')
                tmp_path.write_text('\n'.join(updated) + '\n', encoding='utf-8')
                os.replace(str(tmp_path), str(log_path))
                logger.info('[TerminalSignal] Backfilled outcome=%s for %s %s', outcome, ticker, side)
    except Exception as e:
        logger.warning('[TerminalSignal] Backfill failed for %s %s: %s', ticker, side, e)


def clear_session_dedup():
    """Clear the in-memory dedup set. Call at session/day boundary if needed."""
    _logged_keys.clear()
