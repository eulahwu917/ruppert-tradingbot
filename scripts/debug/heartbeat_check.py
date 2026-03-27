"""
Heartbeat check — called by Task Scheduler once daily.
Reads today's cycle and trade logs and sends a Telegram summary.
"""
import json
import os
from datetime import date, datetime

LOG_DIR = os.path.join(os.path.dirname(__file__), 'logs')


def _count_cycles_today():
    today = date.today().isoformat()
    cycle_log = os.path.join(LOG_DIR, 'cycle_log.jsonl')
    count = 0
    with open(cycle_log, 'r', encoding='utf-8') as f:
        for line in f:
            try:
                entry = json.loads(line)
                if entry.get('ts', '').startswith(today) and entry.get('event') == 'done':
                    count += 1
            except Exception:
                pass
    return count


def _count_trades_today():
    trade_log = os.path.join(LOG_DIR, f"trades_{date.today().isoformat()}.jsonl")
    if not os.path.exists(trade_log):
        return 0
    count = 0
    with open(trade_log, 'r', encoding='utf-8') as f:
        for line in f:
            try:
                json.loads(line)
                count += 1
            except Exception:
                pass
    return count


def main():
    from logger import send_telegram
    import config

    try:
        cycles = _count_cycles_today()
        trades = _count_trades_today()
        mode = 'LIVE' if not config.DRY_RUN else 'DEMO'
        now = datetime.now().strftime('%H:%M')
        msg = (
            f'Ruppert heartbeat \u2705\n'
            f'Cycles today: {cycles}\n'
            f'Trades today: {trades}\n'
            f'Mode: {mode}\n'
            f'Time: {now} PDT'
        )
    except Exception as e:
        msg = f'Ruppert heartbeat \u2705 \u2014 log read error, bot may need attention\n({e})'

    send_telegram(msg)


if __name__ == '__main__':
    main()
