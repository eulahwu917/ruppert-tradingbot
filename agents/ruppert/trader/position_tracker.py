"""
position_tracker.py — WS-driven real-time position exit tracker
Replaces 30-min polling loop with instant exit on threshold hit.

When a tracked position's bid hits the exit threshold, exit immediately.
Called by ws_feed.py on every ticker tick for tracked positions.
"""

import json
import logging
import sys
import time
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

# Resolve workspace root and add to path for env_config
_AGENTS_ROOT = Path(__file__).parent.parent.parent  # workspace/agents
_WORKSPACE_ROOT = _AGENTS_ROOT.parent               # workspace/
if str(_WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE_ROOT))

from agents.ruppert.env_config import get_paths as _get_paths, require_live_enabled, get_current_env  # noqa: E402
import config
from agents.ruppert.data_scientist.logger import log_activity, normalize_entry_price

logger = logging.getLogger(__name__)

_env_paths = _get_paths()
TRACKER_FILE = _env_paths['logs'] / 'tracked_positions.json'
LOGS_DIR = _env_paths['logs']
TRADES_DIR = _env_paths['trades']  # P0-1 fix: trade files go to logs/trades/

# Exit thresholds — config-driven (fallbacks preserve current behavior)
EXIT_95C_THRESHOLD = getattr(config, 'EXIT_95C_THRESHOLD', 95)
EXIT_GAIN_PCT      = getattr(config, 'EXIT_GAIN_PCT', 0.70)


# ─────────────────────────────── In-memory state ──────────────────────────────

# {ticker: {quantity, side, entry_price, module, title, exit_thresholds: [{price, action}]}}
_tracked = {}

# Dedup guard: tracks (ticker, side) keys currently in the middle of execute_exit()
# Prevents WS duplicate events from firing two exits for the same position.
_exits_in_flight: set[tuple] = set()

