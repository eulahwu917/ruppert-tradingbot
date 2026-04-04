"""
Post-Trade Position Monitor
Deprecated: WS position tracker (position_tracker.py + ws_feed.py) handles exits
in real-time. This runs as a safety net — polling fallback for any missed exits.

Unified post-entry position watcher for ALL modules.
Checks exit conditions based on module type, executes auto-exits or queues alerts.
Runs every 30 minutes via Task Scheduler (6am-11pm).

Usage: python post_trade_monitor.py
"""
import sys
import json
import os
import uuid
import time
from pathlib import Path
from datetime import date, datetime, timedelta, timezone

# Ensure project root is on sys.path when running standalone
# Resolve workspace root and add to path (agents.ruppert.* + config shim)
_AGENTS_ROOT = Path(__file__).parent.parent.parent  # workspace/agents
_WORKSPACE_ROOT = _AGENTS_ROOT.parent               # workspace/
if str(_WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE_ROOT))

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

from agents.ruppert.env_config import get_paths as _get_paths
from agents.ruppert.env_config import is_live_enabled as _is_live_enabled
LOGS = _get_paths()['logs']
LOGS.mkdir(exist_ok=True)
LOGS_DIR = LOGS  # alias used by settlement checker
TRADES_DIR = _get_paths()['trades']
TRADES_DIR.mkdir(parents=True, exist_ok=True)

import config
from scripts.event_logger import log_event
# DRY_RUN intentionally not captured at module level — read at call time inside run_monitor()

from agents.ruppert.data_analyst.kalshi_client import KalshiClient
from agents.ruppert.data_scientist.logger import log_trade, log_activity, acquire_exit_lock, release_exit_lock, normalize_entry_price, _append_jsonl
from agents.ruppert.trader import position_tracker
from agents.ruppert.trader import circuit_breaker

def ts():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _update_circuit_breaker_state(module_key: str, window_open_ts: str, settlements: list):
    """
    Classify the just-settled window as complete loss or win, then update
    the unified circuit breaker state via circuit_breaker module.

    Called after each 15m window's positions are fully settled.

    Args:
        module_key:      CB module key (e.g. 'crypto_dir_15m_btc')
        window_open_ts:  ISO timestamp of the window that just settled
        settlements:     List of settlement result dicts for this window.
                         Each dict must have at minimum: {'payout': float}
                         where payout = 0.0 for a loss, >0 for a win.
    """
    if not settlements:
        return  # No settlements to classify — don't update state

    # Classify the window
    payouts = [float(s.get('payout', 0.0)) for s in settlements]
    if all(p == 0.0 for p in payouts):
        window_result = 'loss'
        circuit_breaker.increment_consecutive_losses(module_key, window_open_ts)
    else:
        window_result = 'win'
        circuit_breaker.reset_consecutive_losses(module_key, window_open_ts)

    cb_n = getattr(config, 'CRYPTO_15M_CIRCUIT_BREAKER_N', 3)
    losses = circuit_breaker.get_consecutive_losses(module_key)
    if losses >= cb_n:
        print(
            f'  [circuit_breaker] Advisory: {losses} consecutive complete-loss '
            f'windows for {module_key} (threshold={cb_n}).'
        )

    print(
        f'  [circuit_breaker] Window {window_open_ts} result={window_result}, '
        f'consecutive_losses={losses} ({module_key})'
    )


