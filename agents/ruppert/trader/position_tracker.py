"""
position_tracker.py — WS-driven real-time position exit tracker
Replaces 30-min polling loop with instant exit on threshold hit.

When a tracked position's bid hits the exit threshold, exit immediately.
Called by ws_feed.py on every ticker tick for tracked positions.
"""

import asyncio
import json
import logging
import re
import sys
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytz

# Resolve workspace root and add to path for env_config
_AGENTS_ROOT = Path(__file__).parent.parent.parent  # workspace/agents
_WORKSPACE_ROOT = _AGENTS_ROOT.parent               # workspace/
if str(_WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE_ROOT))

from agents.ruppert.env_config import get_paths as _get_paths, require_live_enabled, get_current_env  # noqa: E402
import config
# _log_exit/_log_settle are the public log_exit/log_settle functions from logger.py (aliased).
# They include dedup fingerprint checking. ISSUE-023 confirmed resolved in Sprint 3.
from agents.ruppert.data_scientist.logger import (
    log_activity, normalize_entry_price, _append_jsonl, log_exit as _log_exit, log_settle as _log_settle,
    acquire_exit_lock, release_exit_lock,
)
from agents.ruppert.trader import circuit_breaker as _circuit_breaker

logger = logging.getLogger(__name__)

_env_paths = _get_paths()
TRACKER_FILE = _env_paths['logs'] / 'tracked_positions.json'
LOGS_DIR = _env_paths['logs']
TRADES_DIR = _env_paths['trades']  # P0-1 fix: trade files go to logs/trades/

# Exit thresholds — config-driven (fallbacks preserve current behavior)
EXIT_95C_THRESHOLD = getattr(config, 'EXIT_95C_THRESHOLD', 95)
EXIT_GAIN_PCT      = getattr(config, 'EXIT_GAIN_PCT', None)
if EXIT_GAIN_PCT is None:
    raise ImportError('[position_tracker] EXIT_GAIN_PCT not found in config — check config.py')


def _today_pdt() -> str:
    """Return today's date string in PDT/PST (America/Los_Angeles), formatted YYYY-MM-DD."""
    return datetime.now(pytz.timezone('America/Los_Angeles')).strftime('%Y-%m-%d')


# ─────────────────────────────── Daily CB helper ──────────────────────────────


def _update_daily_cb(module: str, window_ts: str, pnl: float) -> None:
    """Update per-module CB state after a daily contract settles.

    Called after each crypto_band_daily_* or crypto_threshold_daily_* settlement.
    A win (pnl > 0) resets consecutive losses; a loss increments them.

    Args:
        module:     Module key, e.g. 'crypto_band_daily_btc'
        window_ts:  Timestamp string identifying this settlement window
        pnl:        Realized P&L for this contract (positive=win, negative=loss)
    """
    if not (module.startswith('crypto_band_daily_') or
            module.startswith('crypto_threshold_daily_')):
        return  # Only for daily modules

    try:
        cb_n = getattr(config, 'CRYPTO_DAILY_CIRCUIT_BREAKER_N',
                       getattr(config, 'CRYPTO_1H_CIRCUIT_BREAKER_N', 3))

        if pnl <= 0:
            _circuit_breaker.increment_consecutive_losses(module, window_ts)
        else:
            _circuit_breaker.reset_consecutive_losses(module, window_ts)

        losses = _circuit_breaker.get_consecutive_losses(module)
        logger.info(
            '[PositionTracker][CB] %s: pnl=$%.2f -> %s | consecutive_losses=%d (threshold=%d)',
            module, pnl, 'loss' if pnl <= 0 else 'win', losses, cb_n
        )
    except Exception as _cb_err:
        logger.warning('[PositionTracker][CB] update failed for %s: %s', module, _cb_err)


# ─────────────────────────────── In-memory state ──────────────────────────────

# {ticker: {quantity, side, entry_price, module, title, exit_thresholds: [{price, action}]}}
_tracked = {}

# Dedup guard: tracks (ticker, side) keys currently in the middle of execute_exit()
# Prevents WS duplicate events from firing two exits for the same position.
_exits_in_flight: set[tuple] = set()
_exits_lock = asyncio.Lock()

# Post-exit cooldown guard: prevents sequential re-fires after position removal.
# Maps (ticker, side) -> unix timestamp of completed exit.
# Entries are held for _EXIT_COOLDOWN_TTL seconds.
_EXIT_COOLDOWN_TTL = 300  # 5 minutes
_recently_exited: dict[tuple, float] = {}

# Write-off log dedup: only log once per ticker per write-off window bucket.
# Prevents ~1000s of identical "daily write-off — skipping sell" lines per contract.
# Key: (ticker, side, mins_bucket) where mins_bucket = int(_mins_left).
# Cleared in remove_position() when the position is finally removed.
_write_off_logged: set[tuple] = set()


_MONTH_MAP = {
    'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
    'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12,
}


def _parse_close_time(ticker: str) -> 'datetime | None':
    """Parse settlement datetime (UTC) from a Kalshi ticker string.

    Supports both daily and 15m tickers:
      KXBTC-26APR0207-B66375   → 2026-04-02 11:00 UTC  (daily, MM=0)
      KXBTCD-26APR0213-T67499  → 2026-04-02 17:00 UTC  (daily, MM=0)
      KXBTC15M-26APR011315-15  → 2026-04-01 17:15 UTC  (15m, MM=15)

    Returns None on any parse failure — callers must handle gracefully.
    """
    try:
        parts = ticker.split('-')
        if len(parts) >= 2:
            m = re.match(r'(\d{2})([A-Z]{3})(\d{2})(\d{2})(\d{2})?', parts[1])
            if m:
                yr  = 2000 + int(m.group(1))
                mon = _MONTH_MAP.get(m.group(2))
                dd  = int(m.group(3))
                hh  = int(m.group(4))
                mm  = int(m.group(5)) if m.group(5) else 0
                if mon:
                    from pytz import timezone as _tz
                    _est = _tz('America/New_York')
                    _naive = datetime(yr, mon, dd, hh, mm)
                    return _est.localize(_naive).astimezone(timezone.utc)
    except Exception:
        pass
    return None


