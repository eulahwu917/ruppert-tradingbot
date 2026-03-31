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
LOGS = _get_paths()['logs']
LOGS.mkdir(exist_ok=True)
LOGS_DIR = LOGS  # alias used by settlement checker
TRADES_DIR = _get_paths()['trades']
TRADES_DIR.mkdir(parents=True, exist_ok=True)

import config
from scripts.event_logger import log_event
# DRY_RUN intentionally not captured at module level — read at call time inside run_monitor()

from agents.ruppert.data_analyst.kalshi_client import KalshiClient
from agents.ruppert.data_scientist.logger import log_trade, log_activity, acquire_exit_lock, release_exit_lock, normalize_entry_price
from agents.ruppert.trader import position_tracker

def ts():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _update_circuit_breaker_state(module: str, window_open_ts: str, settlements: list):
    """
    Classify the just-settled window as complete loss, win, or partial loss,
    then update the circuit breaker state file.

    Called after each 15m window's positions are fully settled.

    Args:
        module:          Module name (e.g. 'crypto_15m')
        window_open_ts:  ISO timestamp of the window that just settled
        settlements:     List of settlement result dicts for this window.
                         Each dict must have at minimum: {'payout': float}
                         where payout = 0.0 for a loss, >0 for a win.
    """
    if not settlements:
        return  # No settlements to classify — don't update state

    # Use absolute path via _get_paths() to avoid working-directory ambiguity.
    state_path = os.path.join(str(_get_paths()['logs']), 'crypto_15m_circuit_breaker.json')

    # Classify the window
    payouts = [float(s.get('payout', 0.0)) for s in settlements]
    if all(p == 0.0 for p in payouts):
        window_result = 'loss'        # complete loss — all entries expired worthless
    elif any(p > 0.0 for p in payouts):
        window_result = 'win'         # at least one winner
    else:
        window_result = 'partial_loss'  # shouldn't reach here given above logic

    # Read current state (or initialize)
    import pytz as _pytz
    pdt = _pytz.timezone('America/Los_Angeles')
    today_str = datetime.now(pdt).strftime('%Y-%m-%d')
    try:
        with open(state_path, 'r', encoding='utf-8') as f:
            state = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        state = {'consecutive_losses': 0, 'advisory_would_have_fired_count': 0}
    state['date'] = today_str

    # Update consecutive loss counter
    if window_result == 'loss':
        state['consecutive_losses'] = state.get('consecutive_losses', 0) + 1
    else:
        # Any non-complete-loss resets the counter
        state['consecutive_losses'] = 0

    # Track advisory fire count for calibration
    cb_n = getattr(config, 'CRYPTO_15M_CIRCUIT_BREAKER_N', 3)
    if state['consecutive_losses'] >= cb_n:
        state['advisory_would_have_fired_count'] = state.get('advisory_would_have_fired_count', 0) + 1
        print(
            f'  [circuit_breaker] Advisory: {state["consecutive_losses"]} consecutive complete-loss '
            f'windows for {module} (threshold={cb_n}). '
            f'advisory_would_have_fired_count={state["advisory_would_have_fired_count"]}'
        )

    state['last_updated']       = datetime.utcnow().isoformat()
    state['last_window_ts']     = window_open_ts
    state['last_window_result'] = window_result

    # Atomic write via .tmp + os.replace
    os.makedirs(os.path.dirname(state_path), exist_ok=True)
    tmp_path = state_path + '.tmp'
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2)
        os.replace(tmp_path, state_path)
    except Exception as e:
        print(f'  [circuit_breaker] State file write failed: {e}')
        return

    print(
        f'  [circuit_breaker] Window {window_open_ts} result={window_result}, '
        f'consecutive_losses={state["consecutive_losses"]}'
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
    entries_by_key = {}
    exit_keys = set()
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
                exit_keys.add(key)
                if action == 'settle':
                    settle_keys.add(key)
            else:
                entries_by_key[key] = rec

    # Sync tracker: remove any positions that already have settle records
    # (handles cases where tracker cleanup was missed on prior runs)
    for (s_ticker, s_side) in settle_keys:
        position_tracker.remove_position(s_ticker, s_side)

    open_positions = [rec for key, rec in entries_by_key.items() if key not in exit_keys]

    if not open_positions:
        print(f"  [Settlement Checker] no open positions to check")
        return

    settled_count = 0
    # Accumulate 15m settlements per window for circuit breaker update
    # dict: window_open_ts → list of {'payout': float}
    _15m_window_settlements: dict = {}
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

        # Fetch market from Kalshi
        try:
            market = client.get_market(ticker)
        except Exception as e:
            print(f"  [Settlement Checker] API error for {ticker}: {e}")
            continue

        if not market:
            continue

        # Determine if market is resolved
        result = market.get('result', '')
        status = market.get('status', '')
        yes_bid = market.get('yes_bid', 50)

        if result in ('yes', 'no'):
            pass  # resolved via result field
        elif status == 'finalized':
            # Infer result from yes_bid
            result = 'yes' if yes_bid >= 99 else 'no'
        elif yes_bid >= 99:
            result = 'yes'
        elif yes_bid <= 1:
            result = 'no'
        else:
            # Not yet resolved — skip silently
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
                exit_price = 99
                pnl = (99 - entry_price) * contracts / 100
            else:  # result == 'no'
                exit_price = 1
                pnl = -(entry_price * contracts / 100)
        else:  # side == 'no'
            if result == 'no':
                exit_price = 99
                pnl = (99 - entry_price) * contracts / 100
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
            "noaa_prob": None,
            "market_prob": None,
            "scan_contracts": None,
            "fill_contracts": contracts,
            "scan_price": entry_price,
            "fill_price": exit_price,
            "order_result": {"dry_run": True, "status": "settled"},
        }
        try:
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(settle_record) + '\n')
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

        # Accumulate 15m crypto settlements by window for circuit breaker update
        if pos.get('module') == 'crypto_15m':
            win_ts = pos.get('window_open_ts', '')
            if win_ts:
                payout = exit_price if (
                    (side == 'yes' and result == 'yes') or
                    (side == 'no'  and result == 'no')
                ) else 0.0
                _15m_window_settlements.setdefault(win_ts, []).append({'payout': payout})

    if settled_count == 0:
        print(f"  [Settlement Checker] no newly settled positions")
    else:
        print(f"  [Settlement Checker] settled {settled_count} position(s)")

    # Update circuit breaker state for each fully-settled 15m window
    for win_ts, win_settlements in _15m_window_settlements.items():
        try:
            _update_circuit_breaker_state('crypto_15m', win_ts, win_settlements)
        except Exception as _cb_err:
            print(f"  [circuit_breaker] State update failed for window {win_ts}: {_cb_err}")


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
    entries_by_key = {}
    exit_keys = set()

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
                exit_keys.add(key)
            else:
                entries_by_key[key] = rec

    # Return only positions that haven't been exited
    return [rec for key, rec in entries_by_key.items() if key not in exit_keys]


