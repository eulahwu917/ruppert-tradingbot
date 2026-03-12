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


def get_computed_capital():
    """
    Compute true available capital from first principles:
      deposits (logs/demo_deposits.jsonl) + realized closed P&L (all logs/trades_*.jsonl exit records).

    This is the source-of-truth capital figure for demo mode.
    Do NOT use client.get_balance() for capital sizing — it returns a stale Kalshi API value.
    """
    import glob

    # ── Sum all deposits ──────────────────────────────────────────────────────
    deposits_path = os.path.join(LOG_DIR, 'demo_deposits.jsonl')
    total_deposits = 0.0
    if os.path.exists(deposits_path):
        try:  # W2: wrap file open in try/except
            with open(deposits_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        total_deposits += float(record.get('amount', 0.0))
                    except Exception:
                        pass
        except Exception as _e:
            import sys as _sys
            print(f"[WARNING] get_computed_capital: failed to read deposits file: {_e}", file=_sys.stderr)

    # W1: Floor — if no deposits found (file missing or empty/unreadable), fall back
    # to $400 baseline to prevent zero-capital lockout of check_daily_cap().
    if total_deposits == 0.0:
        import sys as _sys
        print(
            "[WARNING] get_computed_capital: deposits file missing or empty — "
            "using $400.00 floor to prevent zero-capital lockout.",
            file=_sys.stderr,
        )
        total_deposits = 400.0

    # ── Closed P&L: prefer dashboard cache (includes naturally settled losses) ──
    # Dashboard /api/pnl calls Kalshi API for settled positions and writes pnl_cache.json.
    # This is more accurate than summing exit records, which miss naturally settled losses.
    pnl_cache_path = os.path.join(LOG_DIR, 'pnl_cache.json')
    total_realized_pnl = None
    if os.path.exists(pnl_cache_path):
        try:
            with open(pnl_cache_path, 'r', encoding='utf-8') as f:
                cache = json.load(f)
                total_realized_pnl = float(cache.get('closed_pnl', 0.0))
        except Exception as _e:
            import sys as _sys
            print(f"[WARNING] get_computed_capital: pnl_cache.json unreadable, falling back to exit records: {_e}", file=_sys.stderr)

    # Fallback: sum exit records if cache not available
    if total_realized_pnl is None:
        total_realized_pnl = 0.0
        trade_log_pattern = os.path.join(LOG_DIR, 'trades_*.jsonl')
        for log_path in sorted(glob.glob(trade_log_pattern)):
            try:
                with open(log_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            record = json.loads(line)
                            if record.get('action') == 'exit':
                                pnl = record.get('realized_pnl')
                                if pnl is not None:
                                    total_realized_pnl += float(pnl)
                        except Exception:
                            pass
            except Exception as _e:
                import sys as _sys
                print(f"[WARNING] get_computed_capital: failed to read trade log {log_path}: {_e}", file=_sys.stderr)

    return round(total_deposits + total_realized_pnl, 2)


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
