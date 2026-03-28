"""
Ruppert Daily Progress Report
Reads last 24h of cycle logs and trade logs, generates a summary, sends via Telegram.

Standalone: python daily_progress_report.py

Windows Task Scheduler Setup (8pm PDT daily):
  1. Open Task Scheduler → Create Basic Task
  2. Name: "Ruppert Daily Report"
  3. Trigger: Daily, Start time 20:00 (PDT = UTC-7 during DST, UTC-8 standard)
     - If your system clock is UTC, set to 03:00 UTC (DST) or 04:00 UTC (standard)
  4. Action: Start a Program
     - Program: C:\\Users\\David Wu\\AppData\\Local\\Programs\\Python\\Python312\\python.exe
       (adjust to your Python path)
     - Arguments: daily_progress_report.py
     - Start in: C:\\Users\\David Wu\\.openclaw\\workspace\\ruppert-tradingbot-demo
  5. Enable "Run whether user is logged on or not"

Author: Ruppert (AI Trading Analyst)
Created: 2026-03-26
"""
import json
import sys
import os
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from agents.data_scientist.capital import get_capital

sys.stdout.reconfigure(encoding='utf-8')

BASE_DIR = Path(__file__).parent
LOGS_DIR = BASE_DIR / 'logs'
CYCLE_LOG = LOGS_DIR / 'cycle_log.jsonl'


def _load_jsonl(path: Path, since: datetime | None = None) -> list:
    """Load JSONL file, optionally filtering to entries after `since`."""
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
            if since:
                ts_str = rec.get('ts') or rec.get('timestamp', '')
                if ts_str:
                    try:
                        rec_time = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                        if rec_time.tzinfo is None:
                            rec_time = rec_time.replace(tzinfo=None)
                            if since.tzinfo:
                                since_naive = since.replace(tzinfo=None)
                            else:
                                since_naive = since
                            if rec_time < since_naive:
                                continue
                        elif rec_time < since:
                            continue
                    except Exception:
                        pass
            records.append(rec)
        except json.JSONDecodeError:
            pass
    return records


def _load_trades_last_24h() -> list:
    """Load all trades from the last 24 hours (today + yesterday log files)."""
    today_str = date.today().isoformat()
    yesterday_str = (date.today() - timedelta(days=1)).isoformat()

    trades = []
    for day_str in [yesterday_str, today_str]:
        log_path = LOGS_DIR / f'trades_{day_str}.jsonl'
        if log_path.exists():
            for line in log_path.read_text(encoding='utf-8').splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    trades.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

    # Filter to last 24h
    cutoff = datetime.now() - timedelta(hours=24)
    recent = []
    for t in trades:
        ts_str = t.get('timestamp', '')
        if ts_str:
            try:
                rec_time = datetime.fromisoformat(ts_str)
                if rec_time < cutoff:
                    continue
            except Exception:
                pass
        recent.append(t)
    return recent


def _load_all_trades() -> list:
    """Load all trades from all log files (for all-time P&L)."""
    all_trades = []
    for log_path in sorted(LOGS_DIR.glob('trades_*.jsonl')):
        for line in log_path.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                all_trades.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return all_trades


def _compute_pnl(trades: list) -> tuple[float, int, int]:
    """
    Compute approximate P&L, wins, losses from trade records.
    A 'buy'/'open' is a cost; settled contracts pay $1/contract if won.
    Since we don't have settlement data, estimate from exit records.
    Returns (pnl, wins, losses).
    """
    total_cost = 0.0
    total_exit = 0.0
    wins = 0
    losses = 0

    for t in trades:
        action = t.get('action', 'buy')
        size = float(t.get('size_dollars', 0) or 0)
        realized = t.get('realized_pnl')

        if action in ('buy', 'open'):
            total_cost += size
        elif action in ('exit', 'settle'):
            total_exit += size
            if realized is not None:
                if float(realized) >= 0:
                    wins += 1
                else:
                    losses += 1
            elif size > 0:
                wins += 1

    pnl = round(total_exit - total_cost, 2)
    return pnl, wins, losses