def check_settlements(client):
    """Check for settled DEMO positions and compute simulated P&L.

    Runs each monitor cycle before position checks. Loads open buys from
    today's + yesterday's trade log, identifies markets past their target_date
    or close_time, fetches resolution from Kalshi, logs a 'settle' action,
    and updates pnl_cache.json.
    """
    print(f"\n  [Settlement Checker] running...")

    today = date.today()

    # Scan a rolling 365-day window to catch long-horizon positions (monthly/annual).
    # Extended from 30 days — positions entered more than 30 days ago were silently
    # skipped by the settlement checker. Most files don't exist; skipped via exists().
    logs_to_check = []
    for days_back in range(365):
        log_date = today - timedelta(days=days_back)
        logs_to_check.append(TRADES_DIR / f"trades_{log_date.isoformat()}.jsonl")

    # Build open positions (same logic as load_open_positions)
    entries_by_key = {}      # (ticker, side) → list of buy records
    exit_count_by_key = {}   # (ticker, side) → count of exit/settle records
    settle_keys = set()  # already settled this cycle — track from logs

    for trade_log in logs_to_check:
        if not trade_log.exists():
            continue
        for line in trade_log.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            ticker = rec.get('ticker', '')
            side = rec.get('side', '')
            action = rec.get('action', 'buy')
            key = (ticker, side)
            if action in ('exit', 'settle'):
                exit_count_by_key[key] = exit_count_by_key.get(key, 0) + 1
                if action == 'settle':
                    settle_keys.add(key)
            else:
                if key not in entries_by_key:
                    entries_by_key[key] = []
                entries_by_key[key].append(rec)

    # Sync tracker: remove any positions that already have settle records
    # (handles cases where tracker cleanup was missed on prior runs)
    for (s_ticker, s_side) in settle_keys:
        position_tracker.remove_position(s_ticker, s_side)

    open_positions = []
    for key, recs in entries_by_key.items():
        exits = exit_count_by_key.get(key, 0)
        open_positions.extend(recs[exits:])

    if not open_positions:
        print(f"  [Settlement Checker] no open positions to check")
        return

    settled_count = 0
    # Accumulate settlements per (module_key, window_open_ts) for circuit breaker update.
    # dict: (module_key, window_open_ts) → list of {'payout': float}
    _module_window_settlements: dict = {}
    for pos in open_positions:
        ticker = pos.get('ticker', '')
        side = pos.get('side', '')
        key = (ticker, side)
        if not ticker or not side:
            continue

        # Only check positions whose target date has passed or that look mature
        target_date_str = pos.get('target_date') or pos.get('date', '')
        try:
            target_date = date.fromisoformat(str(target_date_str)) if target_date_str else None
        except Exception:
            target_date = None

        # Skip if target_date is in the future (market still open)
        if target_date and target_date > today:
            continue

        # Fetch market from Kalshi (with retry on transient errors)
        MAX_RETRIES = 3
        market = None
        for attempt in range(MAX_RETRIES):
            try:
                market = client.get_market(ticker)
                break
            except Exception as e:
                if attempt < MAX_RETRIES - 1:
                    wait = 2 ** attempt  # attempt=0 → 1s, attempt=1 → 2s
                    print(f"  [Settlement Checker] API error for {ticker} (attempt {attempt+1}/{MAX_RETRIES}): {e} — retrying in {wait}s")
                    time.sleep(wait)
                else:
                    print(f"  [Settlement Checker] API error for {ticker} after {MAX_RETRIES} attempts: {e} — skipping")
        if market is None:
            continue

        if not market:
            continue

        # Determine if market is resolved
        result = market.get('result', '')
        status = market.get('status', '')
        yes_bid = market.get('yes_bid', 50)

        if result in ('yes', 'no'):
            pass  # resolved via explicit result field
        elif status in ('settled', 'finalized'):
            # Status confirms settlement — infer from bid only when unambiguous
            if (yes_bid or 0) >= 99:
                result = 'yes'
            elif (yes_bid or 0) <= 1:
                result = 'no'
            else:
                # Finalized but bid is ambiguous — cannot safely infer
                print(f"  [Settlement Checker] WARN: {ticker} status={status} but yes_bid={yes_bid} is ambiguous — skipping")
                continue
        else:
            # Not settled/finalized — skip (do NOT infer from bid alone)
            continue

        # Compute entry price
        entry_price = None
        fp = pos.get('fill_price')
        sp = pos.get('scan_price')
        mp = pos.get('market_prob')
        if fp is not None:
            try:
                entry_price = float(fp)
            except Exception:
                pass
        if entry_price is None and sp is not None:
            try:
                entry_price = float(sp)
            except Exception:
                pass
        if entry_price is None and mp is not None:
            try:
                entry_price = float(mp) * 100
            except Exception:
                pass
        if entry_price is None:
            entry_price = 50.0  # fallback

        contracts = int(pos.get('contracts', 1) or 1)

        # Determine exit_price and P&L
        if side == 'yes':
            if result == 'yes':
                exit_price = 100
                pnl = (100 - entry_price) * contracts / 100
            else:  # result == 'no'
                exit_price = 1
                pnl = -(entry_price * contracts / 100)
        else:  # side == 'no'
            if result == 'no':
                exit_price = 100
                pnl = (100 - entry_price) * contracts / 100
            else:  # result == 'yes'
                exit_price = 1
                pnl = -(entry_price * contracts / 100)

        # Parse entry datetime for hold_duration
        try:
            entry_dt = datetime.fromisoformat(pos.get('timestamp', '').replace('Z', '+00:00').split('+')[0])
        except Exception:
            entry_dt = None

        # Write settle record directly to avoid build_trade_entry() schema stripping
        log_path = TRADES_DIR / f'trades_{date.today().isoformat()}.jsonl'
        settle_record = {
            "trade_id": str(uuid.uuid4()),
            "timestamp": datetime.now().isoformat(),
            "date": str(today),
            "ticker": ticker,
            "title": pos.get("title", ""),
            "side": side,
            "action": "settle",
            "action_detail": f"SETTLE {'WIN' if pnl > 0 else 'LOSS'} @ {exit_price}c",
            "source": "settlement_checker",
            "module": pos.get("module", ""),
            "settlement_result": result,
            "pnl": round(pnl, 2),
            "entry_price": entry_price,
            "exit_price": exit_price,
            "contracts": contracts,
            "size_dollars": pos.get("size_dollars", 0),
            "entry_edge": pos.get("edge", None),
            "confidence": pos.get("confidence", None),
            "hold_duration_hours": round((datetime.now() - entry_dt).total_seconds() / 3600, 2) if entry_dt else None,
            "market_prob": None,
            "scan_contracts": None,
            "fill_contracts": contracts,
            "scan_price": entry_price,
            "fill_price": exit_price,
            "order_result": {"dry_run": not _is_live_enabled(), "status": "settled"},
        }
        try:
            _append_jsonl(log_path, settle_record)
        except Exception as e:
            print(f"  [Settlement Checker] JSONL write error for {ticker}: {e}")
            continue

        log_event('SETTLEMENT', {
            'ticker': ticker,
            'side': side,
            'result': result,
            'pnl': round(pnl, 2),
            'entry_price': entry_price,
            'exit_price': exit_price,
            'contracts': contracts,
        })
        print(f"  [Settlement] {ticker} {side.upper()} → {result.upper()} | P&L=${pnl:+.2f}")
        settled_count += 1

        try:
            position_tracker.remove_position(ticker, side)
        except Exception as _pt_err:
            print(f"  [Settlement Checker] WARN: could not remove {ticker} {side} from tracker: {_pt_err}")

        # Accumulate settlements by (module_key, window_open_ts) for circuit breaker update.
        # Handles both 15m directional (crypto_dir_15m_*) and band daily (crypto_band_daily_*) modules.
        _pos_module = pos.get('module', '')
        _is_cb_module = (
            _pos_module.startswith('crypto_dir_15m_') or
            _pos_module.startswith('crypto_band_daily_') or
            _pos_module.startswith('crypto_threshold_daily_') or
            # Legacy taxonomy aliases — map to current names
            _pos_module in ('crypto_15m', 'crypto_15m_dir', 'crypto_1h_band', 'crypto_1h_dir')
        )
        if _is_cb_module:
            # Normalize legacy module names to current taxonomy
            _cb_module_key = _pos_module
            if _pos_module in ('crypto_15m', 'crypto_15m_dir'):
                _cb_module_key = 'crypto_dir_15m_btc'   # best-effort fallback; no asset tag in old records
            elif _pos_module == 'crypto_1h_band':
                _cb_module_key = 'crypto_band_daily_btc'  # best-effort fallback
            elif _pos_module == 'crypto_1h_dir':
                _cb_module_key = 'crypto_threshold_daily_btc'  # best-effort fallback
            _win_ts_key = pos.get('window_open_ts', pos.get('date', ''))
            if _win_ts_key:
                _cb_payout = exit_price if (
                    (side == 'yes' and result == 'yes') or
                    (side == 'no'  and result == 'no')
                ) else 0.0
                _module_window_settlements.setdefault((_cb_module_key, _win_ts_key), []).append({'payout': _cb_payout})

    if settled_count == 0:
        print(f"  [Settlement Checker] no newly settled positions")
    else:
        print(f"  [Settlement Checker] settled {settled_count} position(s)")

    # Update circuit breaker state for each fully-settled (module, window) pair
    for (cb_mod, win_ts), win_settlements in _module_window_settlements.items():
        try:
            _update_circuit_breaker_state(cb_mod, win_ts, win_settlements)
        except Exception as _cb_err:
            print(f"  [circuit_breaker] State update failed for {cb_mod}/{win_ts}: {_cb_err}")


