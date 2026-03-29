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
from datetime import date, datetime
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

# Exit thresholds (match existing post_trade_monitor rules)
EXIT_95C_THRESHOLD = 95       # cents — auto-exit if bid >= 95c
EXIT_GAIN_PCT = 0.70          # 70% of max profit — auto-exit


# ─────────────────────────────── In-memory state ──────────────────────────────

# {ticker: {quantity, side, entry_price, module, title, exit_thresholds: [{price, action}]}}
_tracked = {}


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

def add_position(ticker: str, quantity: int, side: str, entry_price: float,
                 module: str = '', title: str = '', holding_type: str = ''):
    """
    Call after every trade execution.
    entry_price: in cents (e.g. 45 = 45c).
    holding_type: 'long_horizon' skips the 70% gain exit threshold.
    """
    skip_gain_exit = (holding_type == 'long_horizon')

    # P0-4 fix: standardize NO positions to always use NO price.
    # DRY_RUN sometimes passes YES price for NO side (entry_price < 50 when side='no').
    # Convert: if side='no' and entry_price looks like YES price (< 50), flip it.
    if side == 'no' and entry_price < 50:
        entry_price = 100 - entry_price

    if side == 'yes':
        thresholds = [
            {'price': EXIT_95C_THRESHOLD, 'action': 'sell_all', 'rule': '95c_rule'},
        ]
        # 70% gain threshold: entry_price + 70% of (100 - entry_price)
        # Skip for long_horizon positions (price has days/weeks to move)
        if not skip_gain_exit:
            gain_target = entry_price + EXIT_GAIN_PCT * (100 - entry_price)
            if gain_target < EXIT_95C_THRESHOLD:
                thresholds.append({
                    'price': round(gain_target, 1),
                    'action': 'sell_all',
                    'rule': '70pct_gain',
                })
    else:  # no side
        # For NO positions, track yes_bid dropping (our NO value rises)
        # 95c rule: yes_bid <= 5 means no_ask >= 95
        thresholds = [
            {'price': 5, 'action': 'sell_all', 'rule': '95c_rule_no', 'compare': 'lte'},
        ]
        # P0-4 fix: correct NO-side 70% gain formula.
        # entry_price is now guaranteed to be NO price (>= 50).
        # Max profit = 100 - entry_price cents. Exit when YES bid has fallen enough
        # that NO holder has gained 70% of max profit.
        # no_gain_target = 100 - (entry_price + EXIT_GAIN_PCT * (100 - entry_price))
        if not skip_gain_exit:
            no_gain_target = 100 - (entry_price + EXIT_GAIN_PCT * (100 - entry_price))
            if no_gain_target > 5:  # Only add if meaningful (above the 95c rule floor)
                thresholds.append({
                    'price': round(no_gain_target, 1),
                    'action': 'sell_all',
                    'rule': '70pct_gain_no',
                    'compare': 'lte',
                })

    _tracked[(ticker, side)] = {
        'quantity': quantity,
        'side': side,
        'entry_price': entry_price,
        'module': module,
        'title': title,
        'added_at': time.time(),
        'exit_thresholds': thresholds,
    }
    _persist()
    logger.info('[PositionTracker] Tracking %s %s @ %dc (%d contracts)', ticker, side, entry_price, quantity)


def remove_position(ticker: str, side: str):
    """Call after exit execution."""
    _tracked.pop((ticker, side), None)
    _persist()


def get_tracked() -> dict:
    """Return copy of tracked positions (for diagnostics). Keys serialized as 'ticker::side'."""
    return {f'{k[0]}::{k[1]}': v for k, v in _tracked.items()}


def is_tracked(ticker: str, side: str) -> bool:
    return (ticker, side) in _tracked


async def check_exits(ticker: str, yes_bid: int | None, yes_ask: int | None):
    """
    Called by WS feed on every tick for tracked tickers.
    yes_bid/yes_ask in cents (as received from WS, already divided by 100 not needed).
    """
    if yes_bid is None:
        return

    matching_keys = [k for k in _tracked if k[0] == ticker]
    for key in matching_keys:
        pos = _tracked.get(key)
        if not pos:
            continue

        for threshold in pos['exit_thresholds']:
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
                log_activity(
                    f'[WS Exit] {ticker} hit {rule} (bid={yes_bid}c, target={price_target}c) — exiting'
                )
                await execute_exit(key, pos, yes_bid, rule)
                break


async def execute_exit(key: tuple, pos: dict, current_bid: int, rule: str):
    """Execute the exit order via REST."""
    from agents.ruppert.data_analyst.kalshi_client import KalshiClient

    ticker, side = key
    entry_price = pos['entry_price']
    quantity = pos['quantity']
    module = pos.get('module', '')

    # P&L in dollars
    if side == 'yes':
        pnl = (current_bid - entry_price) * quantity / 100
    else:
        # NO position: our cost was (100 - entry_price), our exit value is (100 - current_bid)
        pnl = ((100 - current_bid) - (100 - entry_price)) * quantity / 100

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

    exit_record = {
        'trade_id': str(uuid.uuid4()),
        'timestamp': datetime.now().isoformat(),
        'date': str(date.today()),
        'ticker': ticker,
        'title': pos.get('title', ''),
        'side': side,
        'action': 'exit',
        'action_detail': f'WS_EXIT {rule} @ {current_bid}c',
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
            if yes_bid is not None:
                await check_exits(ticker, yes_bid, yes_ask)
        except Exception as e:
            logger.warning('[PositionTracker] Recovery poll failed for %s: %s', ticker, e)


# Load on import
_load()
