"""
Trade Logger
Logs all bot activity, trades, and outcomes to files.
"""
import glob
import json
import os
import uuid
from datetime import datetime, date, timedelta

LOG_DIR = os.path.join(os.path.dirname(__file__), 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Log rotation — called once per cycle from ruppert_cycle.py
# ---------------------------------------------------------------------------

LOG_RETENTION_DAYS = 90  # keep 90 days of trade + activity logs

def rotate_logs(retention_days: int = LOG_RETENTION_DAYS) -> int:
    """
    Delete trade and activity log files older than retention_days.
    Returns count of files deleted.

    Safe: only removes files matching trades_YYYY-MM-DD.jsonl and
    activity_YYYY-MM-DD.log patterns — never touches other files.
    """
    cutoff = date.today() - timedelta(days=retention_days)
    patterns = [
        os.path.join(LOG_DIR, 'trades_*.jsonl'),
        os.path.join(LOG_DIR, 'activity_*.log'),
    ]
    deleted = 0
    for pattern in patterns:
        for path in glob.glob(pattern):
            fname = os.path.basename(path)
            # Extract date portion: trades_YYYY-MM-DD.jsonl → YYYY-MM-DD
            try:
                date_str = fname.split('_', 1)[1].rsplit('.', 1)[0]
                file_date = date.fromisoformat(date_str)
                if file_date < cutoff:
                    os.remove(path)
                    deleted += 1
            except Exception:
                pass  # skip files that don't match expected date format
    if deleted:
        print(f"[Logger] Rotated {deleted} log file(s) older than {retention_days} days")
    return deleted


def _today_log_path():
    return os.path.join(LOG_DIR, f"trades_{date.today().isoformat()}.jsonl")

def _activity_log_path():
    return os.path.join(LOG_DIR, f"activity_{date.today().isoformat()}.log")


def build_trade_entry(opportunity, size, contracts, order_result):
    """Build a standardized trade entry dict with all required fields.

    Enforces schema consistency for every trade written to JSONL logs.
    Adds a unique trade_id (uuid4) and ensures source, module, action,
    timestamp, and date are always present.
    """
    # Infer module from source and ticker if not explicitly set
    source = opportunity.get('source', 'bot')
    module = opportunity.get('module', '')
    if not module:
        ticker_upper = (opportunity.get('ticker') or '').upper()
        if source in ('weather',) or (source == 'bot' and ticker_upper.startswith('KXHIGH')):
            module = 'weather'
        elif source == 'crypto' or (source == 'bot' and any(
            ticker_upper.startswith(p) for p in ('KXBTC', 'KXETH', 'KXXRP', 'KXSOL', 'KXDOGE')
        )):
            module = 'crypto'
        elif source == 'fed' or ticker_upper.startswith('KXFED'):
            module = 'fed'
        elif source == 'econ' or ticker_upper.startswith('KXCPI'):
            module = 'econ'
        elif source == 'geo':
            module = 'geo'
        elif source == 'manual':
            module = 'manual'
        else:
            # P2-3 fix: avoid setting module = 'bot' (not a valid module in MIN_CONFIDENCE).
            # For 'bot' source, infer from ticker prefix; otherwise default to 'other'.
            if source == 'bot':
                module = 'weather' if ticker_upper.startswith('KXHIGH') else 'other'
            else:
                module = source  # fallback: use source as module (e.g. 'unknown')

    return {
        'trade_id':     str(uuid.uuid4()),
        'timestamp':    opportunity.get('timestamp') or datetime.now().isoformat(),
        'date':         opportunity.get('date') or date.today().isoformat(),
        'ticker':       opportunity['ticker'],
        'title':        opportunity.get('title', opportunity['ticker']),
        'side':         opportunity['side'],
        'action':       opportunity.get('action', 'buy'),
        'source':       source,
        'module':       module,
        'noaa_prob':    opportunity.get('noaa_prob'),
        'market_prob':  opportunity.get('market_prob'),
        'edge':         opportunity.get('edge'),
        'confidence':   opportunity.get('confidence') if opportunity.get('confidence') is not None
                        else abs(opportunity.get('edge') or 0),
        'size_dollars': size,
        'contracts':    contracts,
        'order_result': order_result,
    }


def log_trade(opportunity, size, contracts, order_result):
    """Log a placed trade to today's trade log."""
    entry = build_trade_entry(opportunity, size, contracts, order_result)
    with open(_today_log_path(), 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry) + '\n')
    print(f"[Log] Trade logged: {entry['trade_id'][:8]}.. {entry['ticker']} {entry['side'].upper()} ${size:.2f}")


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
    """Calculate total $ exposure from today's open positions.

    Also reads yesterday's log to catch multi-day positions that were entered
    yesterday but not yet exited. Only counts entries (buys) that have no
    corresponding exit across both log files.
    """
    today_str     = date.today().isoformat()
    yesterday_str = (date.today() - timedelta(days=1)).isoformat()

    entries   = {}   # key: (ticker, side) → size_dollars of the latest entry
    exit_keys = set()

    for day_str in [yesterday_str, today_str]:
        log_path = os.path.join(LOG_DIR, f"trades_{day_str}.jsonl")
        if not os.path.exists(log_path):
            continue
        with open(log_path, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    ticker = entry.get('ticker', '')
                    side   = entry.get('side', '')
                    action = entry.get('action', 'buy')
                    key    = (ticker, side)
                    if action == 'exit':
                        exit_keys.add(key)
                    else:
                        entries[key] = entry.get('size_dollars', 0)
                except:
                    pass

    # Sum positions that have an entry but no corresponding exit
    return sum(size for key, size in entries.items() if key not in exit_keys)


def normalize_entry_price(pos: dict) -> float:
    """Return entry_price in cents from a position record.

    Falls back to market_prob if entry_price is missing. Handles
    probability-formatted values (0–1) by converting to cents.
    Uses the NO-side convention: market_prob represents YES probability,
    so NO entry cost = (1 - market_prob) * 100.
    """
    side        = pos.get('side', 'no')
    entry_price = pos.get('entry_price') or pos.get('market_prob', 0.5) * 100
    if side == 'no':
        entry_price = entry_price if isinstance(entry_price, (int, float)) else 50
        # Normalize: if value looks like a probability (0–1), convert to cents
        if 0 < entry_price < 1:
            entry_price = round((1 - entry_price) * 100)
    return entry_price


def acquire_exit_lock(ticker: str, side: str) -> bool:
    """Create a file-based lock for exit operations on (ticker, side).

    Returns True if the lock was acquired, False if another process already
    holds it. Lock files older than 5 minutes are treated as stale and
    automatically removed so a crashed process can't block exits forever.
    """
    import time
    lock_path = os.path.join(LOG_DIR, f'.exit_lock_{ticker}_{side}')
    if os.path.exists(lock_path):
        try:
            age = time.time() - os.path.getmtime(lock_path)
            if age < 300:   # 5 minutes
                return False
            os.remove(lock_path)  # stale lock — remove and re-acquire
        except Exception:
            return False
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
        return True
    except FileExistsError:
        return False


def release_exit_lock(ticker: str, side: str) -> None:
    """Remove the exit lock file for (ticker, side). Safe to call even if absent."""
    lock_path = os.path.join(LOG_DIR, f'.exit_lock_{ticker}_{side}')
    try:
        os.remove(lock_path)
    except Exception:
        pass


def classify_module(src: str, ticker: str) -> str:
    """Classify a trade into a module bucket based on source and ticker prefix.

    Single source of truth — imported by dashboard/api.py to stay in sync.
    """
    t = (ticker or '').upper()
    if src in ('weather',) or (src in ('weather', 'bot') and t.startswith('KXHIGH')):
        return 'weather'
    if src == 'crypto' or (src in ('crypto', 'bot') and any(
        t.startswith(p) for p in ('KXBTC', 'KXETH', 'KXXRP', 'KXSOL', 'KXDOGE')
    )):
        return 'crypto'
    if src == 'fed' or t.startswith('KXFED'):
        return 'fed'
    if src == 'econ' or t.startswith('KXCPI'):
        return 'econ'
    if src == 'geo' or any(t.startswith(p) for p in (
        'KXUKRAINE', 'KXRUSSIA', 'KXISRAEL', 'KXIRAN', 'KXTAIWAN',
        'KXNATO', 'KXCHINA', 'KXNKOREA', 'KXCEASEFIRE',
    )):
        return 'geo'
    if src == 'manual':
        return 'manual'
    return 'other'


def get_computed_capital():
    """
    Backward-compatible wrapper — delegates to capital.get_capital().

    Kept so existing code that imports get_computed_capital() still works.
    New code should import from capital.py directly.
    """
    from capital import get_capital
    return get_capital()


def send_telegram(message: str) -> bool:
    """Send a message directly to David via Telegram Bot API."""
    import urllib.request, urllib.parse
    import config as _config
    try:
        config_path = os.path.join(os.path.dirname(__file__), '..', '..', 'openclaw.json')
        config_path = os.path.normpath(config_path)
        with open(config_path, 'r', encoding='utf-8') as f:
            import json as _json
            cfg = _json.load(f)
        bot_token = cfg['channels']['telegram']['botToken']
        chat_id = _config.TELEGRAM_CHAT_ID
        url = f'https://api.telegram.org/bot{bot_token}/sendMessage'
        data = urllib.parse.urlencode({'chat_id': chat_id, 'text': message}).encode()
        req = urllib.request.Request(url, data=data)
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception as e:
        print(f"[WARN] send_telegram failed: {e}")
        return False


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