# Thread-safety note: add_position() and remove_position() are synchronous
# functions with no await points. Under CPython's GIL, dict mutations and
# the _tracked.copy() snapshot in _persist() are effectively atomic. A
# concurrent race between add and remove cannot occur unless these functions
# are made async — at which point an asyncio.Lock should be added here.
def _persist():
    """Write tracked positions to disk. Keys are serialized as 'ticker::side' strings."""
    try:
        TRACKER_FILE.parent.mkdir(exist_ok=True)
        tmp = TRACKER_FILE.with_suffix('.tmp')
        serialized = {f'{k[0]}::{k[1]}': v for k, v in _tracked.items()}
        tmp.write_text(json.dumps(serialized, indent=2), encoding='utf-8')
        tmp.replace(TRACKER_FILE)
    except Exception as e:
        logger.warning('[PositionTracker] Persist failed: %s', e)


def _load():
    """Load tracked positions from disk on startup. Handles legacy (ticker-only) keys."""
    global _tracked
    if not TRACKER_FILE.exists():
        return
    try:
        data = json.loads(TRACKER_FILE.read_text(encoding='utf-8'))
        for key_str, value in data.items():
            if '::' in key_str:
                parts = key_str.split('::', 1)
                key = (parts[0], parts[1])
            else:
                # Legacy key: ticker string only — use side from value
                key = (key_str, value.get('side', 'yes'))
            _tracked[key] = value
        logger.info('[PositionTracker] Loaded %d tracked positions from disk', len(_tracked))
    except Exception as e:
        logger.warning('[PositionTracker] Load failed: %s', e)


# ─────────────────────────────── Public API ───────────────────────────────────

def _build_thresholds(side: str, entry_price: float, holding_type: str = '') -> list:
    """Build exit threshold list for a given side, entry price, and holding type.

    Extracted as a private helper so both the new-position and accumulate paths
    in add_position() can call it cleanly.
    """
    skip_gain_exit = (holding_type == 'long_horizon')
    if side == 'yes':
        thresholds = [
            {'price': EXIT_95C_THRESHOLD, 'action': 'sell_all', 'rule': '95c_rule'},
        ]
        if not skip_gain_exit:
            gain_target = entry_price + EXIT_GAIN_PCT * (100 - entry_price)
            if gain_target < EXIT_95C_THRESHOLD:
                thresholds.append({
                    'price': round(gain_target, 1),
                    'action': 'sell_all',
                    'rule': '70pct_gain',
                })
    else:  # no side
        thresholds = [
            {'price': 5, 'action': 'sell_all', 'rule': '95c_rule_no', 'compare': 'lte'},
        ]
        if not skip_gain_exit:
            no_gain_target = 100 - (entry_price + EXIT_GAIN_PCT * (100 - entry_price))
            if no_gain_target > 5:
                thresholds.append({
                    'price': round(no_gain_target, 1),
                    'action': 'sell_all',
                    'rule': '70pct_gain_no',
                    'compare': 'lte',
                })
    return thresholds


def add_position(ticker: str, quantity: int, side: str, entry_price: float,
                 module: str = '', title: str = '', holding_type: str = '',
                 entry_raw_score: float | None = None,
                 size_dollars: float | None = None,
                 entry_secs_in_window: float | None = None,
                 contract_remaining_at_entry: float | None = None):
    """
    Call after every trade execution.
    entry_price: in cents (e.g. 45 = 45c).
    holding_type: 'long_horizon' skips the 70% gain exit threshold.
    size_dollars: actual dollar cost paid for this leg. If not provided,
                  computed as entry_price * quantity / 100.

    When a position for (ticker, side) already exists, accumulates the new leg:
    total quantity is summed and entry_price is blended (weighted average).
    This preserves all legs for correct P&L and settlement tracking.
    """
    if size_dollars is None:
        size_dollars = round(entry_price * quantity / 100, 2)

    key = (ticker, side)
    existing = _tracked.get(key)
    if existing:
        # Accumulate: merge new leg into existing position
        old_qty = existing['quantity']
        old_price = existing['entry_price']
        new_qty = old_qty + quantity
        # Weighted-average entry price
        blended_price = round((old_price * old_qty + entry_price * quantity) / new_qty, 2)
        existing['quantity'] = new_qty
        existing['entry_price'] = blended_price
        existing['size_dollars'] = round(existing.get('size_dollars', 0) + size_dollars, 2)
        # Refresh thresholds for new blended price
        existing['exit_thresholds'] = _build_thresholds(side, blended_price, holding_type)
        logger.info(
            '[PositionTracker] Accumulated %s %s: +%d contracts (total=%d, blended_entry=%.1fc)',
            ticker, side, quantity, new_qty, blended_price
        )
    else:
        thresholds = _build_thresholds(side, entry_price, holding_type)
        _tracked[key] = {
            'quantity': quantity,
            'side': side,
            'entry_direction': side.lower(),
            'entry_price': entry_price,
            'module': module,
            'title': title,
            'added_at': time.time(),
            'exit_thresholds': thresholds,
            'entry_raw_score': entry_raw_score,
            'size_dollars': size_dollars,
            'entry_secs_in_window': entry_secs_in_window,
            'contract_remaining_at_entry': contract_remaining_at_entry,
        }
        logger.info('[PositionTracker] Tracking %s %s @ %dc (%d contracts)', ticker, side, entry_price, quantity)
    _persist()