def update_1h_circuit_breaker(window_ts: str, settlements: list, module_key: str = 'crypto_band_daily_btc'):
    """
    Update the band daily circuit breaker state after a band window settles.

    Called by check_settlements() after all crypto_band_daily positions for a given
    window_ts are settled. Delegates to the unified circuit_breaker module.

    Args:
        window_ts:   ISO timestamp identifying the settled window
        settlements: List of {'payout': float} dicts for the window
        module_key:  CB module key (default: 'crypto_band_daily_btc')
    """
    if not settlements:
        return

    payouts = [float(s.get('payout', 0.0)) for s in settlements]
    if all(p == 0.0 for p in payouts):
        window_result = 'loss'
        circuit_breaker.increment_consecutive_losses(module_key, window_ts)
    else:
        window_result = 'win'
        circuit_breaker.reset_consecutive_losses(module_key, window_ts)

    if module_key.startswith('crypto_dir_15m_'):
        cb_n = getattr(config, 'CRYPTO_15M_CIRCUIT_BREAKER_N', 3)
    elif module_key.startswith('crypto_band_daily_') or module_key.startswith('crypto_threshold_daily_'):
        cb_n = getattr(config, 'CRYPTO_DAILY_CIRCUIT_BREAKER_N', 5)
    else:
        cb_n = getattr(config, 'CRYPTO_1H_CIRCUIT_BREAKER_N', 3)
    losses = circuit_breaker.get_consecutive_losses(module_key)

    print(
        f'  [1h_circuit_breaker] Window {window_ts} result={window_result}, '
        f'consecutive_losses={losses} (threshold={cb_n}, module={module_key})'
    )