def _module_stats(trades: list, module: str) -> dict:
    """Compute per-module stats: wins, losses, avg edge."""
    module_trades = [t for t in trades if t.get('source') == module]
    if not module_trades:
        return {'wins': 0, 'losses': 0, 'avg_edge': 0.0, 'count': 0}

    entries = [t for t in module_trades if t.get('action', 'buy') in ('buy', 'open')]
    exits = [t for t in module_trades if t.get('action') == 'exit']

    wins = 0
    losses_count = 0
    for t in exits:
        rpnl = t.get('realized_pnl')
        if rpnl is not None:
            if float(rpnl) >= 0:
                wins += 1
            else:
                losses_count += 1

    edges = [float(t.get('edge', 0) or 0) for t in entries if t.get('edge')]
    avg_edge = round(sum(edges) / len(edges) * 100, 1) if edges else 0.0

    return {
        'wins': wins,
        'losses': losses_count,
        'avg_edge': avg_edge,
        'count': len(entries),
    }


def generate_report() -> str:
    """Generate the daily progress report string."""
    now = datetime.now()

    # Last 24h trades
    recent_trades = _load_trades_last_24h()
    pnl_24h, wins_24h, losses_24h = _compute_pnl(recent_trades)

    # All-time trades
    all_trades = _load_all_trades()
    pnl_all, wins_all, losses_all = _compute_pnl(all_trades)

    # Per-module stats (last 24h)
    modules = ['weather', 'crypto', 'geo', 'fed', 'econ']
    module_lines = []
    for mod in modules:
        stats = _module_stats(recent_trades, mod)
        label = mod.capitalize().ljust(8)
        w = stats['wins']
        l = stats['losses']
        avg_e = stats['avg_edge']

        # Mode indicator for geo/econ
        extra = ''
        if mod == 'geo':
            try:
                import config
                extra = ' [AUTO]' if config.GEO_AUTO_TRADE else ' [SCANNING]'
            except Exception:
                pass
        elif mod == 'econ':
            try:
                import config
                extra = ' [AUTO]' if config.ECON_AUTO_TRADE else ' [SCANNING]'
            except Exception:
                pass

        module_lines.append(f"  {label}: {w}W/{l}L, avg edge {avg_e}%{extra}")

    # Cycle log: last cycle info
    last_cycle_ts = 'unknown'
    cutoff_24h = now - timedelta(hours=24)
    cycle_records = _load_jsonl(CYCLE_LOG, since=cutoff_24h)
    done_records = [r for r in cycle_records if r.get('event') == 'done']
    if done_records:
        last_cycle_ts = done_records[-1].get('ts', 'unknown')

    # Estimate next cycle (6h interval from last)
    next_cycle_est = 'unknown'
    if last_cycle_ts != 'unknown':
        try:
            last_dt = datetime.fromisoformat(last_cycle_ts)
            next_dt = last_dt + timedelta(hours=6)
            next_cycle_est = next_dt.strftime('%Y-%m-%d %H:%M')
        except Exception:
            pass

    # Open positions: count today's buys minus exits
    today_log = LOGS_DIR / f'trades_{date.today().isoformat()}.jsonl'
    open_count = 0
    deployed_dollars = 0.0
    if today_log.exists():
        tickers_entered = {}
        for line in today_log.read_text(encoding='utf-8').splitlines():
            try:
                rec = json.loads(line.strip())
                ticker = rec.get('ticker', '')
                action = rec.get('action', 'buy')
                if action in ('buy', 'open'):
                    tickers_entered[ticker] = float(rec.get('size_dollars', 0) or 0)
                elif action in ('exit', 'settle') and ticker in tickers_entered:
                    del tickers_entered[ticker]
            except Exception:
                pass
        open_count = len(tickers_entered)
        deployed_dollars = round(sum(tickers_entered.values()), 2)

    # Format
    date_str = now.strftime('%Y-%m-%d')
    report = (
        f"\U0001f4cb Ruppert Daily Progress \u2014 {date_str}\n\n"
        f"DEMO P&L (last 24h): ${pnl_24h:+.2f} ({wins_24h}W / {losses_24h}L)\n"
        f"DEMO P&L (all time): ${pnl_all:+.2f}\n\n"
        f"MODULE SUMMARY:\n"
    )
    report += '\n'.join(module_lines)
    report += (
        f"\n\nSYSTEM STATUS:\n"
        f"  Last cycle: {last_cycle_ts}\n"
        f"  Next cycle: {next_cycle_est}\n"
        f"  Open positions: {open_count} (${deployed_dollars:.2f} deployed)"
    )

    return report


def main():
    report = generate_report()
    print(report)
    print()

    # Send via Telegram
    sys.path.insert(0, str(BASE_DIR))
    from agents.data_scientist.logger import send_telegram

    ok = send_telegram(report)
    if ok:
        print('[OK] Daily progress report sent via Telegram.')
    else:
        print('[WARN] Failed to send Telegram — report printed above.')


if __name__ == '__main__':
    main()
