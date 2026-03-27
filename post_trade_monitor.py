"""
Post-Trade Position Monitor
Unified post-entry position watcher for ALL modules.
Checks exit conditions based on module type, executes auto-exits or queues alerts.
Runs every 30 minutes via Task Scheduler (6am-11pm).

Usage: python post_trade_monitor.py
"""
import sys
import json
import requests
from pathlib import Path
from datetime import date, datetime, timezone

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

LOGS = Path(__file__).parent / 'logs'
LOGS.mkdir(exist_ok=True)
ALERTS_FILE = LOGS / 'pending_alerts.json'
BASE = "https://api.elections.kalshi.com/trade-api/v2/markets"

import config
DRY_RUN = getattr(config, 'DRY_RUN', True)

from kalshi_client import KalshiClient
from logger import log_trade, log_activity

def ts():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def push_alert(level, message, ticker=None, pnl=None):
    """Write alert for heartbeat to pick up and forward."""
    alerts = []
    if ALERTS_FILE.exists():
        try: alerts = json.loads(ALERTS_FILE.read_text(encoding='utf-8'))
        except: pass
    alerts.append({
        'level': level, 'message': message,
        'ticker': ticker, 'pnl': pnl,
        'timestamp': ts(),
    })
    ALERTS_FILE.write_text(json.dumps(alerts, indent=2), encoding='utf-8')


def load_open_positions():
    """Load open positions from trade logs, filtering out exits.

    Reads today's log AND yesterday's log so multi-day positions entered
    yesterday are not missed. Today's entries/exits take precedence.
    """
    from datetime import timedelta
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    today = date.today().isoformat()

    logs_to_check = [
        LOGS / f"trades_{yesterday}.jsonl",
        LOGS / f"trades_{today}.jsonl",
    ]

    entries_by_ticker = {}
    exit_tickers = set()

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
            action = rec.get('action', 'buy')
            if action == 'exit':
                exit_tickers.add(ticker)
            else:
                entries_by_ticker[ticker] = rec

    # Return only positions that haven't been exited
    return [rec for ticker, rec in entries_by_ticker.items() if ticker not in exit_tickers]


def get_market_data(ticker):
    """Fetch current market data from Kalshi API. Returns dict or None."""
    try:
        r = requests.get(f'{BASE}/{ticker}', timeout=5)
        if r.status_code != 200:
            return None
        return r.json().get('market', {})
    except Exception:
        return None


def check_weather_position(pos, market):
    """Check weather exit conditions. Returns (action, reason) or (None, None)."""
    side = pos.get('side', 'no')
    entry_price = pos.get('entry_price') or pos.get('market_prob', 0.5) * 100
    if side == 'no':
        entry_price = entry_price if isinstance(entry_price, (int, float)) else 50
        # Normalize: if entry_price looks like a probability (0-1), convert to cents
        if 0 < entry_price < 1:
            entry_price = round((1 - entry_price) * 100)

    no_ask = market.get('no_ask') or 50
    yes_ask = market.get('yes_ask') or 50
    cur_price = no_ask if side == 'no' else yes_ask
    contracts = pos.get('contracts', 0)
    pnl = round((cur_price - entry_price) * contracts / 100, 2) if entry_price else 0

    # 95c rule: guaranteed profit lock
    if side == 'no' and no_ask >= 95:
        return 'auto_exit', f'95c rule: no_ask={no_ask}c P&L=${pnl:+.2f}', cur_price, contracts, pnl

    # 70% gain rule
    if entry_price and entry_price < 100:
        gain_pct = (cur_price - entry_price) / (100 - entry_price) if (100 - entry_price) > 0 else 0
        if gain_pct >= 0.70:
            return 'auto_exit', f'70% gain: {gain_pct:.0%} gain P&L=${pnl:+.2f}', cur_price, contracts, pnl

    # Ensemble prob flip check (weather-specific)
    try:
        from openmeteo_client import get_full_weather_signal
        from edge_detector import parse_date_from_ticker, parse_threshold_from_ticker

        ticker = pos.get('ticker', '')
        if 'KXHIGH' in ticker:
            series_ticker = ticker.split('-')[0].upper()
            threshold_f = parse_threshold_from_ticker(ticker)
            target_date = parse_date_from_ticker(ticker)
            if threshold_f is not None:
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
    entry_price = pos.get('entry_price') or pos.get('market_prob', 0.5) * 100
    if isinstance(entry_price, float) and 0 < entry_price < 1:
        entry_price = round((1 - entry_price) * 100) if side == 'no' else round(entry_price * 100)

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
    print(f"\n{'='*60}")
    print(f"  POST-TRADE MONITOR  {ts()}")
    print(f"{'='*60}")

    positions = load_open_positions()
    if not positions:
        print("  No open positions today.")
        print(f"\nMonitor done. {ts()}")
        return

    print(f"  {len(positions)} open position(s) to check\n")

    client = KalshiClient()
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
            print(f"  AUTO-EXIT: {ticker} {side.upper()} — {reason}")

            exit_opp = {
                'ticker': ticker, 'title': pos.get('title', ticker),
                'side': side, 'action': 'exit',
                'market_prob': cur_price / 100, 'noaa_prob': None, 'edge': None,
                'size_dollars': round(pos_contracts * cur_price / 100, 2),
                'contracts': pos_contracts, 'source': source,
                'timestamp': ts(), 'date': str(date.today()),
            }

            if DRY_RUN:
                log_trade(exit_opp, exit_opp['size_dollars'], pos_contracts, {'dry_run': True})
                log_activity(f'[POST-MONITOR EXIT] {ticker} {side.upper()} @ {cur_price}c — {reason}')
                print(f"    [DEMO] Exit logged")
            else:
                try:
                    result = client.sell_position(ticker, side, cur_price, pos_contracts)
                    log_trade(exit_opp, exit_opp['size_dollars'], pos_contracts, result)
                    log_activity(f'[POST-MONITOR EXIT] {ticker} {side.upper()} @ {cur_price}c — {reason}')
                    print(f"    [LIVE] Exit executed")
                except Exception as e:
                    print(f"    EXIT ERROR: {e}")
                    continue

            push_alert('exit', f'POST-MONITOR EXIT: {ticker} {side.upper()} — {reason}', ticker=ticker, pnl=pnl)
            exits_executed += 1

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