# Post-exit cooldown guard: prevents sequential re-fires after position removal.
# Maps (ticker, side) -> unix timestamp of completed exit.
# Entries are held for _EXIT_COOLDOWN_TTL seconds.
_EXIT_COOLDOWN_TTL = 300  # 5 minutes
_recently_exited: dict[tuple, float] = {}


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
        migrated = 0
        for key_str, value in data.items():
            if '::' in key_str:
                parts = key_str.split('::', 1)
                key = (parts[0], parts[1])
            else:
                # Legacy key: ticker string only — use side from value
                key = (key_str, value.get('side', 'yes'))
            # Migrate legacy NO positions stored with YES-side entry price (< 50).
            # Pre-2026-03-28 fix: add_position() did not flip NO entry prices.
            # Convert: if side='no' and entry_price < 50, flip to NO price.
            if value.get('side') == 'no' and isinstance(value.get('entry_price'), (int, float)):
                if value['entry_price'] < 50:
                    value['entry_price'] = 100 - value['entry_price']
                    migrated += 1
            _tracked[key] = value
        if migrated:
            logger.info('[PositionTracker] Migrated %d legacy NO position(s) with flipped entry_price', migrated)
            _persist()  # Write corrected data back to disk immediately
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
                 size_dollars: float | None = None):
    """
    Call after every trade execution.
    entry_price: in cents (e.g. 45 = 45c).
    holding_type: 'long_horizon' skips the 70% gain exit threshold.
    size_dollars: actual dollar cost paid for this leg. If not provided,
                  computed as entry_price * quantity / 100 BEFORE any NO-side
                  price flip (so the value reflects true cost even when the
                  flip transforms entry_price).

    When a position for (ticker, side) already exists, accumulates the new leg:
    total quantity is summed and entry_price is blended (weighted average).
    This preserves all legs for correct P&L and settlement tracking.
    """
    # Compute size_dollars BEFORE the NO-side price flip so it reflects true cost.
    if size_dollars is None:
        size_dollars = round(entry_price * quantity / 100, 2)

    # P0-4 fix: standardize NO positions to always use NO price.
    # DRY_RUN sometimes passes YES price for NO side (entry_price < 50 when side='no').
    # Convert: if side='no' and entry_price looks like YES price (< 50), flip it.
    if side == 'no' and entry_price < 50:
        entry_price = 100 - entry_price

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

        # ── Time-gated stop-loss for crypto_15m_dir positions ─────────────
        # Prevents losing positions from riding to 0c at expiry.
        # Runs alongside threshold exits — whichever triggers first wins.
        if pos.get('module') == 'crypto_15m_dir' and pos.get('added_at'):
            elapsed_min = (now - pos['added_at']) / 60.0
            entry_price = pos['entry_price']
            stop_triggered = False
            if 5 <= elapsed_min < 10 and yes_bid < entry_price * 0.30:
                stop_triggered = True
            elif 10 <= elapsed_min < 13 and yes_bid < entry_price * 0.40:
                stop_triggered = True
            # 0-5 min: no stop (too early, noise)
            # 13-15 min: no stop (spread too wide near expiry, let it settle)
            if stop_triggered:
                rule = f'stop_loss_{elapsed_min:.0f}m'
                log_activity(
                    f'[WS Exit] {ticker} hit {rule} (bid={yes_bid}c, entry={entry_price}c) — exiting'
                )
                await execute_exit(key, pos, yes_bid, rule)
                continue  # position exited, skip threshold checks
        # ── End time-gated stop-loss ──────────────────────────────────────

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

    # Dedup guard: if this (ticker, side) exit is already in-flight, skip.
    # Prevents WS duplicate events from firing two exits for the same position.
    # NOTE: does NOT use contracts as part of the key — a single position per
    # (ticker, side) key is the invariant enforced by add_position(). Scale-in
    # is not possible for the same key; Cases 2 & 3 had distinct keys before
    # this guard existed.
    if key in _exits_in_flight:
        logger.warning(
            '[PositionTracker] Dedup guard: exit for %s %s already in-flight — skipping duplicate',
            ticker, side
        )
        return

    _exits_in_flight.add(key)
    try:
        from agents.ruppert.data_analyst.kalshi_client import KalshiClient

        entry_price = pos['entry_price']
        quantity = pos['quantity']
        module = pos.get('module', '')

        # ── Settlement Loss Path ──────────────────────────────────────────────
        # When settle_loss=True: YES won, our NO is worthless.
        # exit_price = 0c (NO value at settlement = 0), P&L is negative.
        # Do NOT submit a sell order — position has already settled to zero.
        if settle_loss:
            # NO-side loss: use size_dollars as the true cost (entry_price is unreliable
            # due to the NO-side flip in add_position — 15m passes correct NO price but
            # flip converts e.g. 3c → 97c, inflating the calculated loss).
            pnl = -pos.get('size_dollars', entry_price * quantity / 100)
            log_path = TRADES_DIR / f'trades_{date.today().isoformat()}.jsonl'
            exit_record = {
                'trade_id': str(uuid.uuid4()),
                'timestamp': datetime.now().isoformat(),
                'date': str(date.today()),
                'ticker': ticker,
                'title': pos.get('title', ''),
                'side': side,
                'action': 'exit',
                'action_detail': f'SETTLE_LOSS yes_won @ 0c',
                'source': 'ws_position_tracker',
                'module': module,
                'entry_price': entry_price,
                'exit_price': 0,
                'contracts': quantity,
                'pnl': round(pnl, 2),
            }
            try:
                with open(log_path, 'a', encoding='utf-8') as f:
                    f.write(json.dumps(exit_record) + '\n')
            except Exception as e:
                logger.error('[WS Exit] SETTLE_LOSS log write failed for %s: %s', ticker, e)
            log_activity(
                f'[WS EXIT] {ticker} {side.upper()} SETTLE_LOSS | YES won | P&L=${pnl:+.2f}'
            )
            print(
                f'  [WS EXIT] {ticker} {side.upper()} SETTLE_LOSS | YES won | P&L=${pnl:+.2f}'
            )
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
                return

        # Log the exit trade — P0-1 fix: write to logs/trades/ not logs/
        log_path = TRADES_DIR / f'trades_{date.today().isoformat()}.jsonl'
        # For NO positions, exit_price should reflect the NO side price (100 - yes_bid).
        # Entry_price is already stored as the NO price. Exit_price should match the same convention.
        exit_price_logged = current_bid if side == 'yes' else (100 - current_bid)

        action_detail_price = current_bid if side == 'yes' else (100 - current_bid)
        exit_record = {
            'trade_id': str(uuid.uuid4()),
            'timestamp': datetime.now().isoformat(),
            'date': str(date.today()),
            'ticker': ticker,
            'title': pos.get('title', ''),
            'side': side,
            'action': 'exit',
            'action_detail': f'WS_EXIT {rule} @ {action_detail_price}c (yes_bid={current_bid}c)',
            'source': 'ws_position_tracker',
            'module': module,
            'entry_price': entry_price,
            'exit_price': exit_price_logged,
            'contracts': quantity,
            'pnl': round(pnl, 2),
        }

        try:
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(exit_record) + '\n')
        except Exception as e:
            logger.error('[WS Exit] Log write failed for %s: %s', ticker, e)

        log_activity(f'[WS EXIT] {ticker} {side.upper()} @ {current_bid}c | {rule} | P&L=${pnl:+.2f}')
        print(f'  [WS EXIT] {ticker} {side.upper()} @ {current_bid}c | {rule} | P&L=${pnl:+.2f}')

        remove_position(ticker, side)
        _recently_exited[(ticker, side)] = time.time()  # cooldown: prevent re-fire for TTL window
    finally:
        _exits_in_flight.discard(key)


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

        # Parse close_time from ticker: format KXBTC15M-26APR011315-15
        # The window close = window open + 15 minutes
        close_dt = None
        try:
            import re
            parts = ticker.split('-')
            if len(parts) >= 2:
                date_part = parts[1]
                m = re.match(r'(\d{2})([A-Z]{3})(\d{2})(\d{2})(\d{2})', date_part)
                if m:
                    MONTH_MAP = {
                        'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
                        'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12,
                    }
                    yr = 2000 + int(m.group(1))
                    mon = MONTH_MAP.get(m.group(2))
                    dd = int(m.group(3))
                    hh = int(m.group(4))
                    mm = int(m.group(5))
                    if mon:
                        from datetime import timedelta
                        open_dt = datetime(yr, mon, dd, hh, mm, tzinfo=timezone.utc)
                        close_dt = open_dt + timedelta(minutes=15)
        except Exception:
            pass

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
            if result is None:
                continue  # not yet settled, retry next cycle
        except Exception as e:
            logger.warning('[PositionTracker] check_expired: REST failed for %s: %s', ticker, e)
            continue

        # Calculate realized P&L from settlement
        entry_price = pos['entry_price']
        quantity = pos['quantity']
        module = pos.get('module', '')

        # Settlement price: YES=100c if result='yes', YES=0c if result='no'
        if side == 'yes':
            settlement_price = 100 if result == 'yes' else 0
            pnl = (settlement_price - entry_price) * quantity / 100
        else:
            # NO side: entry_price is unreliable due to the NO-side flip in
            # add_position() (15m passes correct NO price but flip converts
            # e.g. 3c → 97c). Use size_dollars for losses, formula for wins.
            if result == 'no':
                # NO won — full payout minus cost
                settlement_price = 100
                pnl = (100 - entry_price) * quantity / 100
            else:
                # NO lost (YES won) — loss equals what we paid
                settlement_price = 0
                pnl = -pos.get('size_dollars', entry_price * quantity / 100)

        # Log settlement trade
        log_path = TRADES_DIR / f'trades_{date.today().isoformat()}.jsonl'
        settle_record = {
            'trade_id': str(uuid.uuid4()),
            'timestamp': datetime.now().isoformat(),
            'date': str(date.today()),
            'ticker': ticker,
            'title': pos.get('title', ''),
            'side': side,
            'action': 'settle',
            'action_detail': f'EXPIRY result={result} settlement={settlement_price}c',
            'source': 'ws_position_tracker',
            'module': module,
            'entry_price': entry_price,
            'exit_price': settlement_price,
            'contracts': quantity,
            'pnl': round(pnl, 2),
        }
        try:
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(settle_record) + '\n')
        except Exception as e:
            logger.error('[PositionTracker] check_expired: log write failed for %s: %s', ticker, e)

        log_activity(
            f'[SETTLE] {ticker} {side.upper()} expired | result={result} | P&L=${pnl:+.2f}'
        )
        logger.info(
            '[PositionTracker] Expired %s %s: result=%s, P&L=$%.2f',
            ticker, side, result, pnl
        )
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