def get_market_data(ticker):
    """Fetch current market data from Kalshi API. Returns dict or None."""
    try:
        _client = KalshiClient()
        result = _client.get_market(ticker)
        return result if result else None
    except Exception:
        return None


def check_weather_position(pos, market):
    """Check weather exit conditions. Returns (action, reason) or (None, None)."""
    side = pos.get('side', 'no')
    entry_price = normalize_entry_price(pos)

    no_ask = market.get('no_ask') or 50
    yes_ask = market.get('yes_ask') or 50
    cur_price = no_ask if side == 'no' else yes_ask
    contracts = pos.get('contracts', 0)
    pnl = round((cur_price - entry_price) * contracts / 100, 2) if entry_price else 0

    # 95c rule: guaranteed profit lock
    if side == 'no' and no_ask >= 95:
        return 'auto_exit', f'95c rule: no_ask={no_ask}c P&L=${pnl:+.2f}', cur_price, contracts, pnl
    if side == 'yes' and yes_ask >= 95:
        return 'auto_exit', f'95c rule: yes_ask={yes_ask}c P&L=${pnl:+.2f}', cur_price, contracts, pnl

    # 70% gain rule
    if entry_price and entry_price < 100:
        gain_pct = (cur_price - entry_price) / (100 - entry_price) if (100 - entry_price) > 0 else 0
        if gain_pct >= 0.70:
            return 'auto_exit', f'70% gain: {gain_pct:.0%} gain P&L=${pnl:+.2f}', cur_price, contracts, pnl

    # Ensemble prob flip check (weather-specific)
    try:
        from agents.ruppert.data_analyst.openmeteo_client import get_full_weather_signal
        from agents.ruppert.strategist.edge_detector import parse_date_from_ticker, parse_threshold_from_ticker

        ticker = pos.get('ticker', '')
        if 'KXHIGH' in ticker:
            series_ticker = ticker.split('-')[0].upper()
            threshold_f = parse_threshold_from_ticker(ticker)
            target_date = parse_date_from_ticker(ticker)
            if threshold_f is None:
                print(f'  WARN: {ticker}: parse_threshold_from_ticker returned None — skipping ensemble check')
            else:
                sig = get_full_weather_signal(series_ticker, threshold_f, target_date)
                ens_prob = sig.get('final_prob', 0.5) or 0.5
                if side == 'no' and ens_prob > 0.80:
                    return 'alert', f'ensemble {ens_prob:.0%} against NO position P&L=${pnl:+.2f}', cur_price, contracts, pnl
    except Exception:
        pass

    return None, None, cur_price, contracts, pnl


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

    # 70% gain rule
    if entry_price and entry_price < 100:
        gain_pct = (cur_price - entry_price) / (100 - entry_price) if (100 - entry_price) > 0 else 0
        if gain_pct >= 0.70:
            return 'auto_exit', f'70% gain: {gain_pct:.0%} gain P&L=${pnl:+.2f}', cur_price, contracts, pnl

    return None, None, cur_price, contracts, pnl


