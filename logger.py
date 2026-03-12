"""
Trade Logger
Logs all bot activity, trades, and outcomes to files.
"""
import json
import os
from datetime import datetime, date

LOG_DIR = os.path.join(os.path.dirname(__file__), 'logs')
os.makedirs(LOG_DIR, exist_ok=True)


def _today_log_path():
    return os.path.join(LOG_DIR, f"trades_{date.today().isoformat()}.jsonl")

def _activity_log_path():
    return os.path.join(LOG_DIR, f"activity_{date.today().isoformat()}.log")


def log_trade(opportunity, size, contracts, order_result):
    """Log a placed trade to today's trade log."""
    entry = {
        'timestamp':    datetime.now().isoformat(),
        'date':         date.today().isoformat(),
        'ticker':       opportunity['ticker'],
        'title':        opportunity['title'],
        'side':         opportunity['side'],
        'action':       opportunity.get('action', 'buy'),
        'source':       opportunity.get('source', 'bot'),
        'noaa_prob':    opportunity.get('noaa_prob'),
        'market_prob':  opportunity.get('market_prob'),
        'edge':         opportunity.get('edge'),
        'size_dollars': size,
        'contracts':    contracts,
        'order_result': order_result,
    }
    with open(_today_log_path(), 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry) + '\n')
    print(f"[Log] Trade logged: {opportunity['ticker']} {opportunity['side'].upper()} ${size:.2f}")


def log_opportunity(opportunity):
    """Log a detected opportunity (even if not traded)."""
    entry = {
        'timestamp': datetime.now().isoformat(),
        'type': 'opportunity',
        'ticker': opportunity['ticker'],
        'edge': opportunity['edge'],
        'action': opportunity['action'],
    }
    with open(_activity_log_path(), 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry) + '\n')


def log_activity(message):
    """Log general bot activity."""
    entry = f"[{datetime.now().strftime('%H:%M:%S')}] {message}"
    print(entry)
    with open(_activity_log_path(), 'a', encoding='utf-8') as f:
        f.write(entry + '\n')


def get_daily_exposure():
    """Calculate total $ exposure from today's trades."""
    log_path = _today_log_path()
    if not os.path.exists(log_path):
        return 0.0

    total = 0.0
    with open(log_path, 'r', encoding='utf-8') as f:
        for line in f:
            try:
                entry = json.loads(line)
                total += entry.get('size_dollars', 0)
            except:
                pass
    return total


def get_daily_summary():
    """Return a summary of today's trading activity."""
    log_path = _today_log_path()
    if not os.path.exists(log_path):
        return {'trades': 0, 'total_exposure': 0.0}

    trades = []
    with open(log_path, 'r', encoding='utf-8') as f:
        for line in f:
            try:
                trades.append(json.loads(line))
            except:
                pass

    return {
        'date': date.today().isoformat(),
        'trades': len(trades),
        'total_exposure': sum(t.get('size_dollars', 0) for t in trades),
        'markets': [t['ticker'] for t in trades],
    }