def remove_position(ticker: str, side: str):
    """Call after exit execution."""
    _tracked.pop((ticker, side), None)
    # NOTE: do NOT discard from _exits_in_flight here.
    # Discarding inside remove_position() broke the in-flight guard by clearing it
    # before execute_exit()'s finally block ran. The finally block in execute_exit()
    # is the sole place responsible for clearing _exits_in_flight.
    # Clear write-off dedup entries for this position so they don't accumulate.
    for _wo_k in [k for k in _write_off_logged if k[0] == ticker and k[1] == side]:
        _write_off_logged.discard(_wo_k)
    _persist()


def get_tracked() -> dict:
    """Return copy of tracked positions (for diagnostics). Keys serialized as 'ticker::side'."""
    return {f'{k[0]}::{k[1]}': v for k, v in _tracked.items()}


def get_active_positions(
    asset: str = None,
    settlement_date: str = None,
) -> list[dict]:
    """Return active tracked positions, optionally filtered by asset and/or settlement date.

    Args:
        asset:           If provided (e.g. 'BTC'), only return positions whose ticker
                         contains this string (case-insensitive).
        settlement_date: If provided (e.g. '2026-03-31'), only return positions whose
                         ticker encodes this settlement date. The date is parsed from
                         tickers in the format {EVENT}-{YY}{MON}{DD}-{STRIKE}
                         (e.g. 'KXBTC2026-26MAR31-B90000').

    Returns:
        List of position dicts. Each dict contains at minimum:
            ticker, side, quantity, entry_price, module, title, exit_thresholds
        A 'market_id' key is also set to the ticker value for compatibility
        with callers that use pos.get('market_id').

    Filtering behaviour:
        - asset=None, settlement_date=None  →  return all active positions (no filter)
        - asset='BTC'                       →  ticker must contain 'BTC' (case-insensitive)
        - settlement_date='2026-03-31'      →  ticker must encode settlement on 2026-03-31
        - Both provided                     →  both conditions must match (AND logic)

    No existing callers break: all kwargs default to None, so bare
    get_active_positions() returns all positions as expected.
    """
    MONTH_MAP = {
        'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
        'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12,
    }

    # Parse target settlement date once (avoid re-parsing per position)
    target_date = None
    if settlement_date is not None:
        try:
            from datetime import date as _date
            target_date = _date.fromisoformat(settlement_date)
        except ValueError:
            pass  # invalid date string — filter will match nothing

    results = []
    for (ticker, side), data in _tracked.items():
        # --- asset filter ---
        if asset is not None:
            if asset.upper() not in ticker.upper():
                continue

        # --- settlement_date filter ---
        if settlement_date is not None:
            # Parse date from ticker: look for -{YY}{MON}{DD}- pattern
            import re as _re
            m = _re.search(r'-(\d{2})([A-Z]{3})(\d{2})-', ticker.upper())
            if not m:
                continue  # no date in ticker; skip when filter is active
            try:
                yy  = int(m.group(1))
                mon = MONTH_MAP.get(m.group(2))
                dd  = int(m.group(3))
                if mon is None:
                    continue
                from datetime import date as _date
                ticker_date = _date(2000 + yy, mon, dd)
            except (ValueError, KeyError):
                continue
            if target_date is None or ticker_date != target_date:
                continue

        # Build output record from stored data dict
        record = dict(data)
        record.setdefault('ticker', ticker)
        record.setdefault('side', side)
        record['market_id'] = ticker   # compatibility alias for crypto_1d callers
        results.append(record)

    return results


def is_tracked(ticker: str, side: str) -> bool:
    return (ticker, side) in _tracked