def check_alert_only_position(pos, market):
    """Check econ/geo/fed exit conditions — alert only, no auto-exit."""
    side = pos.get('side', 'no')
    entry_price = pos.get('entry_price') or pos.get('market_prob', 0.5) * 100
    if isinstance(entry_price, float) and 0 < entry_price < 1:
        entry_price = round((1 - entry_price) * 100) if side == 'no' else round(entry_price * 100)

    no_ask = market.get('no_ask') or 50
    yes_ask = market.get('yes_ask') or 50
    cur_price = no_ask if side == 'no' else yes_ask
    contracts = pos.get('contracts', 0)
    pnl = round((cur_price - entry_price) * contracts / 100, 2) if entry_price else 0

    # Price moved > 15c against entry direction
    if entry_price and (entry_price - cur_price) > 15:
        return 'alert_against', f'price moved {entry_price - cur_price:.0f}c against entry P&L=${pnl:+.2f}', cur_price, contracts, pnl

    # Gain > 50% from entry — consider taking profit
    if entry_price and entry_price < 100:
        gain_pct = (cur_price - entry_price) / (100 - entry_price) if (100 - entry_price) > 0 else 0
        if gain_pct >= 0.50:
            return 'alert_profit', f'50%+ gain ({gain_pct:.0%}) — consider taking profit P&L=${pnl:+.2f}', cur_price, contracts, pnl

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
            if source in ('weather', 'bot') or 'KXHIGH' in ticker:
                action, reason, cur_price, pos_contracts, pnl = check_weather_position(pos, market)
            elif source == 'crypto' or any(ticker.upper().startswith(p) for p in ('KXBTC', 'KXETH', 'KXXRP', 'KXSOL', 'KXDOGE')):
                action, reason, cur_price, pos_contracts, pnl = check_crypto_position(pos, market)
            elif source in ('econ', 'geo', 'fed'):
                action, reason, cur_price, pos_contracts, pnl = check_alert_only_position(pos, market)
            else:
                # Unknown module — run basic alert-only check
                action, reason, cur_price, pos_contracts, pnl = check_alert_only_position(pos, market)
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
                    'market_prob': cur_price / 100, 'noaa_prob': None, 'edge': None,
                    'size_dollars': round(pos_contracts * cur_price / 100, 2),
                    'contracts': pos_contracts, 'source': source,
                    'timestamp': ts(), 'date': str(date.today()),
                }

                # Compute realized P&L for pnl_cache
                ep = normalize_entry_price(pos)
                exit_pnl = round((cur_price - ep) * pos_contracts / 100, 2)

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
