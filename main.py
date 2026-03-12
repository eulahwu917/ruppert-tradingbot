"""
Ruppert Kalshi Trading Bot — Full System
Modules: Weather, Economics, Gaming Scout, Geopolitical

Usage:
  python main.py --test         # Test API connection
  python main.py                # Run all modules once (dry run)
  python main.py --live         # Run with real trades (demo account)
  python main.py --loop         # Run continuously every 6 hours
  python main.py --weather      # Weather module only
  python main.py --econ         # Economics module only
  python main.py --scout        # Gaming/tech scout only
  python main.py --geo          # Geopolitical scanner only
"""
import os
import sys
import json
import time
import schedule
from datetime import datetime

from kalshi_client import KalshiClient
from edge_detector import find_opportunities
from trader import Trader
from logger import log_activity, get_daily_summary, get_daily_exposure, get_computed_capital
from economics_scanner import find_econ_opportunities
from gaming_scout import run_daily_scout, format_scout_brief
from geopolitical_scanner import run_geo_scan, format_geo_brief
from best_bets_scanner import find_best_bets
import config
from bot.strategy import (
    should_enter, should_add, should_exit,
    check_daily_cap, calculate_position_size,
    get_strategy_summary,
)


# ─── STRATEGY HELPERS ────────────────────────────────────────────────────────

_STRATEGY_EXITS_LOG = os.path.join(os.path.dirname(__file__), 'logs', 'strategy_exits.jsonl')
_LOGS_DIR = os.path.join(os.path.dirname(__file__), 'logs')