def push_alert(level, message, ticker=None, pnl=None):
    """Log alert candidate event. Data Scientist decides if it's alertworthy."""
    log_event('ALERT_CANDIDATE', {
        'level': level,
        'message': message,
        'ticker': ticker,
        'pnl': pnl,
    })


def load_open_positions():
    """Load open positions from trade logs, filtering out exits.

    Scans a 365-day rolling window to capture long-horizon positions
    (monthly, quarterly, annual markets). Most files will not exist and
    are skipped cheaply via exists() check.
    """
    today = date.today()

    # Scan rolling 365-day window to capture long-horizon positions (monthly/annual).
    # Extended from 30 days — a 30-day window silently dropped positions entered
    # more than 30 days ago (e.g. annual markets). Most files don't exist; the
    # exists() check is cheap.
    logs_to_check = []
    for days_back in range(365):
        log_date = today - timedelta(days=days_back)
        logs_to_check.append(TRADES_DIR / f"trades_{log_date.isoformat()}.jsonl")

    # P1-2 fix: key by (ticker, side) tuple instead of ticker alone.
    # Previously keyed by ticker only, so holding both YES and NO on the same
    # market would cause the second entry to overwrite the first.
    entries_by_key = {}      # (ticker, side) → list of buy records
    exit_count_by_key = {}   # (ticker, side) → count of exit/settle records

    for trade_log in logs_to_check:
        if not trade_log.exists():
            continue
        for line in trade_log.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            ticker = rec.get('ticker', '')
            side = rec.get('side', '')
            action = rec.get('action', 'buy')
            key = (ticker, side)
            if action in ('exit', 'settle'):
                exit_count_by_key[key] = exit_count_by_key.get(key, 0) + 1
            else:
                if key not in entries_by_key:
                    entries_by_key[key] = []
                entries_by_key[key].append(rec)

    # NOTE: DEMO-safe. For LIVE, run_monitor() processes each leg independently —
    # add dedup/aggregation before exit execution when deploying live.
    result = []
    for key, recs in entries_by_key.items():
        exits = exit_count_by_key.get(key, 0)
        result.extend(recs[exits:])
    return result


def get_market_data(ticker):
    """Fetch current market data from Kalshi API. Returns dict or None."""
    try:
        _client = KalshiClient()
        result = _client.get_market(ticker)
        return result if result else None
    except Exception:
        return None


