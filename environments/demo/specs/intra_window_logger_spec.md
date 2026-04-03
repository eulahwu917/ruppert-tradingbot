# Spec: Intra-Window Price Logger
**For:** Dev  
**From:** DS  
**Date:** 2026-03-31  

---

## 1. Overview

`intra_window_logger.py` records a price snapshot every 60 seconds for every open `crypto_15m_dir` position throughout its full 15-minute window. It hooks into `check_exits()` in `position_tracker.py` — identical pattern to `terminal_signal_logger`. Shadow-only: no trading decisions, no order submission. Output is a per-ticker JSONL file in `logs/price_series/`, giving us a complete price path for backtesting entry/exit signal quality.

---

## 2. Integration Point — `position_tracker.py`

Inside `check_exits()`, immediately after the existing terminal signal logger block, add:

```python
# Intra-window price logger — shadow log for crypto_15m_dir positions
try:
    from intra_window_logger import maybe_log_price
    maybe_log_price(ticker, pos, yes_bid, yes_ask)
except Exception as _iwl_err:
    logger.debug('[PositionTracker] intra_window_logger: %s', _iwl_err)
```

`yes_ask` is already available in `check_exits()` as a parameter — no new data needed.

---

## 3. New File — `environments/demo/intra_window_logger.py`

```python
"""
intra_window_logger.py — Records yes_bid/yes_ask every 60s for open crypto_15m_dir positions.

Shadow-only: no trading actions. Produces a price path for backtesting.
Log file: logs/price_series/KXBTC15M-YYMMMDDHHММ.jsonl  (one file per ticker, appended)
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
        close_est = est.localize(__import__('datetime').datetime(yr, mon, day, hour, minute))
        close_epoch = close_est.timestamp()
        open_epoch = close_epoch - WINDOW_SECS
        return open_epoch, close_epoch
    except Exception:
        return None, None


def maybe_log_price(ticker: str, position: dict, yes_bid: int | None, yes_ask: int | None):
    """Log a price snapshot if ≥60s have elapsed since the last log for this position.

    Args:
        ticker:   Market ticker string
        position: Position dict from position_tracker._tracked
        yes_bid:  Current yes_bid in cents (int)
        yes_ask:  Current yes_ask in cents (int, may be None)
    """
    # 5 — Module filter (FIRST LINE)
    if position.get('module') != 'crypto_15m_dir':
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
```

---

## 4. Dedup / Throttle Logic

- **In-memory dict:** `_last_log_ts: dict[str, float]` — key is `"{ticker}::{side}"`, value is `time.time()` of last write.
- **Check:** `if now - last < 60: return` — skip if under 60s.
- **Update:** Set `_last_log_ts[position_key] = now` immediately before writing (prevents burst on slow I/O).
- **Reset:** `clear_session_dedup()` provided for day-boundary resets if needed (not required for correctness).

---

## 5. Module Filter

`if position.get('module') != 'crypto_15m_dir': return` — first line of function, same as terminal logger.

---

## 6. yes_bid / yes_ask Source

`check_exits(ticker, yes_bid, yes_ask, close_time)` already receives both as parameters (integers in cents from WS feed). Pass them directly to `maybe_log_price`. No market_cache needed.

**Unit note:** WS values arrive as integers (e.g. `45` = 45¢). The logger divides by 100 to store as floats (`0.45`) matching the schema. Matches `terminal_signal_logger` convention.

---

## 7. Log Directory

`PRICE_SERIES_DIR = _env_paths['logs'] / 'price_series'`  
Created with `mkdir(parents=True, exist_ok=True)` on first write. No pre-creation needed.

**File naming:** `{safe_ticker}.jsonl` — one file per ticker, appended across the full window. `safe_ticker` replaces any non-`[\\w-]` chars with `_` (defensive; tickers are well-formed in practice).

---

## 8. Error Handling

- All file I/O wrapped in `try/except Exception` → `logger.warning(...)` only. Never raises.
- Caller in `check_exits()` wraps the import+call in its own `try/except` with `logger.debug(...)`.
- Ticker parse failure → `seconds_elapsed/seconds_to_close/pct_window_elapsed` set to `None`; record still written with partial data. Price data is preserved.
- `yes_ask=None` → stored as `null` in JSON. Fine for analysis.

---

## 9. Acceptance Criteria

**Dev:**
- [ ] `intra_window_logger.py` exists in `environments/demo/`
- [ ] `check_exits()` calls `maybe_log_price(ticker, pos, yes_bid, yes_ask)` after terminal logger block
- [ ] `yes_bid` is stored as float (cents / 100), not raw int
- [ ] Non-`crypto_15m_dir` positions produce zero log entries

**QA:**
- [ ] With one open `crypto_15m_dir` position, exactly 1 record appears per 60s interval (±2s jitter acceptable due to WS tick timing)
- [ ] Two positions in the same ticker produce independent throttle keys and log independently
- [ ] Log file path is `logs/price_series/{ticker}.jsonl`; directory auto-created on first write
- [ ] `seconds_elapsed + seconds_to_close ≈ 900` (within ±2s) for mid-window entries
- [ ] `pct_window_elapsed` is in [0.0, 1.0]
- [ ] Injecting an exception in the file-write path does not crash `check_exits()`

---

**DS**