def _load_trade_record(ticker: str) -> dict | None:
    """
    Search all logs/trades_*.jsonl files and return the most recent trade
    record matching `ticker`, or None if not found.
    Records are returned sorted by timestamp descending (most recent first).
    """
    import glob
    pattern = os.path.join(_LOGS_DIR, 'trades_*.jsonl')
    files = sorted(glob.glob(pattern), reverse=True)  # newest file first

    best = None
    for fpath in files:
        try:
            with open(fpath, encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if record.get('ticker') == ticker:
                        # Keep the most recent by timestamp string (ISO sort)
                        if best is None or record.get('timestamp', '') > best.get('timestamp', ''):
                            best = record
        except OSError:
            continue
    return best


def _opp_to_signal(opp: dict, module: str = 'weather') -> dict:
    """Convert an edge_detector opportunity dict into a strategy signal dict."""
    target_date_str = opp.get('target_date', datetime.now().strftime('%Y-%m-%d'))
    try:
        target_dt = datetime.strptime(target_date_str, '%Y-%m-%d').replace(hour=23, minute=59)
        hours_to_settlement = max(0.0, (target_dt - datetime.now()).total_seconds() / 3600)
    except Exception:
        hours_to_settlement = 24.0  # safe fallback
    return {
        'edge':                opp.get('edge', 0.0),
        'win_prob':            opp.get('win_prob', 0.0),
        'confidence':          opp.get('confidence', 0.0),
        'hours_to_settlement': round(hours_to_settlement, 2),
        'module':              module,
        'vol_ratio':           1.0,
    }


def run_exit_scan(dry_run=True):
    """
    Check all open bot positions for exit signals and log to strategy_exits.jsonl.
    Applies: 95¢ rule, 70% gain rule, near-settlement hold, reversal stop.

    Entry metadata (entry_price, entry_edge) is loaded from logs/trades_*.jsonl
    by matching ticker. Falls back to conservative defaults if no record found.
    The 95¢ rule, 70% gain rule, and near-settlement hold fire on live bids.
    Reversal rule fires using real entry edge vs current bid-derived edge.
    """
    log_activity("[ExitScan] Checking open positions for exit signals...")
    os.makedirs(os.path.dirname(_STRATEGY_EXITS_LOG), exist_ok=True)

    try:
        client = KalshiClient()
        positions = client.get_positions()
        if not positions:
            log_activity("[ExitScan] No open positions.")
            return

        log_activity(f"[ExitScan] {len(positions)} open position(s) found.")
        exits_logged = 0

        for pos in positions:
            ticker = getattr(pos, 'ticker', None)
            if not ticker:
                continue

            # Only scan bot-managed markets (weather: KXHIGH*, crypto: KXBTC*/KXETH*)
            series = ticker.split('-')[0].upper()
            if series.startswith('KXHIGH'):
                module = 'weather'
            elif any(series.startswith(p) for p in ('KXBTC', 'KXETH', 'KXCRYPTO')):
                module = 'crypto'
            else:
                continue  # Skip non-bot positions

            # Fetch live market bid
            try:
                market = client.get_market(ticker)
                yes_bid = getattr(market, 'yes_bid', 0) or 0
                no_bid  = getattr(market, 'no_bid',  0) or 0
            except Exception as e:
                log_activity(f"  [ExitScan] Could not fetch market {ticker}: {e}")
                continue

            position_count = getattr(pos, 'position', 0) or 0
            if position_count > 0:
                current_bid = yes_bid
            elif position_count < 0:
                current_bid = no_bid
            else:
                continue  # Flat position

            # Derive hours_to_settlement from ticker date component
            try:
                date_part = ticker.split('-')[1]          # e.g. "26MAR11"
                target_dt = datetime.strptime("20" + date_part, "%Y%b%d").replace(hour=23, minute=59)
                hours_to_settlement = max(0.0, (target_dt - datetime.now()).total_seconds() / 3600)
            except Exception:
                hours_to_settlement = 24.0

            # ── Load entry metadata from trade log ───────────────────────────
            trade_record = _load_trade_record(ticker)
            if trade_record:
                market_prob = trade_record.get('market_prob', 0.5) or 0.5
                trade_side  = trade_record.get('side', 'yes')
                if trade_side == 'no':
                    entry_price = (1.0 - market_prob) * 100
                else:
                    entry_price = market_prob * 100
                entry_edge = trade_record.get('edge', 0.0) or 0.0
            else:
                # Fallback: no record found; 95¢ rule and near-settlement hold
                # still fire correctly; reversal will be conservative.
                entry_price = 50
                entry_edge  = 0.0
                log_activity(f"  [ExitScan] No trade record found for {ticker}; using defaults.")

            # Approximate current edge from live bid vs entry price
            current_edge = abs(current_bid / 100.0 - (1.0 - entry_price / 100.0))

            entry_signal = {
                'edge': entry_edge, 'win_prob': 0.5, 'confidence': 0.5,
                'hours_to_settlement': hours_to_settlement, 'module': module,
            }
            current_signal = {
                'edge': current_edge, 'win_prob': 0.5, 'confidence': 0.5,
                'hours_to_settlement': hours_to_settlement, 'module': module,
            }

            decision = should_exit(
                current_bid=current_bid,
                entry_price=entry_price,
                signal=current_signal,
                entry_signal=entry_signal,
                hours_to_settlement=hours_to_settlement,
                module=module,
            )

            if decision['exit']:
                log_entry = {
                    'timestamp':          datetime.now().isoformat(),
                    'ticker':             ticker,
                    'module':             module,
                    'reason':             decision['reason'],
                    'fraction':           decision['fraction'],
                    'current_bid':        current_bid,
                    'position_count':     position_count,
                    'hours_to_settlement': round(hours_to_settlement, 2),
                    'dry_run':            dry_run,
                }
                with open(_STRATEGY_EXITS_LOG, 'a', encoding='utf-8') as f:
                    f.write(json.dumps(log_entry) + '\n')
                log_activity(
                    f"  [ExitScan] EXIT SIGNAL: {ticker} | reason={decision['reason']} "
                    f"fraction={decision['fraction']:.0%} bid={current_bid}¢"
                )
                # TODO: live mode - execute sell via trader.py
                exits_logged += 1
            else:
                log_activity(f"  [ExitScan] HOLD: {ticker} | {decision['reason']}")

        log_activity(f"[ExitScan] Done. {exits_logged} exit signal(s) logged.")

    except Exception as e:
        log_activity(f"[ExitScan] ERROR: {e}")
        import traceback
        traceback.print_exc()


def test_connection():
    """Test Kalshi API connection and show available markets."""
    print("\n=== Testing Kalshi Connection ===")
    client = KalshiClient()
    print(f"Environment: {config.get_environment().upper()}")
    balance = client.get_balance()
    print(f"Balance: ${balance:.2f}")
    print("\nSearching for weather markets...")
    markets = client.search_markets('temperature')
    print(f"Found {len(markets)} weather markets:")
    for m in markets[:5]:
        yes_ask = m.get('yes_ask', '?')
        print(f"  [{m.get('ticker')}] {m.get('title')} | YES: {yes_ask}c")
    print("\n[OK] Connection test complete!")


# ─── WEATHER MODULE ───────────────────────────────────────────────────────────

def run_weather_scan(dry_run=True):
    """Run weather market scan and execute trades."""
    log_activity("[Weather] Starting scan...")
    try:
        client = KalshiClient()

        # ── Daily cap check ───────────────────────────────────────────────────
        # Use computed capital (deposits + realized P&L) — NOT client.get_balance()
        # which returns a stale Kalshi API demo balance.
        total_capital  = get_computed_capital()
        deployed_today = get_daily_exposure()
        cap_remaining  = check_daily_cap(total_capital, deployed_today)
        log_activity(
            f"[Weather] Capital: ${total_capital:.2f} | Deployed today: ${deployed_today:.2f} "
            f"| Remaining: ${cap_remaining:.2f}"
        )
        if cap_remaining <= 0:
            log_activity(
                f"[Weather] Daily cap reached (${deployed_today:.2f} deployed, "
                f"max ${total_capital * 0.70:.2f}). Skipping new entries this cycle."
            )
            return

        markets = client.search_markets('temperature')
        log_activity(f"[Weather] Fetched {len(markets)} markets")

        opportunities = find_opportunities(markets)
        log_activity(f"[Weather] Found {len(opportunities)} opportunities above {config.MIN_EDGE_THRESHOLD:.0%} threshold")

        for opp in opportunities:
            log_activity(f"  >> {opp['ticker']}: {opp['action']} | NOAA: {opp['noaa_prob']:.1%} vs Market: {opp['market_prob']:.1%} | Edge: {opp['edge']:+.1%}")

        # ── Strategy gate: filter opportunities through should_enter() ────────
        approved_opps = []
        for opp in opportunities:
            signal   = _opp_to_signal(opp, module='weather')
            decision = should_enter(signal, total_capital, deployed_today)
            if decision['enter']:
                # Pass strategy-computed size so Trader skips redundant risk.py sizing
                opp['strategy_size'] = decision['size']
                approved_opps.append(opp)
                # W14: refresh deployed_today so subsequent opportunities in this cycle
                # see the updated cap (prevents over-deployment if multiple trades fire)
                deployed_today += decision['size']
                log_activity(f"  [Strategy] ENTER {opp['ticker']}: {decision['reason']}")
            else:
                log_activity(f"  [Strategy] SKIP  {opp['ticker']}: {decision['reason']}")

        if approved_opps:
            trader = Trader(dry_run=dry_run)
            trader.execute_all(approved_opps)
        else:
            log_activity("[Weather] No opportunities approved by strategy layer.")

    except Exception as e:
        log_activity(f"[Weather] ERROR: {e}")
        import traceback
        traceback.print_exc()


# ─── ECONOMICS MODULE ─────────────────────────────────────────────────────────

def run_econ_scan(dry_run=True):
    """Run economics market scan."""
    log_activity("[Econ] Starting scan...")
    try:
        opportunities = find_econ_opportunities()
        log_activity(f"[Econ] Found {len(opportunities)} markets to review")
        for opp in opportunities[:5]:
            flag = " [REVIEW]" if opp.get('requires_human_review') else ""
            log_activity(f"  >> {opp['ticker']}: {opp['market_prob']:.0%} | {opp.get('note', '')}{flag}")
    except Exception as e:
        log_activity(f"[Econ] ERROR: {e}")


# ─── GAMING SCOUT MODULE ──────────────────────────────────────────────────────

def run_gaming_scout():
    """Run gaming/tech market scout."""
    log_activity("[Scout] Starting gaming/tech scout...")
    try:
        markets = run_daily_scout()
        brief = format_scout_brief(markets)
        log_activity(f"[Scout] Found {len(markets)} gaming/tech markets")
        # Print brief to console / log
        for line in brief.split('\n'):
            if line.strip():
                log_activity(f"  {line}")
    except Exception as e:
        log_activity(f"[Scout] ERROR: {e}")


# ─── GEOPOLITICAL MODULE ──────────────────────────────────────────────────────

def run_geo_scan_module():
    """Run geopolitical market scanner."""
    log_activity("[Geo] Starting geopolitical scan...")
    try:
        markets = run_geo_scan()
        brief = format_geo_brief(markets)
        log_activity(f"[Geo] Flagged {len(markets)} markets with news activity")
        for line in brief.split('\n'):
            if line.strip():
                log_activity(f"  {line}")
    except Exception as e:
        log_activity(f"[Geo] ERROR: {e}")


# ─── FULL SCAN ────────────────────────────────────────────────────────────────

def run_full_scan(dry_run=True):
    """Run all modules in sequence."""
    log_activity("=" * 60)
    log_activity(f"FULL SCAN — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log_activity(f"Mode: {'DRY RUN (simulated)' if dry_run else 'LIVE TRADING'}")
    log_activity("=" * 60)

    # ── Exit scan: check open positions before entering new ones ─────────────
    run_exit_scan(dry_run=dry_run)

    run_weather_scan(dry_run=dry_run)
    run_econ_scan(dry_run=dry_run)
    run_gaming_scout()
    run_geo_scan_module()

    summary = get_daily_summary()
    log_activity(f"\nDaily summary: {summary['trades']} trades | ${summary['total_exposure']:.2f} exposure")
    log_activity("=" * 60)


def run_loop(dry_run=True):
    """Run the full bot on a schedule."""
    interval = config.CHECK_INTERVAL_HOURS
    log_activity(f"Starting bot loop — scanning every {interval} hours")
    run_full_scan(dry_run=dry_run)
    schedule.every(interval).hours.do(run_full_scan, dry_run=dry_run)
    while True:
        schedule.run_pending()
        time.sleep(60)


# ─── ENTRY POINT ─────────────────────────────────────────────────────────────

if __name__ == '__main__':
    args = sys.argv[1:]

    # ── Log strategy summary at every startup ─────────────────────────────────
    _summary = get_strategy_summary()
    log_activity("[Strategy] Parameters in effect:")
    for _k, _v in _summary.items():
        log_activity(f"  {_k:<35} = {_v}")

    if '--test' in args:
        test_connection()
    elif '--weather' in args:
        run_weather_scan(dry_run='--live' not in args)
    elif '--econ' in args:
        run_econ_scan(dry_run='--live' not in args)
    elif '--scout' in args:
        run_gaming_scout()
    elif '--geo' in args:
        run_geo_scan_module()
    elif '--loop' in args:
        run_loop(dry_run='--live' not in args)
    else:
        run_full_scan(dry_run='--live' not in args)