async def check_exits(ticker: str, yes_bid: int | None, yes_ask: int | None,
                      close_time: str | None = None):
    """
    Called by WS feed on every tick for tracked tickers.
    yes_bid/yes_ask in cents (as received from WS, already divided by 100 not needed).
    close_time: ISO 8601 UTC string from WS message (e.g. '2026-03-31T14:30:00Z').
                Used for settlement guard — when provided and current time is within
                SETTLEMENT_GUARD_WINDOW_SECS of close_time, REST-verify result before
                executing any 'lte' (NO-side) exit triggered by yes_bid = 0.
    """
    if yes_bid is None:
        return

    # Prune stale cooldown entries
    now = time.time()
    expired = [k for k, t in _recently_exited.items() if now - t > _EXIT_COOLDOWN_TTL]
    for k in expired:
        del _recently_exited[k]

    matching_keys = [k for k in _tracked if k[0] == ticker]
    for key in matching_keys:
        pos = _tracked.get(key)
        if not pos:
            continue

        side = key[1]

        # Cooldown guard: block re-fire on recently exited positions
        if key in _recently_exited:
            logger.warning(
                '[PositionTracker] Cooldown guard: %s %s was exited %.0fs ago — suppressing re-fire',
                key[0], key[1], time.time() - _recently_exited[key]
            )
            continue

        # Terminal signal logger — shadow log for crypto_15m_dir positions near close
        try:
            from terminal_signal_logger import maybe_log_terminal
            maybe_log_terminal(ticker, pos, yes_bid, close_time=close_time)
        except Exception as _tsl_err:
            logger.debug('[PositionTracker] terminal_signal_logger: %s', _tsl_err)

        # Intra-window price logger — shadow log for crypto_15m_dir positions
        try:
            from intra_window_logger import maybe_log_price
            maybe_log_price(ticker, pos, yes_bid, yes_ask)
        except Exception as _iwl_err:
            logger.debug('[PositionTracker] intra_window_logger: %s', _iwl_err)

        # ── Design D: Entry-aware layered stop-loss for crypto_dir_15m_ positions ──
        # Three tiers: Catastrophic (20%, no time check), Severe (30%, 5min left),
        # Terminal (40%, 3.5min left). Guard threshold is adaptive to entry timing.
        # YES-side only: Design D stops compare yes_bid < entry_price * pct.
        # For NO positions (entry_price=3c), this would effectively never fire —
        # NO-side exits are handled via the 'lte' threshold checks below.
        if pos.get('module', '').startswith('crypto_dir_15m_') and pos.get('added_at') and side == 'yes':
            # Skip if this position already has a pending exit order
            if key in _exits_in_flight:
                pass  # let threshold checks run instead
            else:
                entry_price = pos['entry_price']
                elapsed_secs = now - pos['added_at']

                # Step 1: Compute entry-aware guard threshold
                # entry_secs_in_window: seconds from window open to entry
                # Default 120 (2 min) for legacy positions — preserves current behavior
                entry_secs = pos.get('entry_secs_in_window', getattr(config, 'STOP_LEGACY_ENTRY_SECS_DEFAULT', 120))

                _STOP_BRACKET_LATE  = getattr(config, 'STOP_BRACKET_LATE',  480)
                _STOP_BRACKET_MID   = getattr(config, 'STOP_BRACKET_MID',   300)
                _STOP_BRACKET_EARLY = getattr(config, 'STOP_BRACKET_EARLY', 180)

                if entry_secs >= _STOP_BRACKET_LATE:          # entry at 8+ min
                    min_elapsed = getattr(config, 'STOP_GUARD_SECONDARY',    90)
                elif entry_secs >= _STOP_BRACKET_MID:         # entry at 5-8 min
                    min_elapsed = getattr(config, 'STOP_GUARD_LATE_PRIMARY', 180)
                elif entry_secs >= _STOP_BRACKET_EARLY:       # entry at 3-5 min
                    min_elapsed = getattr(config, 'STOP_GUARD_MID_PRIMARY',  300)
                else:                                          # entry before 3 min (most common)
                    min_elapsed = getattr(config, 'STOP_GUARD_EARLY_PRIMARY', 480)

                # Step 2: Guard check — only evaluate stops once guard has elapsed
                if elapsed_secs >= min_elapsed:
                    # Parse contract close time from ticker using shared helper
                    # e.g. KXBTC15M-26APR011315-15 -> opens 13:15 EST, closes 13:30 EST
                    _close_dt = _parse_close_time(ticker)

                    if _close_dt is not None:
                        _now_utc = datetime.now(tz=timezone.utc)
                        time_remaining = (_close_dt - _now_utc).total_seconds()

                        _STOP_PRICE_CATASTROPHIC = getattr(config, 'STOP_PRICE_CATASTROPHIC', 0.20)
                        _STOP_PRICE_SEVERE       = getattr(config, 'STOP_PRICE_SEVERE',       0.30)
                        _STOP_PRICE_TERMINAL     = getattr(config, 'STOP_PRICE_TERMINAL',     0.40)
                        _STOP_TIME_SEVERE        = getattr(config, 'STOP_TIME_SEVERE',        300)
                        _STOP_TIME_TERMINAL      = getattr(config, 'STOP_TIME_TERMINAL',      210)

                        # --- TIER 1: Catastrophic Stop ---
                        # Fire immediately on near-zero price, no time check needed.
                        # At 20% of entry price, 80% of capital is gone — no recovery expected.
                        if yes_bid < entry_price * _STOP_PRICE_CATASTROPHIC:
                            rule = f'stop_loss_catastrophic_{elapsed_secs:.0f}s'
                            log_activity(
                                f'[WS Exit] {ticker} hit {rule} (bid={yes_bid}c, entry={entry_price}c) — exiting'
                            )
                            await execute_exit(key, pos, yes_bid, rule)
                            continue  # position exited, skip threshold checks

                        # --- TIER 2: Severe Stop ---
                        # Fire if below 30% of entry and 5 min or less remaining.
                        if yes_bid < entry_price * _STOP_PRICE_SEVERE and time_remaining < _STOP_TIME_SEVERE:
                            rule = f'stop_loss_severe_{elapsed_secs:.0f}s'
                            log_activity(
                                f'[WS Exit] {ticker} hit {rule} (bid={yes_bid}c, entry={entry_price}c) — exiting'
                            )
                            await execute_exit(key, pos, yes_bid, rule)
                            continue  # position exited, skip threshold checks

                        # --- TIER 3: Terminal Stop (current behavior, preserved) ---
                        # Fire if below 40% of entry and 3.5 min or less remaining.
                        if yes_bid < entry_price * _STOP_PRICE_TERMINAL and time_remaining < _STOP_TIME_TERMINAL:
                            rule = f'stop_loss_terminal_{elapsed_secs:.0f}s'
                            log_activity(
                                f'[WS Exit] {ticker} hit {rule} (bid={yes_bid}c, entry={entry_price}c) — exiting'
                            )
                            await execute_exit(key, pos, yes_bid, rule)
                            continue  # position exited, skip threshold checks
        # ── End Design D stop-loss ────────────────────────────────────────────────────

        # ── Stop-loss for crypto_band_daily_* and crypto_threshold_daily_* ──
        # Settlement time is parsed from the ticker (same helper as check_expired_positions).
        # Replaces prior hardcoded 21:00 UTC which was wrong for hourly contracts.
        _mod = pos.get('module', '')
        if (_mod.startswith('crypto_threshold_daily_') or _mod.startswith('crypto_band_daily_')) and pos.get('added_at') and side == 'yes':
            # YES-side only: all tier checks compare yes_bid < entry_price * pct.
            # For NO-side, yes_bid rising = loss (inverse). NO-side exits handled by 'lte' threshold checks.
            if key in _exits_in_flight:
                pass  # let threshold checks run instead
            else:
                entry_price = pos['entry_price']
                elapsed_secs = now - pos['added_at']

                # ── Entry guard: 30 min before any stop evaluates ──────────────
                _daily_guard = getattr(config, 'DAILY_STOP_ENTRY_GUARD_SECS', 1800)
                if elapsed_secs >= _daily_guard:

                    # ── Parse settlement time from ticker ──────────────────────
                    # e.g. KXBTC-26APR0207-B66375  → 2026-04-02 11:00 UTC
                    # e.g. KXBTCD-26APR0213-T67499 → 2026-04-02 17:00 UTC
                    _settle_dt = _parse_close_time(ticker)

                    if _settle_dt is None:
                        # Cannot parse settlement — skip safely rather than fire wrong stop
                        logger.warning(
                            '[PositionTracker] daily stop: no settlement time for %s — skipping stop check',
                            ticker
                        )
                    else:
                        _now_utc = datetime.now(tz=timezone.utc)
                        _time_remaining = (_settle_dt - _now_utc).total_seconds()

                        if _time_remaining > 0:  # skip if settlement already passed

                            # Load config constants (with safe fallbacks)
                            _write_off_time = getattr(config, 'DAILY_STOP_WRITE_OFF_TIME_SECS',    1200)
                            _cat_pct        = getattr(config, 'DAILY_STOP_CATASTROPHIC_PCT',        0.15)
                            _cat_abs        = getattr(config, 'DAILY_STOP_CATASTROPHIC_ABS_CENTS',  2)
                            _severe_pct     = getattr(config, 'DAILY_STOP_SEVERE_PCT',              0.25)
                            _severe_time    = getattr(config, 'DAILY_STOP_SEVERE_TIME_SECS',        3600)
                            _terminal_pct   = getattr(config, 'DAILY_STOP_TERMINAL_PCT',            0.30)
                            _terminal_time  = getattr(config, 'DAILY_STOP_TERMINAL_TIME_SECS',      1200)

                            _mins_left = _time_remaining / 60

                            # ── LEVEL 1: Write-off ─────────────────────────────────────────
                            # Bid at 1c near settlement → let expire; not worth selling
                            if yes_bid <= 1 and _time_remaining < _write_off_time:
                                _wo_key = (ticker, side, int(_mins_left))
                                if _wo_key not in _write_off_logged:
                                    _write_off_logged.add(_wo_key)
                                    log_activity(
                                        f'[WS Exit] {ticker} daily write-off '
                                        f'(bid={yes_bid}c, T-{_mins_left:.0f}min) — skipping sell'
                                    )
                                continue  # do NOT exit — let it expire to 0

                            # ── LEVEL 2: Catastrophic stop (no time check) ─────────────────
                            # Below 15% of entry (or absolute ≤2c floor) → cut regardless of time
                            _cat_threshold = max(entry_price * _cat_pct, _cat_abs)
                            if yes_bid < _cat_threshold:
                                rule = f'daily_stop_catastrophic_{elapsed_secs:.0f}s'
                                log_activity(
                                    f'[WS Exit] {ticker} daily CATASTROPHIC stop '
                                    f'(bid={yes_bid}c < {_cat_threshold:.1f}c, '
                                    f'T-{_mins_left:.0f}min) — exiting'
                                )
                                await execute_exit(key, pos, yes_bid, rule)
                                continue

                            # ── LEVEL 3: Severe stop (< 1 hour remaining) ──────────────────
                            # Below 25% of entry with < 1 hour left — recovery needs 4x move
                            if yes_bid < entry_price * _severe_pct and _time_remaining < _severe_time:
                                rule = f'daily_stop_severe_{_time_remaining:.0f}s_left'
                                log_activity(
                                    f'[WS Exit] {ticker} daily SEVERE stop '
                                    f'(bid={yes_bid}c < 25% of {entry_price}c, '
                                    f'T-{_mins_left:.0f}min) — exiting'
                                )
                                await execute_exit(key, pos, yes_bid, rule)
                                continue

                            # ── LEVEL 4: Terminal stop (< 20 min remaining) ────────────────
                            # Below 30% of entry with < 20 min — near-certain loss, cut now
                            if yes_bid < entry_price * _terminal_pct and _time_remaining < _terminal_time:
                                rule = f'daily_stop_terminal_{_time_remaining:.0f}s_left'
                                log_activity(
                                    f'[WS Exit] {ticker} daily TERMINAL stop '
                                    f'(bid={yes_bid}c < 30% of {entry_price}c, '
                                    f'T-{_mins_left:.0f}min) — exiting'
                                )
                                await execute_exit(key, pos, yes_bid, rule)
                                continue
        # ── End daily stop-loss ───────────────────────────────────────────────

        thresholds = pos.get('exit_thresholds')
        if thresholds is None:
            logger.warning('[PositionTracker] %s missing exit_thresholds — skipping exit check', ticker)
            continue
        for threshold in thresholds:
            compare = threshold.get('compare', 'gte')
            price_target = threshold['price']
            triggered = False

            if compare == 'lte':
                # For NO positions: trigger when yes_bid drops below threshold
                triggered = yes_bid <= price_target
            else:
                # For YES positions: trigger when yes_bid rises above threshold
                triggered = yes_bid >= price_target

            if triggered:
                rule = threshold.get('rule', 'threshold')

                # ── Settlement Guard (P0 fix 2026-03-31) ──────────────────────
                # When yes_bid = 0 at settlement time, the orderbook has cleared
                # regardless of outcome. Verify actual result via REST before
                # acting on any lte-triggered NO exit near the settlement window.
                if compare == 'lte' and yes_bid == 0 and close_time is not None:
                    _guard_secs = getattr(config, 'SETTLEMENT_GUARD_WINDOW_SECS', 90)
                    _guarded = False
                    try:
                        from datetime import timezone as _tz
                        _close_dt = datetime.fromisoformat(
                            close_time.replace('Z', '+00:00')
                        )
                        _now_utc = datetime.now(tz=_tz.utc)
                        _secs_to_close = (_close_dt - _now_utc).total_seconds()
                        if abs(_secs_to_close) <= _guard_secs:
                            _guarded = True
                    except Exception as _e:
                        logger.warning(
                            '[PositionTracker] Settlement guard: close_time parse failed '
                            'for %s (%s): %s — proceeding without guard',
                            ticker, close_time, _e
                        )

                    if _guarded:
                        # We are within the settlement window. Verify via REST.
                        try:
                            from agents.ruppert.data_analyst.kalshi_client import KalshiClient as _KC
                            _client = _KC()
                            _market = _client.get_market(ticker)
                            _result = _market.get('result') if _market else None
                        except Exception as _e:
                            logger.error(
                                '[PositionTracker] Settlement guard: REST get_market failed '
                                'for %s: %s — skipping this tick (will retry)',
                                ticker, _e
                            )
                            continue  # skip tick; retry on next WS message

                        if _result is None:
                            # Not yet settled — orderbook cleared but result pending.
                            # Skip this tick. Next tick will retry.
                            logger.info(
                                '[PositionTracker] Settlement guard: %s result=None '
                                '(not yet settled) — holding, will retry next tick',
                                ticker
                            )
                            continue  # retry next tick

                        elif _result == 'no':
                            # NO won — proceed with exit at exit price 0c (correct win).
                            # yes_bid = 0 is accurate here: YES is worthless.
                            logger.info(
                                '[PositionTracker] Settlement guard: %s result=no '
                                '— NO won, proceeding with exit at 0c',
                                ticker
                            )
                            # Fall through to execute_exit below (no changes needed)

                        elif _result == 'yes':
                            # YES won — our NO position is worthless. Log as loss.
                            logger.info(
                                '[PositionTracker] Settlement guard: %s result=yes '
                                '— YES won, logging SETTLE_LOSS and removing position',
                                ticker
                            )
                            await execute_exit(
                                key, pos, current_bid=0, rule='SETTLE_LOSS',
                                settle_loss=True
                            )
                            break

                        else:
                            # Unexpected result value — log and skip safely
                            logger.warning(
                                '[PositionTracker] Settlement guard: %s unexpected result=%r '
                                '— skipping exit, investigate manually',
                                ticker, _result
                            )
                            continue
                # ── End Settlement Guard ───────────────────────────────────────

                log_activity(
                    f'[WS Exit] {ticker} hit {rule} (bid={yes_bid}c, target={price_target}c) — exiting'
                )
                await execute_exit(key, pos, yes_bid, rule)
                break


