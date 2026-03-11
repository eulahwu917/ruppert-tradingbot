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
import sys
import time
import schedule
from datetime import datetime

from kalshi_client import KalshiClient
from edge_detector import find_opportunities
from trader import Trader
from logger import log_activity, get_daily_summary
from economics_scanner import find_econ_opportunities
from gaming_scout import run_daily_scout, format_scout_brief
from geopolitical_scanner import run_geo_scan, format_geo_brief
from best_bets_scanner import find_best_bets
import config


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
        markets = client.search_markets('temperature')
        log_activity(f"[Weather] Fetched {len(markets)} markets")

        opportunities = find_opportunities(markets)
        log_activity(f"[Weather] Found {len(opportunities)} opportunities above {config.MIN_EDGE_THRESHOLD:.0%} threshold")

        for opp in opportunities:
            log_activity(f"  >> {opp['ticker']}: {opp['action']} | NOAA: {opp['noaa_prob']:.1%} vs Market: {opp['market_prob']:.1%} | Edge: {opp['edge']:+.1%}")

        if opportunities:
            trader = Trader(dry_run=dry_run)
            trader.execute_all(opportunities)
        else:
            log_activity("[Weather] No actionable opportunities.")

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