def check_crypto_position(pos, market):
    """Check crypto exit conditions. Returns (action, reason) or (None, None)."""
    side = pos.get('side', 'no')
    entry_price = normalize_entry_price(pos)

    no_ask = market.get('no_ask') or 50
    yes_ask = market.get('yes_ask') or 50
    cur_price = no_ask if side == 'no' else yes_ask
    contracts = pos.get('contracts', 0)
    pnl = round((cur_price - entry_price) * contracts / 100, 2) if entry_price else 0

    # Check if market closes in < 30 minutes — do NOT auto-exit
    close_time = market.get('close_time', '')
    if close_time:
        try:
            ct = datetime.fromisoformat(close_time.replace('Z', '+00:00'))
            mins_left = (ct - datetime.now(timezone.utc)).total_seconds() / 60
            if mins_left < 30:
                return 'warn_near_close', f'<30min to close ({mins_left:.0f}m) — holding', cur_price, contracts, pnl
        except Exception:
            pass

    # 95c rule
    if side == 'no' and no_ask >= 95:
        return 'auto_exit', f'95c rule: no_ask={no_ask}c P&L=${pnl:+.2f}', cur_price, contracts, pnl
    if side == 'yes' and yes_ask >= 95:
        return 'auto_exit', f'95c rule: yes_ask={yes_ask}c P&L=${pnl:+.2f}', cur_price, contracts, pnl

    # Gain exit rule (config-driven threshold)
    _exit_gain_pct = getattr(config, 'EXIT_GAIN_PCT', 0.70)
    if entry_price and entry_price < 100:
        gain_pct = (cur_price - entry_price) / (100 - entry_price) if (100 - entry_price) > 0 else 0
        if gain_pct >= _exit_gain_pct:
            return 'auto_exit', f'{_exit_gain_pct:.0%} gain: {gain_pct:.0%} gain P&L=${pnl:+.2f}', cur_price, contracts, pnl

    return None, None, cur_price, contracts, pnl