async def execute_exit(key: tuple, pos: dict, current_bid: int, rule: str,
                       settle_loss: bool = False):
    """Execute the exit order via REST.

    settle_loss: When True, this is a confirmed settlement loss (YES won while we
                 held NO). Skip the actual sell order (position is already worthless),
                 log with SETTLE_LOSS action_detail, and record correct negative P&L.
    """
    ticker, side = key

    # Cross-process file lock — coordinates with post_trade_monitor
    if not acquire_exit_lock(ticker, side):
        logger.warning(
            '[PositionTracker] Exit file-lock held for %s %s — another process is exiting. Skipping.',
            ticker, side
        )
        return

    # Dedup guard: if this (ticker, side) exit is already in-flight, skip.
    # Atomic check-and-set under lock (ISSUE-002).
    async with _exits_lock:
        if key in _exits_in_flight:
            release_exit_lock(ticker, side)
            logger.warning(
                '[PositionTracker] Dedup guard: exit for %s %s already in-flight — skipping duplicate',
                ticker, side
            )
            return
        _exits_in_flight.add(key)

    try:
        # ── Snapshot position data before any await (ISSUE-107) ──────────────
        # Prevents stale reads if another task modifies _tracked during an await.
        entry_price  = pos['entry_price']
        quantity     = pos['quantity']
        module       = pos.get('module', '')
        title        = pos.get('title', '')
        size_dollars = pos.get('size_dollars')
        # ── End snapshot ─────────────────────────────────────────────────────

        from agents.ruppert.data_analyst.kalshi_client import KalshiClient

        # ── Settlement Loss Path ──────────────────────────────────────────────
        # When settle_loss=True: YES won, our NO is worthless.
        # exit_price = 0c (NO value at settlement = 0), P&L is negative.
        # Do NOT submit a sell order — position has already settled to zero.
        if settle_loss:
            # NO-side loss: use size_dollars as the true cost for accurate P&L.
            # entry_price for NO positions is the correct NO price (e.g. 3c).
            # size_dollars was computed at add_position() time from the actual fill.
            pnl = -(size_dollars if size_dollars is not None else entry_price * quantity / 100)
            settle_opp = {
                'ticker': ticker, 'title': title, 'side': side, 'action': 'settle',
                'source': 'ws_position_tracker', 'module': module,
                'entry_price': entry_price, 'contracts': quantity, 'pnl': round(pnl, 2),
                'timestamp': datetime.now().isoformat(), 'date': _today_pdt(),
            }
            _log_settle(settle_opp, round(pnl, 2), quantity, {'result': 'yes'},
                        exit_price=0,
                        settlement_result='yes',
                        action_detail='SETTLE_LOSS yes_won @ 0c')
            print(
                f'  [WS EXIT] {ticker} {side.upper()} SETTLE_LOSS | YES won | P&L=${pnl:+.2f}'
            )

            # ── Daily module CB update ────────────────────────────────────────
            if module.startswith('crypto_band_daily_') or module.startswith('crypto_threshold_daily_'):
                _sl_window_ts = datetime.now(tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
                _update_daily_cb(module, _sl_window_ts, pnl)

            remove_position(ticker, side)
            _recently_exited[(ticker, side)] = time.time()
            return  # Do NOT fall through to sell order logic
        # ── End Settlement Loss Path ──────────────────────────────────────────

        # P&L in dollars
        if side == 'yes':
            pnl = (current_bid - entry_price) * quantity / 100
        else:
            # NO position: entry_price and exit_price are both in NO-side cents.
            # entry_price is stored as NO price (e.g. 70c if bought when YES=30c).
            # exit_price (NO side) = 100 - current_bid (yes_bid).
            # P&L = (exit_price_no - entry_price_no) * contracts / 100
            exit_price_no = 100 - current_bid
            pnl = (exit_price_no - entry_price) * quantity / 100

        _dry_run = getattr(config, 'DRY_RUN', True)
        if _dry_run:
            order_result = {'dry_run': True, 'status': 'simulated'}
        else:
            from agents.ruppert.env_config import require_live_enabled
            require_live_enabled()
            try:
                client = KalshiClient()
                order_result = client.sell_position(ticker, side, current_bid, quantity)
            except Exception as e:
                logger.error('[WS Exit] Execute failed for %s: %s', ticker, e)
                # Track consecutive failures (ISSUE-003) — write to live pos dict
                pos['_exit_failures'] = pos.get('_exit_failures', 0) + 1
                _persist()
                if pos['_exit_failures'] >= 3:
                    # 3 consecutive exit failures — abandon position and alert.
                    # No time gate: a brief API blip can trigger this. Accepted tradeoff.
                    logger.error(
                        '[WS Exit] %s %s: 3 consecutive exit failures — abandoning position',
                        ticker, side
                    )
                    try:
                        from agents.ruppert.trader.utils import push_alert
                        push_alert('error', f'EXIT ABANDONED after 3 failures: {ticker} {side.upper()}', ticker=ticker)
                    except Exception as _alert_err:
                        logger.error('[WS Exit] push_alert failed on abandonment: %s', _alert_err)
                    try:
                        _abandon_log_path = TRADES_DIR / f'trades_{_today_pdt()}.jsonl'
                        abandon_record = {
                            'trade_id': str(uuid.uuid4()),
                            'timestamp': datetime.now().isoformat(),
                            'date': _today_pdt(),
                            'ticker': ticker,
                            'title': title,
                            'side': side,
                            'action': 'exit',
                            'action_detail': 'ABANDONED after 3 exit failures — no fill confirmed',
                            'source': 'ws_position_tracker',
                            'module': module,
                            'entry_price': entry_price,
                            'exit_price': current_bid,
                            'contracts': quantity,
                            'pnl': round(pnl, 2),
                        }
                        _append_jsonl(_abandon_log_path, abandon_record)
                    except Exception as _abandon_log_err:
                        logger.error('[WS Exit] Failed to write abandonment record for %s: %s', ticker, _abandon_log_err)
                    remove_position(ticker, side)
                    _recently_exited[key] = time.time()
                return

        # Log the exit trade — P0-1 fix: write to logs/trades/ not logs/
        log_path = TRADES_DIR / f'trades_{_today_pdt()}.jsonl'
        # For NO positions, exit_price should reflect the NO side price (100 - yes_bid).
        # Entry_price is already stored as the NO price. Exit_price should match the same convention.
        exit_price_logged = current_bid if side == 'yes' else (100 - current_bid)

        action_detail_price = current_bid if side == 'yes' else (100 - current_bid)
        exit_opp = {
            'ticker': ticker, 'title': title, 'side': side, 'action': 'exit',
            'source': 'ws_position_tracker', 'module': module,
            'entry_price': entry_price, 'contracts': quantity, 'pnl': round(pnl, 2),
            'timestamp': datetime.now().isoformat(), 'date': _today_pdt(),
        }
        _log_exit(exit_opp, round(pnl, 2), quantity, {'rule': rule},
                  exit_price=exit_price_logged,
                  action_detail=f'WS_EXIT {rule} @ {action_detail_price}c (yes_bid={current_bid}c)')
        print(f'  [WS EXIT] {ticker} {side.upper()} @ {current_bid}c | {rule} | P&L=${pnl:+.2f}')

        # ── Daily module CB update ────────────────────────────────────────
        if module.startswith('crypto_band_daily_') or module.startswith('crypto_threshold_daily_'):
            _exit_window_ts = datetime.now(tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            _update_daily_cb(module, _exit_window_ts, pnl)

        remove_position(ticker, side)
        _recently_exited[(ticker, side)] = time.time()  # cooldown: prevent re-fire for TTL window
    finally:
        _exits_in_flight.discard(key)
        release_exit_lock(ticker, side)


def _settle_record_exists(ticker: str, side: str) -> bool:
    """Return True if a settle or exit record already exists for (ticker, side) today or yesterday."""
    for day_offset in (0, 1):  # today and yesterday (midnight boundary edge case)
        check_date = date.fromisoformat(_today_pdt()) - timedelta(days=day_offset)
        log_path = TRADES_DIR / f'trades_{check_date.isoformat()}.jsonl'
        if not log_path.exists():
            continue
        try:
            for line in log_path.read_text(encoding='utf-8').splitlines():
                try:
                    rec = json.loads(line.strip())
                    if (rec.get('ticker') == ticker and
                            rec.get('side') == side and
                            rec.get('action') in ('exit', 'settle')):
                        return True
                except Exception:
                    continue
        except Exception:
            pass
    return False


async def check_expired_positions():
    """Check for positions whose close_time has passed and log settlement outcome.

    Runs periodically (every 60s from ws_feed). For 15m positions that expire
    without hitting exit thresholds, REST-verifies settlement and logs the result.
    """
    if not _tracked:
        return

    now_utc = datetime.now(tz=timezone.utc)
    keys_to_remove = []

    for key in list(_tracked.keys()):
        ticker, side = key
        pos = _tracked.get(key)
        if not pos:
            continue

        # Parse close_time from ticker using shared helper
        close_dt = _parse_close_time(ticker)

        if close_dt is None or now_utc < close_dt:
            continue  # not expired yet (or can't parse)

        # Position has expired — REST-verify settlement
        try:
            from agents.ruppert.data_analyst.kalshi_client import KalshiClient
            client = KalshiClient()
            market = client.get_market(ticker)
            if not market:
                continue
            result = market.get('result')
            if not result:  # catches None, empty string '', and other falsy values
                continue  # not yet settled — skip, retry next cycle
        except Exception as e:
            logger.warning('[PositionTracker] check_expired: REST failed for %s: %s', ticker, e)
            continue

        # ISSUE-025: guard against double-settlement (settlement_checker may have already written)
        if _settle_record_exists(ticker, side):
            logger.info(
                '[PositionTracker] check_expired: settle record already exists for %s %s — removing from tracker (no duplicate write)',
                ticker, side
            )
            keys_to_remove.append(key)
            _recently_exited[key] = time.time()
            continue  # skip writing, just clean up tracker

        # Calculate realized P&L from settlement
        entry_price = pos['entry_price']
        quantity = pos['quantity']
        module = pos.get('module', '')

        # Settlement price: YES=100c if result='yes', YES=0c if result='no'
        if side == 'yes':
            settlement_price = 100 if result == 'yes' else 0
            pnl = (settlement_price - entry_price) * quantity / 100
        else:
            # NO side: entry_price is the correct NO price (e.g. 3c for a contract
            # bought at 3c NO = 97c YES). P&L formula matches YES convention.
            if result == 'no':
                # NO won — full payout minus cost
                settlement_price = 100
                pnl = (100 - entry_price) * quantity / 100
            else:
                # NO lost (YES won) — loss equals what we paid
                settlement_price = 0
                pnl = -pos.get('size_dollars', entry_price * quantity / 100)

        # Log settlement trade via logger.log_settle() for schema enrichment + dedup
        settle_opp = {
            'ticker': ticker, 'title': pos.get('title', ''), 'side': side, 'action': 'settle',
            'source': 'ws_position_tracker', 'module': module,
            'entry_price': entry_price, 'contracts': quantity, 'pnl': round(pnl, 2),
            'timestamp': datetime.now().isoformat(), 'date': _today_pdt(),
        }
        _log_settle(settle_opp, round(pnl, 2), quantity, {'result': result},
                    exit_price=settlement_price,
                    settlement_result=result,
                    action_detail=f'EXPIRY result={result} settlement={settlement_price}c')
        logger.info(
            '[PositionTracker] Expired %s %s: result=%s, P&L=$%.2f',
            ticker, side, result, pnl
        )

        # ── Daily module CB update ────────────────────────────────────────
        if module.startswith('crypto_band_daily_') or module.startswith('crypto_threshold_daily_'):
            _settle_window_ts = (close_dt.strftime('%Y-%m-%dT%H:%M:%SZ')
                                 if close_dt else datetime.now(tz=timezone.utc).isoformat())
            _update_daily_cb(module, _settle_window_ts, pnl)

        keys_to_remove.append(key)

    for key in keys_to_remove:
        _tracked.pop(key, None)
        _recently_exited[key] = time.time()
    if keys_to_remove:
        _persist()


async def recovery_poll_positions():
    """Call on WS disconnect — REST poll all tracked positions to catch missed moves."""
    if not _tracked:
        return

    logger.info('[PositionTracker] Recovery polling %d tracked positions', len(_tracked))

    try:
        from agents.ruppert.data_analyst.kalshi_client import KalshiClient
        client = KalshiClient()
    except Exception as e:
        logger.error('[PositionTracker] Recovery poll: client init failed: %s', e)
        return

    for key in list(_tracked.keys()):
        ticker = key[0]
        try:
            market = client.get_market(ticker)
            if not market:
                continue
            yes_bid = market.get('yes_bid')
            yes_ask = market.get('yes_ask')
            close_time = market.get('close_time')  # pass for settlement guard
            if yes_bid is not None:
                await check_exits(ticker, yes_bid, yes_ask, close_time=close_time)
        except Exception as e:
            logger.warning('[PositionTracker] Recovery poll failed for %s: %s', ticker, e)


# Load on import
_load()
