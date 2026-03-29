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

# Ensure project root is on sys.path when running standalone
_PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import config
from agents.data_scientist.logger import log_activity, normalize_entry_price

logger = logging.getLogger(__name__)

DRY_RUN = getattr(config, 'DRY_RUN', True)

TRACKER_FILE = _PROJECT_ROOT / 'logs' / 'tracked_positions.json'
LOGS_DIR = _PROJECT_ROOT / 'logs'

# Exit thresholds (match existing post_trade_monitor rules)
EXIT_95C_THRESHOLD = 95       # cents — auto-exit if bid >= 95c
EXIT_GAIN_PCT = 0.70          # 70% of max profit — auto-exit


# ─────────────────────────────── In-memory state ──────────────────────────────

# {ticker: {quantity, side, entry_price, module, title, exit_thresholds: [{price, action}]}}
_tracked = {}


def _persist():
    """Write tracked positions to disk."""
    try:
        TRACKER_FILE.parent.mkdir(exist_ok=True)
        tmp = TRACKER_FILE.with_suffix('.tmp')
        tmp.write_text(json.dumps(_tracked, indent=2), encoding='utf-8')
        tmp.replace(TRACKER_FILE)
    except Exception as e:
        logger.warning('[PositionTracker] Persist failed: %s', e)


def _load():
    """Load tracked positions from disk on startup."""
    global _tracked
    if not TRACKER_FILE.exists():
        return
    try:
        data = json.loads(TRACKER_FILE.read_text(encoding='utf-8'))
        _tracked.update(data)
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

    _tracked[ticker] = {
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


def remove_position(ticker: str):
    """Call after exit execution."""
    _tracked.pop(ticker, None)
    _persist()


def get_tracked() -> dict:
    """Return copy of tracked positions (for diagnostics)."""
    return dict(_tracked)


def is_tracked(ticker: str) -> bool:
    return ticker in _tracked


async def check_exits(ticker: str, yes_bid: int | None, yes_ask: int | None):
    """
    Called by WS feed on every tick for tracked tickers.
    yes_bid/yes_ask in cents (as received from WS, already divided by 100 not needed).
    """
    pos = _tracked.get(ticker)
    if not pos or yes_bid is None:
        return

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
            await execute_exit(ticker, pos, yes_bid, rule)
            return


async def execute_exit(ticker: str, pos: dict, current_bid: int, rule: str):
    """Execute the exit order via REST."""
    from agents.data_analyst.kalshi_client import KalshiClient

    side = pos['side']
    entry_price = pos['entry_price']
    quantity = pos['quantity']
    module = pos.get('module', '')

    # P&L in dollars
    if side == 'yes':
        pnl = (current_bid - entry_price) * quantity / 100
    else:
        # NO position: our cost was (100 - entry_price), our exit value is (100 - current_bid)
        pnl = ((100 - current_bid) - (100 - entry_price)) * quantity / 100

    if DRY_RUN:
        order_result = {'dry_run': True, 'status': 'simulated'}
    else:
        try:
            client = KalshiClient()
            order_result = client.sell_position(ticker, side, current_bid, quantity)
        except Exception as e:
            logger.error('[WS Exit] Execute failed for %s: %s', ticker, e)
            return

    # Log the exit trade
    log_path = LOGS_DIR / f'trades_{date.today().isoformat()}.jsonl'
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
        'exit_price': current_bid,
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

    remove_position(ticker)


async def recovery_poll_positions():
    """Call on WS disconnect — REST poll all tracked positions to catch missed moves."""
    if not _tracked:
        return

    logger.info('[PositionTracker] Recovery polling %d tracked positions', len(_tracked))

    try:
        from agents.data_analyst.kalshi_client import KalshiClient
        client = KalshiClient()
    except Exception as e:
        logger.error('[PositionTracker] Recovery poll: client init failed: %s', e)
        return

    for ticker in list(_tracked.keys()):
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