def run_monitor():
    """Main monitor loop — check all open positions and execute/alert as needed."""
    _dry_run = getattr(config, 'DRY_RUN', True)
    print(f"\n{'='*60}")
    print(f"  POST-TRADE MONITOR  {ts()}")
    print(f"{'='*60}")

    client = KalshiClient()

    # Run settlement checker first — resolves DEMO positions that have expired
    try:
        check_settlements(client)
    except Exception as e:
        print(f"  [Settlement Checker] ERROR (non-fatal): {e}")

    positions = load_open_positions()
    if not positions:
        print("  No open positions today.")
        print(f"\nMonitor done. {ts()}")
        return

    print(f"  {len(positions)} open position(s) to check\n")
    checked = 0
    skipped = 0
    exits_executed = 0
    alerts_queued = 0

    for pos in positions:
        ticker = pos.get('ticker', '')
        side = pos.get('side', '')
        source = pos.get('source', pos.get('module', 'bot'))
        entry_price = pos.get('entry_price') or pos.get('market_prob')
        contracts = pos.get('contracts', 0)

        # Staleness protection: skip incomplete records
        if not ticker or not side:
            print(f"  SKIP: missing ticker/side in record")
            skipped += 1
            continue
        if not entry_price and entry_price != 0:
            print(f"  SKIP: {ticker} missing entry_price")
            skipped += 1
            continue

        # Fetch current market data
        market = get_market_data(ticker)
        if market is None:
            print(f"  SKIP: {ticker} API call failed")
            skipped += 1
            continue

        # Skip settled/finalized markets
        status = market.get('status', '')
        if status in ('finalized', 'settled'):
            print(f"  {ticker:38} SETTLED — skipping")
            checked += 1
            continue

        # Route to module-specific checker
        action = None
        reason = None
        cur_price = 0
        pos_contracts = 0
        pnl = 0

        try:
            if source in ('bot', 'crypto') or any(ticker.upper().startswith(p) for p in ('KXBTC', 'KXETH', 'KXXRP', 'KXSOL', 'KXDOGE')):
                action, reason, cur_price, pos_contracts, pnl = check_crypto_position(pos, market)
            else:
                # Unknown/unsupported source — skip
                print(f"  SKIP: {ticker} unsupported source '{source}'")
                skipped += 1
                continue
        except Exception as e:
            print(f"  ERROR: {ticker} check failed: {e}")
            skipped += 1
            continue

        checked += 1

        # Handle actions
        if action == 'auto_exit':
            if not acquire_exit_lock(ticker, side):
                print(f"  SKIP: {ticker} {side.upper()} exit already in progress (lock held)")
                skipped += 1
                continue
            try:
                print(f"  AUTO-EXIT: {ticker} {side.upper()} — {reason}")

                exit_opp = {
                    'ticker': ticker, 'title': pos.get('title', ticker),
                    'side': side, 'action': 'exit',
                    'market_prob': cur_price / 100, 'edge': None,
                    'size_dollars': round(pos_contracts * cur_price / 100, 2),
                    'contracts': pos_contracts, 'source': source,
                    'timestamp': ts(), 'date': str(date.today()),
                }

                # Compute realized P&L for pnl_cache
                ep = normalize_entry_price(pos)
                exit_pnl = round((cur_price - ep) * pos_contracts / 100, 2)
                exit_opp['pnl'] = exit_pnl  # ISSUE-030: add pnl field after computation (NameError-safe)
                exit_opp['edge'] = pos.get('edge')
                exit_opp['confidence'] = pos.get('confidence')

                if _dry_run:
                    log_trade(exit_opp, exit_opp['size_dollars'], pos_contracts, {'dry_run': True})
                    log_activity(f'[POST-MONITOR EXIT] {ticker} {side.upper()} @ {cur_price}c — {reason}')
                    print(f"    [DEMO] Exit logged")
                else:
                    from agents.ruppert.env_config import require_live_enabled
                    require_live_enabled()
                    try:
                        result = client.sell_position(ticker, side, cur_price, pos_contracts)
                        log_trade(exit_opp, exit_opp['size_dollars'], pos_contracts, result)
                        log_activity(f'[POST-MONITOR EXIT] {ticker} {side.upper()} @ {cur_price}c — {reason}')
                        print(f"    [LIVE] Exit executed")
                    except Exception as e:
                        print(f"    EXIT ERROR: {e}")
                        continue

                log_event('EXIT_TRIGGERED', {
                    'ticker': ticker,
                    'side': side,
                    'rule': reason,
                    'pnl': exit_pnl,
                    'price': cur_price,
                    'contracts': pos_contracts,
                })
                push_alert('exit', f'POST-MONITOR EXIT: {ticker} {side.upper()} — {reason}', ticker=ticker, pnl=pnl)
                exits_executed += 1
            finally:
                release_exit_lock(ticker, side)

        elif action == 'alert':
            print(f"  ALERT: {ticker} {side.upper()} — {reason}")
            push_alert('warning', f'POST-MONITOR: {ticker} {side.upper()} — {reason}', ticker=ticker, pnl=pnl)
            alerts_queued += 1

        elif action == 'alert_against':
            print(f"  WARNING: {ticker} {side.upper()} — {reason}")
            push_alert('warning', f'POST-MONITOR WARNING: {ticker} {side.upper()} — {reason}', ticker=ticker, pnl=pnl)
            alerts_queued += 1

        elif action == 'alert_profit':
            print(f"  PROFIT ALERT: {ticker} {side.upper()} — {reason}")
            push_alert('warning', f'POST-MONITOR: {ticker} {side.upper()} — {reason}', ticker=ticker, pnl=pnl)
            alerts_queued += 1

        elif action == 'warn_near_close':
            print(f"  NEAR-CLOSE: {ticker} {side.upper()} — {reason}")
            # No alert for near-close — just log
        else:
            print(f"  OK: {ticker:38} {side.upper()} cur={cur_price}c P&L=${pnl:+.2f}")

    # Summary
    print(f"\n{'─'*60}")
    summary = f"Position Monitor: {checked} checked, {exits_executed} exits executed, {alerts_queued} alerts queued"
    if skipped > 0:
        summary += f", {skipped} skipped"
    print(f"  {summary}")

    # Only push summary alert if something happened
    if exits_executed > 0 or alerts_queued > 0:
        push_alert('warning', summary)

    print(f"\nMonitor done. {ts()}")


if __name__ == '__main__':
    run_monitor()
