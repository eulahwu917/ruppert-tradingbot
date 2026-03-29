"""
daily_progress_report.py — DEPRECATED (Phase 5 replacement).

This script has been superseded by agents/ceo/brief_generator.py
as part of the Agent Ownership Architecture refactor (Phase 5).

This shim delegates to the new CEO brief generator for backward compatibility
with any existing Task Scheduler entries.

Windows Task Scheduler: Update the action to run brief_generator directly:
  Program: C:\\Users\\David Wu\\AppData\\Local\\Programs\\Python\\Python312\\python.exe
  Arguments: -m agents.ruppert.ceo.brief_generator
  Start in: C:\\Users\\David Wu\\.openclaw\\workspace\\projects\\ruppert-tradingbot-demo

Schedule: Daily at 8:00 PM PDT (03:00 UTC during DST, 04:00 UTC standard)

Author: Ruppert (AI Trading Analyst)
Superseded: 2026-03-28 (Phase 5 Agent Ownership Architecture)
"""

import sys
from pathlib import Path

# Ensure project root on sys.path
BASE_DIR = Path(__file__).parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

sys.stdout.reconfigure(encoding='utf-8')


def main():
    print("[daily_progress_report] This script has been superseded by agents/ceo/brief_generator.py")
    print("[daily_progress_report] Delegating to CEO brief generator...")
    print()

    try:
        from agents.ruppert.ceo.brief_generator import main as run_brief
        result = run_brief()
        print(f"[daily_progress_report] CEO brief completed: {result}")
    except Exception as e:
        print(f"[daily_progress_report] ERROR: CEO brief generator failed: {e}")
        print("[daily_progress_report] Falling back to legacy report generation...")
        _run_legacy_report()


def _run_legacy_report():
    """
    Minimal fallback in case the new CEO brief generator fails.
    Prints a basic summary from truth files.
    """
    import json
    from datetime import date, datetime

    today_str = date.today().isoformat()
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    truth_dir = BASE_DIR / 'logs' / 'truth'
    trades_dir = BASE_DIR / 'logs' / 'trades'

    # Read P&L
    pnl = 0.0
    pnl_file = truth_dir / 'pnl_cache.json'
    if pnl_file.exists():
        try:
            pnl = json.loads(pnl_file.read_text(encoding='utf-8')).get('closed_pnl', 0.0)
        except Exception:
            pass

    # Count today's trades
    trade_count = 0
    trades_file = trades_dir / f'trades_{today_str}.jsonl'
    if trades_file.exists():
        trade_count = sum(1 for line in trades_file.read_text(encoding='utf-8').splitlines() if line.strip())

    report = (
        f"📋 Ruppert Daily Report (Legacy Fallback) — {today_str}\n\n"
        f"Generated: {now_str}\n\n"
        f"Closed P&L (truth file): ${pnl:+.2f}\n"
        f"Trades logged today: {trade_count}\n\n"
        f"⚠️ This is a fallback report. Check agents/ceo/brief_generator.py for errors."
    )

    print(report)

    try:
        from agents.ruppert.data_scientist.logger import send_telegram
        send_telegram(report)
    except Exception as e:
        print(f"[Fallback] Telegram send failed: {e}")


if __name__ == '__main__':
    main()
