"""
intra_window_logger.py — Records yes_bid/yes_ask every 60s for open crypto_dir_15m positions.

Shadow-only: no trading actions. Produces a price path for backtesting.
Log file: logs/price_series/{safe_ticker}.jsonl  (one file per ticker, appended)
"""

import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytz

_WORKSPACE_ROOT = Path(__file__).parent.parent.parent
if str(_WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE_ROOT))

from agents.ruppert.env_config import get_paths as _get_paths

logger = logging.getLogger(__name__)

_env_paths = _get_paths()
PRICE_SERIES_DIR = _env_paths['logs'] / 'price_series'

LOG_INTERVAL_SECS = 60
WINDOW_SECS = 900  # 15 minutes

# In-memory throttle: {position_key: last_log_unix_ts}
_last_log_ts: dict[str, float] = {}


def _parse_ticker_times(ticker: str):
    """Return (window_open_epoch, close_epoch) by parsing ticker.

    Ticker format: KXBTC15M-26APR011215-15
    Date part YYMMMDDhhmm encodes close time in America/New_York.
    Returns (None, None) on parse failure.
    """
    try:
        parts = ticker.split('-')
        if len(parts) < 2:
            return None, None
        date_part = parts[1]
        m = re.match(r'(\d{2})([A-Z]{3})(\d{2})(\d{2})(\d{2})', date_part)
        if not m:
            return None, None
        yr = 2000 + int(m.group(1))
        mon_map = {'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
                   'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12}
        mon = mon_map.get(m.group(2), 1)
        day = int(m.group(3))
        hour = int(m.group(4))
        minute = int(m.group(5))
        est = pytz.timezone('America/New_York')
        close_est = est.localize(datetime(yr, mon, day, hour, minute))
        close_epoch = close_est.timestamp()
        open_epoch = close_epoch - WINDOW_SECS
        return open_epoch, close_epoch
    except Exception:
        return None, None


def maybe_log_price(ticker: str, position: dict, yes_bid: int | None, yes_ask: int | None):
    """Log a price snapshot if >=60s have elapsed since the last log for this position.

    Args:
        ticker:   Market ticker string
        position: Position dict from position_tracker._tracked
        yes_bid:  Current yes_bid in cents (int)
        yes_ask:  Current yes_ask in cents (int, may be None)
    """
    # Module filter (FIRST LINE)
    if position.get('module') != 'crypto_dir_15m':
        return

    if yes_bid is None:
        return

    # Throttle: one log per 60s per position key
    side = position.get('side', 'yes')
    position_key = f'{ticker}::{side}'
    now = time.time()
    last = _last_log_ts.get(position_key, 0.0)
    if now - last < LOG_INTERVAL_SECS:
        return
    _last_log_ts[position_key] = now

    # Compute timing fields
    open_epoch, close_epoch = _parse_ticker_times(ticker)
    if open_epoch is None:
        seconds_elapsed = None
        seconds_to_close = None
        pct_window_elapsed = None
    else:
        seconds_elapsed = round(now - open_epoch)
        seconds_to_close = round(close_epoch - now)
        pct_window_elapsed = round(max(0.0, min(1.0, (now - open_epoch) / WINDOW_SECS)), 4)

    record = {
        'logged_at': datetime.now(tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'ticker': ticker,
        'side': side,
        'yes_bid': round(yes_bid / 100, 2) if yes_bid is not None else None,
        'yes_ask': round(yes_ask / 100, 2) if yes_ask is not None else None,
        'seconds_elapsed': seconds_elapsed,
        'seconds_to_close': seconds_to_close,
        'pct_window_elapsed': pct_window_elapsed,
    }

    try:
        PRICE_SERIES_DIR.mkdir(parents=True, exist_ok=True)
        # One file per ticker (safe: single-process append, no portalocker needed)
        safe_ticker = re.sub(r'[^\w\-]', '_', ticker)
        log_path = PRICE_SERIES_DIR / f'{safe_ticker}.jsonl'
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(record) + '\n')
            f.flush()
            os.fsync(f.fileno())
        logger.debug(
            '[IntraWindow] %s %s | yes_bid=%.2f secs_elapsed=%s secs_to_close=%s',
            ticker, side, record['yes_bid'], seconds_elapsed, seconds_to_close
        )
    except Exception as e:
        logger.warning('[IntraWindow] Failed to write record for %s: %s', ticker, e)


def clear_session_dedup():
    """Clear the in-memory throttle dict. Call at session/day boundary if needed."""
    _last_log_ts.clear()
