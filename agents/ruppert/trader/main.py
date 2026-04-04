"""
Ruppert Kalshi Trading Bot — Full System
Modules: Crypto (band, threshold, 15m direction, long-horizon)

NOTE: Crypto trading execution runs via ruppert_cycle.py.
main.py provides run_crypto_scan, run_crypto_1d_scan entry points.

Usage:
  python main.py --test         # Test API connection
  python main.py                # Run all modules once (dry run)
  python main.py --live         # Run with real trades (demo account)
  python main.py --loop         # Run continuously every 6 hours
"""
import os
import sys
import json
import time
import schedule
from pathlib import Path
from datetime import date, datetime

# Ensure project root is on sys.path when running standalone
# Resolve workspace root and add to path (agents.ruppert.* + config shim)
_AGENTS_ROOT = Path(__file__).parent.parent.parent  # workspace/agents
_WORKSPACE_ROOT = _AGENTS_ROOT.parent               # workspace/
if str(_WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE_ROOT))

from agents.ruppert.data_analyst.kalshi_client import KalshiClient
from agents.ruppert.data_scientist.logger import log_activity, log_trade, get_daily_summary, get_daily_exposure
from agents.ruppert.data_scientist.capital import get_capital, get_buying_power
_DEMO_ENV_ROOT = _WORKSPACE_ROOT / 'environments' / 'demo'
if str(_DEMO_ENV_ROOT) not in sys.path:
    sys.path.insert(0, str(_DEMO_ENV_ROOT))
import config
from agents.ruppert.strategist.strategy import get_strategy_summary


# ─── STRATEGY HELPERS ────────────────────────────────────────────────────────

def run_exit_scan(dry_run=True):
    """
    ARCHIVED: This function has been moved to archive/run_exit_scan_archived.py.
    Exits are owned exclusively by ws_feed.py (position_tracker) + post_trade_monitor.py.
    Do not call this function. It will raise in all modes.
    Archived: 2026-03-29 per CEO spec CEO-L3.
    """
    raise RuntimeError(
        "run_exit_scan() is archived. "
        "See archive/run_exit_scan_archived.py for historical reference. "
        "Exits are handled by ws_feed.py / post_trade_monitor.py."
    )


def test_connection():
    """Test Kalshi API connection."""
    print("\n=== Testing Kalshi Connection ===")
    client = KalshiClient()
    print(f"Environment: {config.get_environment().upper()}")
    balance = client.get_balance()
    print(f"Balance: ${balance:.2f}")
    print("\n[OK] Connection test complete!")


# ─── CRYPTO HELPERS ──────────────────────────────────────────────────────────
# Band logic (band_prob + run_crypto_scan) extracted to crypto_band_daily.py
from agents.ruppert.trader.crypto_band_daily import band_prob, run_crypto_scan


# ─── CRYPTO 1D MODULE ─────────────────────────────────────────────────────────

def run_crypto_1d_scan(dry_run=True, traded_tickers=None, open_position_value=0.0):
    """
    Run the daily crypto above/below scan (crypto_1d module).
    Evaluates BTC and ETH (Phase 1) for KXBTCD / KXETHD above/below entries.
    Entry windows: 09:30–11:30 ET (primary), 13:30–14:30 ET (secondary).
    Returns list of executed trade dicts.
    """
    if traded_tickers is None:
        traded_tickers = set()

    log_activity("[Crypto1D] Starting daily above/below scan...")
    executed = []

    try:
        from agents.ruppert.trader.crypto_threshold_daily import evaluate_crypto_1d_entry, ASSETS_PHASE1

        # Window time constants
        _NO_ENTRY_AFTER_ET        = '15:00'
        _PRIMARY_START_ET         = '09:30'
        _PRIMARY_END_ET           = '11:30'
        _SECONDARY_START_ET       = '13:30'
        _SECONDARY_END_ET         = '14:30'

        # Determine current window (Eastern Time)
        try:
            import pytz
            _now_et = datetime.now(pytz.timezone('America/New_York'))
        except ImportError:
            from zoneinfo import ZoneInfo
            _now_et = datetime.now(ZoneInfo('America/New_York'))

        _time_str = _now_et.strftime('%H:%M')

        # No-entry-after gate (check first)
        if _time_str >= _NO_ENTRY_AFTER_ET:
            log_activity(f"[Crypto1D] No-entry gate: {_time_str} ET >= {_NO_ENTRY_AFTER_ET} — skipping")
            return []

        if _PRIMARY_START_ET <= _time_str <= _PRIMARY_END_ET:
            window = 'primary'
        elif _SECONDARY_START_ET <= _time_str <= _SECONDARY_END_ET:
            window = 'secondary'
        else:
            log_activity(f"[Crypto1D] Outside entry windows (current ET: {_time_str}) — skipping")
            return []

        # Capital / daily cap check
        try:
            _capital = get_capital()
            # Sum deployed across per-asset threshold modules (formerly 'crypto_1h_dir')
            _1d_deployed = sum(
                get_daily_exposure(module=m)
                for m in ('crypto_threshold_daily_btc', 'crypto_threshold_daily_eth')
            )
            _1d_cap = _capital * config.CRYPTO_1D_DAILY_CAP_PCT
        except Exception as _ce:
            log_activity(f"[Crypto1D] get_daily_exposure() failed — skipping cycle: {_ce}")
            # Do not use 0.0 fallback — cap check would be invalid
            return []

        if _1d_deployed >= _1d_cap:
            log_activity(f"[Crypto1D] Daily cap reached (${_1d_deployed:.2f} / ${_1d_cap:.0f}) — skipping")
            return []

        # Evaluate each Phase 1 asset
        for asset in ASSETS_PHASE1:
            ticker_key = f'crypto_1d_{asset}'
            if ticker_key in traded_tickers:
                log_activity(f"[Crypto1D] {asset} already evaluated this cycle — skipping")
                continue

            result = evaluate_crypto_1d_entry(asset=asset, window=window)
            traded_tickers.add(ticker_key)

            if result.get('entered'):
                log_activity(
                    f"[Crypto1D] ENTERED {asset} {result.get('ticker')} "
                    f"${result.get('size_usd', 0):.2f} ({window} window)"
                )
                # Module name: crypto_threshold_daily_{asset} (formerly 'crypto_1h_dir')
                _1d_module = f'crypto_threshold_daily_{asset}'  # e.g. crypto_threshold_daily_btc
                executed.append({
                    'asset': asset,
                    'ticker': result.get('ticker'),
                    'size_dollars': result.get('size_usd', 0),
                    'module': _1d_module,
                    'window': window,
                })
            else:
                log_activity(f"[Crypto1D] SKIP {asset}: {result.get('reason', '?')}")

    except Exception as e:
        log_activity(f"[Crypto1D] ERROR: {e}")
        import traceback
        traceback.print_exc()

    log_activity(f"[Crypto1D] Scan complete — {len(executed)} trade(s) executed")
    return executed


# ─── FULL SCAN ────────────────────────────────────────────────────────────────

def run_full_scan(dry_run=True):
    """Run all modules in sequence."""
    log_activity("=" * 60)
    log_activity(f"FULL SCAN — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log_activity(f"Mode: {'DRY RUN (simulated)' if dry_run else 'LIVE TRADING'}")
    log_activity("=" * 60)

    run_crypto_scan(dry_run=dry_run)

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
    elif '--loop' in args:
        run_loop(dry_run='--live' not in args)
    else:
        run_full_scan(dry_run='--live' not in args)
