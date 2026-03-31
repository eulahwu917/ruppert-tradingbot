"""
Ruppert Dashboard API
FastAPI backend serving live bot data.
Run with: uvicorn dashboard.api:app --reload --port 8765
"""
import sys, os
_env_root = os.path.dirname(os.path.dirname(__file__))
_workspace_root = os.path.dirname(os.path.dirname(_env_root))
sys.path.insert(0, _env_root)
if _workspace_root not in sys.path:
    sys.path.insert(1, _workspace_root)

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
import json
import time
from datetime import date, datetime
from pathlib import Path
from agents.ruppert.data_scientist.capital import get_capital, get_buying_power
from agents.ruppert.data_scientist.logger import classify_module, get_parent_module
import agents.ruppert.data_analyst.market_cache as market_cache

app = FastAPI(title="Ruppert Trading Dashboard")
LOGS_DIR = Path(__file__).parent.parent / "logs"
MODE_FILE = Path(__file__).parent.parent / "mode.json"

_state_cache: dict = {"ts": 0.0, "data": None}
_pnl_cache: dict = {"ts": 0.0, "data": None}
_positions_cache: dict = {"ts": 0.0, "data": None}


def _cache_reload_loop() -> None:
    """Background daemon thread: reloads price_cache.json from disk every 60s."""
    import time as _time
    while True:
        _time.sleep(60)
        market_cache.load()


@app.on_event("startup")
async def startup_load_cache():
    import logging as _logging
    import threading
    market_cache.load()
    _logging.getLogger(__name__).info('[Dashboard] price_cache loaded at startup')
    t = threading.Thread(target=_cache_reload_loop, daemon=True, name="cache-reload")
    t.start()

def get_mode() -> str:
    """Returns 'demo' or 'live'."""
    try:
        if MODE_FILE.exists():
            return json.loads(MODE_FILE.read_text(encoding='utf-8')).get('mode', 'demo')
    except Exception:
        pass
    return 'demo'

# NOTE: set_mode() removed in Phase 4 — dashboard is read-only.
# Mode is config-driven (mode.json); changes go through the Dev pipeline.

# ─── Helpers ─────────────────────────────────────────────────────────────────

def read_today_trades():
    log_path = LOGS_DIR / "trades" / f"trades_{date.today().isoformat()}.jsonl"
    trades = []
    if log_path.exists():
        with open(log_path, encoding='utf-8') as f:
            for line in f:
                try: trades.append(json.loads(line))
                except: pass
    return trades


def read_all_trades():
    all_trades = []
    for path in sorted((LOGS_DIR / "trades").glob("trades_*.jsonl")):
        with open(path, encoding='utf-8') as f:
            for line in f:
                try:
                    t = json.loads(line)
                    t['_date'] = path.stem.replace('trades_', '')
                    all_trades.append(t)
                except: pass
    return all_trades


def read_geo_log():
    log_path = LOGS_DIR / "geopolitical_scanner.jsonl"
    entries = []
    if log_path.exists():
        with open(log_path, encoding='utf-8') as f:
            for line in f:
                try: entries.append(json.loads(line))
                except: pass
    today = str(date.today())
    return [e for e in entries if e.get('date') == today]


def read_crypto_15m_summary() -> dict:
    """Read today's 15m crypto window decisions from decisions_15m.jsonl.
    Returns a summary dict for the dashboard crypto_15m_summary section.
    """
    log_path = LOGS_DIR / "decisions_15m.jsonl"
    today_prefix = date.today().isoformat()  # e.g. "2026-03-28"

    if not log_path.exists():
        return {
            "today_evaluations": 0,
            "today_entries": 0,
            "today_skips_late": 0,
            "today_skips_other": 0,
            "last_entry": None,
            "avg_edge_on_entries": None,
            "last_evaluated_at": None,
        }

    entries = []
    with open(log_path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                ts_val = rec.get('ts', '')
                if str(ts_val).startswith(today_prefix):
                    entries.append(rec)
            except Exception:
                pass

    today_evaluations = len(entries)
    today_entries = 0
    today_skips_late = 0
    today_skips_other = 0
    last_entry = None
    edge_sum = 0.0
    last_evaluated_at = None

    for rec in entries:
        decision = rec.get('decision', '')
        ts_val = rec.get('ts')
        if ts_val and (last_evaluated_at is None or ts_val > last_evaluated_at):
            last_evaluated_at = ts_val

        if decision == 'ENTER':
            today_entries += 1
            edge_val = rec.get('edge')
            if edge_val is not None:
                edge_sum += float(edge_val)
            # Keep the most recent entry record
            if last_entry is None or (ts_val and ts_val > last_entry.get('ts', '')):
                last_entry = {
                    'market_id': rec.get('market_id', rec.get('ticker', '')),
                    'edge': round(float(rec.get('edge', 0)), 4) if rec.get('edge') is not None else None,
                    'entry_price': rec.get('entry_price', rec.get('price')),
                    'direction': rec.get('direction', rec.get('side', '')),
                    'ts': ts_val,
                }
        elif decision == 'SKIP_LATE' or rec.get('skip_reason') == 'LATE_WINDOW':
            today_skips_late += 1
        else:
            # Any non-ENTER, non-SKIP_LATE decision is "other skip"
            if decision and decision != 'ENTER':
                today_skips_other += 1

    avg_edge = round(edge_sum / today_entries, 4) if today_entries > 0 else None

    return {
        "today_evaluations": today_evaluations,
        "today_entries": today_entries,
        "today_skips_late": today_skips_late,
        "today_skips_other": today_skips_other,
        "last_entry": last_entry,
        "avg_edge_on_entries": avg_edge,
        "last_evaluated_at": last_evaluated_at,
    }


# classify_module imported from logger — single source of truth


# ─── Endpoints ────────────────────────────────────────────────────────────────




def settlement_date_from_ticker(ticker: str):
    """Parse settlement date from ticker, e.g. 26MAR10 -> date(2026,3,10).
    Also handles date+hour format, e.g. 26MAR1117 -> date(2026,3,11).
    Returns None if not found."""
    import re as _re
    months = {'JAN':1,'FEB':2,'MAR':3,'APR':4,'MAY':5,'JUN':6,
              'JUL':7,'AUG':8,'SEP':9,'OCT':10,'NOV':11,'DEC':12}
    for part in ticker.upper().split('-'):
        # Match 26MAR11 (date only) OR 26MAR1117 (date + 2-digit hour)
        m = _re.match(r'^(\d{2})([A-Z]{3})(\d{2})(\d{2})?$', part)
        if m:
            yy, mon, dd = m.group(1), m.group(2), m.group(3)
            mn = months.get(mon)
            if mn:
                try:
                    from datetime import date
                    return date(2000 + int(yy), mn, int(dd))
                except: pass
    return None

def _parse_15m_window_time(ticker: str):
    """Extract the EDT window close time from a 15M ticker and return the window OPEN time in PDT.

    Ticker format example: KXDOGE15M-26MAR301445-45
    Kalshi encodes the window CLOSE time in Eastern (EDT = UTC-4).
    We display the window OPEN time in PDT (= EDT - 3h, open = close - 15 min).

    Returns e.g. "11:30 PDT", or None if not a 15M ticker or parsing fails.

    QA samples:
        KXDOGE15M-26MAR301445-45  -> "11:30 PDT"  (close 14:45 EDT → open 14:30 EDT → 11:30 PDT)
        KXBTC15M-26MAR301300-00   -> "09:45 PDT"  (close 13:00 EDT → open 12:45 EDT → 09:45 PDT)
        KXBTC15M-26MAR300015-00   -> "20:00 PDT"  (close 00:15 EDT → open 00:00 EDT → 21:00 PDT prev day)
    """
    import re as _re
    if '15M' not in ticker.upper():
        return None
    for part in ticker.upper().split('-'):
        # Match date+time part like 26MAR301445 (yy=26, mon=MAR, dd=30, hhmm=1445)
        m = _re.match(r'^(\d{2})([A-Z]{3})(\d{2})(\d{4})$', part)
        if m:
            time_str = m.group(4)  # e.g. "1445"
            try:
                edt_close_h = int(time_str[:2])
                edt_close_m = int(time_str[2:])
                # Window open = close - 15 min; PDT = EDT - 3h
                open_edt_total = edt_close_h * 60 + edt_close_m - 15
                open_pdt_total = open_edt_total - 180  # EDT to PDT
                open_pdt_h = (open_pdt_total // 60) % 24
                open_pdt_m = open_pdt_total % 60
                return f"{open_pdt_h:02d}:{open_pdt_m:02d} PDT"
            except Exception:
                pass
    return None


def _translate_15m_side(ticker: str, side: str) -> str:
    """For 15M crypto direction contracts, translate yes/no to UP/DOWN."""
    if '15M' in (ticker or '').upper():
        if side == 'yes':
            return 'UP'
        if side == 'no':
            return 'DOWN'
    return side


from agents.ruppert.data_scientist.ticker_utils import is_settled_ticker  # noqa: F401

@app.get("/api/summary")
def get_summary():
    trades = read_all_trades()
    today  = read_today_trades()
    # Deduplicate to unique positions (excluding exit records and duplicate entries)
    exited_tickers = {t.get('ticker') for t in trades if t.get('action') == 'exit'}
    seen = set()
    unique_positions = 0
    for t in trades:
        ticker = t.get('ticker', '')
        if not ticker or ticker in seen or t.get('action') == 'exit':
            continue
        seen.add(ticker)
        unique_positions += 1
    return {
        # raw_entries = total JSONL lines (includes duplicates and exit records)
        # unique_positions = deduplicated open+closed positions (correct count)
        "raw_entries":       len(trades),
        "unique_positions":  unique_positions,
        "total_trades":      unique_positions,   # alias: matches /api/pnl definition
        "today_trades":      len(today),
        "total_exposure":    round(sum(t.get('size_dollars',0) for t in trades), 2),
        "today_exposure":    round(sum(t.get('size_dollars',0) for t in today), 2),
        "mode": get_mode().upper(), "status": "RUNNING",
    }


@app.get("/api/account")
def get_account():
    """Account summary.

    ── DEMO MODE (current) ───────────────────────────────────────────────────
    Starting capital is tracked locally — no Kalshi API call needed.
      Account Value  = STARTING_CAPITAL + Open P&L + Closed P&L   (frontend computes)
      Buying Power   = STARTING_CAPITAL − Deployed Capital in open trades
      Starting Capital = $10,000 fresh start 2026-03-26

    ── LIVE MODE (switch when David approves going live) ────────────────────
    Replace the STARTING_CAPITAL line below with a real Kalshi API call:
        from agents.ruppert.data_analyst.kalshi_client import KalshiClient
        balance_dollars = KalshiClient().get_balance()  # already returns dollars
    Then update frontend: remove open_pnl addition from Account Value formula —
    Kalshi balance already reflects open positions in live mode.
    ─────────────────────────────────────────────────────────────────────────
    """
    current_mode = get_mode()

    all_trades = read_all_trades()

    # Scale-in fix: aggregate size_dollars + contracts per ticker across all buy legs.
    # Clear accumulated entry when exit/settle encountered (position closed).
    entries = {}   # ticker -> aggregated record
    for t in all_trades:
        ticker = t.get('ticker', '')
        if not ticker:
            continue
        action = t.get('action', '')
        if action in ('exit', 'settle'):
            entries.pop(ticker, None)  # position closed; reset accumulator
        else:
            if ticker not in entries:
                entries[ticker] = dict(t)
            else:
                entries[ticker]['size_dollars'] = (
                    float(entries[ticker].get('size_dollars') or 0)
                    + float(t.get('size_dollars') or 0)
                )
                entries[ticker]['contracts'] = (
                    int(entries[ticker].get('contracts') or 0)
                    + int(t.get('contracts') or 0)
                )
    trades = list(entries.values())

    # Bot = weather + crypto (fully autonomous, Ruppert decides)
    # Manual = economics + geo (David approves)
    # Gaming removed entirely
    AUTO_SOURCES   = ('bot', 'weather', 'crypto')
    MANUAL_SOURCES = ('economics', 'geo', 'manual')

    # Only count OPEN (not-yet-settled) positions in deployed capital
    # A position is "open" only if it has no settle/exit record
    open_trades  = trades  # Already filtered to exclude closed positions above
    bot_cost     = sum(t.get('size_dollars',0) for t in open_trades if t.get('source','bot') in AUTO_SOURCES)
    manual_cost  = sum(t.get('size_dollars',0) for t in open_trades if t.get('source','bot') in MANUAL_SOURCES)
    total_deployed = bot_cost + manual_cost

    # Capital source: single source of truth via capital.py
    try:
        STARTING_CAPITAL = get_capital()
    except Exception:
        STARTING_CAPITAL = 10000.0  # Fresh start 2026-03-26
    buying_power = max(STARTING_CAPITAL - total_deployed, 0)

    return {
        "kalshi_balance":     STARTING_CAPITAL,  # alias kept so frontend formula is unchanged
        "buying_power":       round(buying_power, 2),
        "total_deployed":     round(total_deployed, 2),
        "starting_capital":   round(STARTING_CAPITAL, 2),
        "bot_trade_count":    len([t for t in trades if t.get('source','bot') in AUTO_SOURCES]),
        "manual_trade_count": len([t for t in trades if t.get('source','bot') in MANUAL_SOURCES]),
        "open_trade_count":   len(open_trades),
        "bot_deployed":       round(bot_cost, 2),
        "manual_deployed":    round(manual_cost, 2),
        "is_dry_run":         current_mode == 'demo',
        "mode":               current_mode,
    }


@app.get("/api/mode")
def get_mode_endpoint():
    # Mode is always 'demo' for the DEMO dashboard — determined by config, not UI toggle.
    return {"mode": "demo"}

@app.post("/api/mode")
async def set_mode_endpoint(request: Request):
    # This endpoint is intentionally a no-op on the DEMO dashboard.
    # Mode switching is no longer supported via the UI — use config/live_env.json + run_live_dashboard.py.
    return {"mode": "demo", "ok": True, "note": "Mode is config-driven. Toggle disabled."}

@app.get("/api/deposits")
def get_deposits():
    deposits_path = LOGS_DIR / "demo_deposits.jsonl"
    deposits = []
    total = 0.0
    if deposits_path.exists():
        with open(deposits_path, encoding='utf-8') as f:
            for line in f:
                try:
                    d = json.loads(line)
                    deposits.append(d)
                    total += d.get('amount', 0)
                except: pass
    return {"deposits": deposits, "total": round(total, 2)}


@app.post("/api/deposits")
async def add_deposit(request: Request):
    # Phase 4: dashboard is read-only. Log deposit request as event;
    # Data Scientist synthesizes it into deposits.json (truth file).
    from scripts.event_logger import log_event
    body = await request.json()
    amount = float(body.get('amount', 0))
    note   = str(body.get('note', 'Manual deposit'))
    if amount <= 0:
        return {"error": "Amount must be positive"}
    entry = {"date": date.today().isoformat(), "amount": round(amount, 2), "note": note}
    log_event('DEPOSIT_ADDED', entry, source='dashboard')
    return {"ok": True, "pending": True, "entry": entry,
            "note": "Deposit queued — Data Scientist will apply on next synthesis run."}


@app.get("/api/trades")
def get_trades():
    """Trade history — closed positions only (settled OR manually exited).
    Uses pnl field from settle/exit records directly — no API calls needed.
    """
    all_trades = read_all_trades()

    # Build settle/exit records index: (ticker, side) -> record with pnl
    close_records = {}
    for t in all_trades:
        action = t.get('action', '')
        if action in ('exit', 'settle'):
            ticker = t.get('ticker', '')
            side = t.get('side', '')
            if ticker:
                close_records[(ticker, side)] = t

    closed = []
    seen = set()
    for t in all_trades:
        ticker = t.get('ticker', '')
        if not ticker or ticker in seen: continue
        action = t.get('action', '')
        if action in ('exit', 'settle'): continue  # skip close records themselves
        seen.add(ticker)

        side = t.get('side', 'no')
        key = (ticker, side)

        # Only show in closed if we have a settle/exit record
        if key not in close_records:
            continue

        cr = close_records[key]
        pnl = cr.get('pnl')
        if pnl is not None:
            t['realized_pnl'] = round(float(pnl), 2)
        t['exit_price'] = cr.get('exit_price') or cr.get('fill_price')
        t['settlement_result'] = cr.get('settlement_result', '')
        t['exit_type'] = 'settle' if cr.get('action') == 'settle' else cr.get('exit_type', 'manual')

        _mod = classify_module(t.get('source', 'bot'), ticker)
        t['module'] = _mod
        t['parent_module'] = get_parent_module(_mod)

        # Apply 15M display title transformation (mirrors open positions path)
        raw_title = (t.get('title') or ticker).replace('**', '')
        _win_time = _parse_15m_window_time(ticker)
        if _win_time:
            import re as _re
            raw_title = _re.sub(r'\s+\d{4}-\d{2}-\d{2}\b', '', raw_title).strip()
            raw_title = f"{raw_title} {_win_time}"
        t['title'] = raw_title

        # Also apply side translation for 15M contracts (yes→UP, no→DOWN)
        t['side'] = _translate_15m_side(ticker, side)

        closed.append(t)
    # Exclude manual trades from the closed trades table display
    _MANUAL_EXCL = ('manual', 'economics', 'geo')
    closed = [t for t in closed if t.get('source', 'bot') not in _MANUAL_EXCL]
    return closed


@app.get("/api/trades/today")
def get_today_trades():
    return read_today_trades()


@app.get("/api/positions/active")
def get_active_positions():
    """
    All open positions.
    - LIVE mode: fetches real positions from Kalshi API (real fills show up there)
    - DEMO mode: reads from trade logs — dry_run trades are NOT real Kalshi positions
      so the Kalshi API returns nothing; trade logs are the source of truth.
    Deduplicates by ticker (first open/buy entry per ticker).
    Skips tickers that have a corresponding action=exit entry.
    """
    global _positions_cache
    if _positions_cache["data"] is not None and (time.time() - _positions_cache["ts"]) < 30:
        return _positions_cache["data"]

    current_mode = get_mode()

    if current_mode == 'live':
        # LIVE mode: get real positions from Kalshi API
        try:
            sys.path.insert(0, str(Path(__file__).parent.parent))
            from agents.ruppert.data_analyst.kalshi_client import KalshiClient
            kalshi_positions = KalshiClient().get_positions()
            positions = []
            total_cost = 0.0
            for kp in kalshi_positions:
                ticker = getattr(kp, 'ticker', '') or ''
                if not ticker or is_settled_ticker(ticker):
                    continue
                position = getattr(kp, 'position', 0) or 0  # net YES contracts
                if position == 0:
                    continue
                side = 'yes' if position > 0 else 'no'
                contracts = abs(position)
                # market_exposure in cents → dollars cost basis
                exposure_cents = abs(getattr(kp, 'market_exposure', 0) or 0)
                cost = round(exposure_cents / 100, 2)
                entry_p = round(exposure_cents / contracts) if contracts else 50
                total_cost += cost
                positions.append({
                    "ticker":      ticker,
                    "title":       ticker,
                    "side":        side,
                    "source":      'live',
                    "module":      classify_module('live', ticker),
                    "parent_module": get_parent_module(classify_module('live', ticker)),
                    "entry_price": entry_p,
                    "cur_price":   entry_p,
                    "pnl":         0.0,
                    "pnl_pct":     0.0,
                    "cost":        cost,
                    "contracts":   contracts,
                    "pos_ratio":   0,
                    "edge":        None,
                    "date":        '',
                    "close_time":  '',
                    "noaa_prob":   None,
                    "market_prob": None,
                })
            # Recompute pos_ratio with total_cost
            for p in positions:
                p['pos_ratio'] = round(p['cost'] / total_cost * 100) if total_cost else 0
            _positions_cache["ts"] = time.time()
            _positions_cache["data"] = positions
            return positions
        except Exception:
            pass  # Fall through to log-based approach if Kalshi API fails

    # DEMO mode (or LIVE fallback): read from trade logs
    # dry_run trades are NOT real Kalshi positions — trade logs are the source of truth
    all_trades = read_all_trades()

    # Build set of exited/settled tickers
    exited = {t.get('ticker') for t in all_trades if t.get('action') in ('exit', 'settle')}

    # Deduplicate: keep first (earliest) open/buy entry per ticker
    # Only collect entries where action is 'open' or 'buy' (not exit, add-on, update, etc.)
    seen = {}
    for t in all_trades:
        ticker = t.get('ticker','')
        if not ticker: continue
        if ticker in exited: continue
        if ticker in seen: continue  # already have opening entry
        action = (t.get('action') or '').lower()
        if action != 'open' and not action.startswith('buy'): continue  # only genuine open entries
        if is_settled_ticker(ticker): continue  # skip past-date markets
        seen[ticker] = t

    open_trades = list(seen.values())
    if not open_trades:
        return []

    total_cost = sum(t.get('size_dollars', 0) for t in open_trades)
    positions  = []
    for t in open_trades:
        ticker = t.get('ticker', '')
        raw_title = (t.get('title') or ticker).replace('**', '')
        # 15M entries: replace the date segment with a PDT time label for readability
        _win_time = _parse_15m_window_time(ticker)
        if _win_time:
            import re as _re2
            raw_title = _re2.sub(r'\s+\d{4}-\d{2}-\d{2}\b', '', raw_title).strip()
            raw_title = f"{raw_title} {_win_time}"
        title  = raw_title
        side   = t.get('side', 'no')
        source = t.get('source', 'bot')
        mp     = t.get('market_prob', 0.5) or 0.5
        ep     = int((1 - mp) * 100) if side == 'no' else int(mp * 100)
        cost   = t.get('size_dollars', 0)
        contracts = t.get('contracts', 0)
        pos_ratio = round(cost / total_cost * 100) if total_cost else 0
        edge      = t.get('edge')

        positions.append({
            "ticker":      ticker,
            "title":       title,
            "side":        _translate_15m_side(ticker, side),
            "source":      source,
            "module":        classify_module(source, ticker),
            "parent_module": get_parent_module(classify_module(source, ticker)),
            "entry_price": ep,
            "cur_price":   ep,
            "pnl":         0.0,
            "pnl_pct":     0.0,
            "cost":        round(cost, 2),
            "contracts":   contracts,
            "pos_ratio":   pos_ratio,
            "edge":        round(edge, 3) if edge else None,
            "date":        t.get('date') or t.get('_date', ''),
            "close_time":  t.get('close_time', ''),
            "noaa_prob":   t.get('noaa_prob'),
            "market_prob": t.get('market_prob'),
        })

    _positions_cache["ts"] = time.time()
    _positions_cache["data"] = positions
    return positions


@app.get("/api/positions/prices")
def get_live_prices():
    """Live prices for ALL open positions — served from price_cache only."""
    all_trades = read_all_trades()
    # Deduplicate — same logic as positions endpoint
    exited = {t.get('ticker') for t in all_trades if t.get('action') == 'exit'}
    seen = set()
    trades = []
    for t in all_trades:
        ticker = t.get('ticker','')
        if not ticker or ticker in exited or ticker in seen: continue
        if t.get('action') == 'exit': continue
        seen.add(ticker)
        trades.append(t)
    if not trades:
        return {}
    prices = {}
    for t in trades:
        ticker = t.get('ticker','')
        if not ticker or ticker in prices:
            continue
        bid, ask, is_stale = market_cache.get_with_staleness(ticker)
        _cached = market_cache.get_market_price(ticker, fallback_client=None)
        if _cached:
            entry = market_cache.get(ticker)
            updated_at = entry['updated_at'] if entry else None
            source = entry.get('source', 'websocket') if entry else 'websocket'
            prices[ticker] = {
                'yes_ask':    _cached['yes_ask'],
                'yes_bid':    _cached['yes_bid'],
                'no_ask':     _cached['no_ask'],
                'no_bid':     _cached['no_bid'],
                'source':     source,
                'updated_at': updated_at,
                'is_stale':   is_stale,
            }
        else:
            prices[ticker] = {
                'yes_ask':    None,
                'yes_bid':    None,
                'no_ask':     None,
                'no_bid':     None,
                'source':     None,
                'updated_at': None,
                'is_stale':   True,
            }
    return prices


@app.get("/api/positions/status")
def get_position_statuses():
    """Returns market status for each open position ticker — served from price_cache only."""
    trades = read_today_trades()
    if not trades:
        return {}
    statuses = {}
    seen = set()
    for t in trades:
        ticker = t.get('ticker', '')
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        try:
            # Check WS cache — if we have prices, market is likely open
            _cached = market_cache.get_market_price(ticker, fallback_client=None)
            if _cached and _cached.get('source') == 'ws_cache':
                statuses[ticker] = {
                    'status': 'open',
                    'result': '',
                    'last_price': _cached['yes_ask'],
                }
        except Exception:
            pass
    return statuses


@app.get("/api/kalshi/weather")
def get_weather_markets():
    """
    Weather markets — served from scanner cache for speed.
    Background scanner (ruppert_cycle.py) writes logs/weather_scan.jsonl.
    Fallback: stale indicator (no direct REST calls from dashboard).
    """
    # 1. Try cache first (written by background scanner)
    cache = LOGS_DIR / "weather_scan.jsonl"
    if cache.exists():
        from datetime import datetime, timezone
        age = (datetime.now(timezone.utc).timestamp() - cache.stat().st_mtime)
        if age < 14400:  # < 4 hours old
            markets = []
            for line in cache.read_text(encoding='utf-8').splitlines():
                try: markets.append(json.loads(line))
                except: pass
            if markets:
                return markets

    # 2. Cache unavailable — return stale indicator
    return {"markets": [], "is_stale": True, "note": "Weather scan cache unavailable. Run ruppert_cycle.py to refresh."}


@app.get("/api/scout/geo")
def get_geo_scout():
    """Geopolitical markets — includes settlement rules."""
    entries = read_geo_log()
    for e in entries:
        if not e.get('kalshi_url'):
            e['kalshi_url'] = f"https://kalshi.com/markets/{e.get('ticker','')}"
        e['rules_available'] = bool(e.get('rules'))
    return entries


# ─── Dashboard ────────────────────────────────────────────────────────────────

@app.get("/api/crypto/15m_summary")
def get_crypto_15m_summary():
    """15m crypto window summary — today's evaluations, entries, and skips.
    Reads from logs/decisions_15m.jsonl. Dashboard only — no per-window notifications.
    """
    return read_crypto_15m_summary()


@app.get("/api/crypto/scan")
def get_crypto_scan():
    """Crypto markets scan — BTC/ETH/XRP price + smart money signal + opportunities.
    Prices served from cache (crypto_prices.json). Scanner runs with timeout guard.
    """
    result = {"btc": None, "eth": None, "xrp": None, "smart_money": None, "opportunities": [], "signal": "neutral"}

    # ── Live prices from cache (written by background scan) ──────────────────
    _prices_cache = LOGS_DIR / "truth" / "crypto_prices.json"
    if _prices_cache.exists():
        try:
            import time as _time
            _cache_age = _time.time() - _prices_cache.stat().st_mtime
            _price_data = json.loads(_prices_cache.read_text(encoding='utf-8'))
            for _key in ("btc", "eth", "xrp"):
                if _key in _price_data:
                    result[_key] = _price_data[_key]
                    result[_key]["is_stale"] = _cache_age > 300
        except Exception:
            pass

    # ── Smart money signal — read from cache (written by background bot scan) ─
    # Bot scanner writes to logs/crypto_smart_money.json periodically
    sm_cache = LOGS_DIR / "truth" / "crypto_smart_money.json"
    if sm_cache.exists():
        try:
            sm = json.loads(sm_cache.read_text(encoding='utf-8'))
            result["smart_money"] = sm
            result["signal"] = sm.get("direction", "neutral")
        except Exception:
            pass
    if not result["smart_money"]:
        result["smart_money"] = {"direction": "neutral", "bull_pct": 0.5, "traders_sampled": 0, "note": "Pending first scan"}

    # ── Kalshi crypto markets — raw, fast (no blocking scanner) ─────────────
    # Dashboard shows live market prices; edge calc runs separately via bot scan
    # Check for cached scanner results first (written by crypto_scanner.py)
    # crypto_scanner.py writes logs/crypto_scan_latest.json (JSON, not JSONL)
    scan_cache = LOGS_DIR / "crypto_scan_latest.json"
    if scan_cache.exists():
        try:
            import time as _time
            # Use cache if fresher than 30 minutes
            if _time.time() - scan_cache.stat().st_mtime < 1800:
                with open(scan_cache, encoding='utf-8') as f:
                    data = json.load(f)
                    for opp in data.get('opportunities', []):
                        result["opportunities"].append(opp)
        except Exception:
            pass

    # Always supplement with raw Kalshi markets (fast, no edge calc)
    if len(result["opportunities"]) < 3:
        result["is_stale"] = True
        result["note"] = "Crypto scan cache stale or empty. Run ruppert_cycle.py to refresh."

    return result


@app.get("/", response_class=HTMLResponse)
def dashboard():
    with open(Path(__file__).parent / "templates" / "index.html", encoding='utf-8') as f:
        return f.read()


@app.get("/api/pnl")
def get_pnl_history():
    """
    Real P&L split into open (unrealized) and closed (realized/settled).
    Settled = past-date tickers that already resolved on Kalshi.
    Open    = current positions still trading.
    """
    global _pnl_cache
    if _pnl_cache["data"] is not None and (time.time() - _pnl_cache["ts"]) < 30:
        return _pnl_cache["data"]

    from collections import defaultdict

    all_trades = read_all_trades()

    # Build exit records index first
    exit_records = {}
    for t in all_trades:
        if t.get('action') == 'exit':
            exit_records[t.get('ticker', '')] = t

    # Build close records index for pnl: (ticker, side) -> settle/exit record
    # SUM fix: accumulate pnl across multiple settle records for the same (ticker, side)
    # e.g. two ETH settle legs with same ticker+side — last-write-wins dropped one.
    close_records_pnl = {}
    for t in all_trades:
        if t.get('action') in ('exit', 'settle'):
            tk = t.get('ticker', '')
            sd = t.get('side', '')
            if tk:
                if (tk, sd) in close_records_pnl:
                    # Accumulate pnl into the existing record rather than overwrite
                    existing = close_records_pnl[(tk, sd)]
                    if t.get('pnl') is not None and existing.get('pnl') is not None:
                        existing['pnl'] = float(existing['pnl']) + float(t['pnl'])
                else:
                    close_records_pnl[(tk, sd)] = dict(t)  # copy to avoid mutating source

    # A position is "closed" ONLY if it has a settle/exit record.
    # Expired tickers without a settle record are still "open" (pending settlement).
    settled_tickers = {}
    open_tickers    = {}
    seen = set()
    for t in all_trades:
        ticker = t.get('ticker', '')
        if not ticker or ticker in seen: continue
        if t.get('action') in ('exit', 'settle'): continue
        seen.add(ticker)
        side = t.get('side', 'no')
        has_close = (ticker, side) in close_records_pnl or ticker in exit_records
        if has_close:
            settled_tickers[ticker] = t
        else:
            open_tickers[ticker] = t

    closed_pnl_total = 0.0
    closed_by_source = {'bot': 0.0, 'manual': 0.0}
    closed_by_period = {'day': 0.0, 'month': 0.0, 'year': 0.0}
    closed_by_src_period = {'bot': {'month':0.0,'year':0.0,'all':0.0}, 'manual': {'month':0.0,'year':0.0,'all':0.0}}
    closed_wins = 0
    bot_wins = 0
    closed_total = 0
    closed_count_by_source = {'bot': 0, 'manual': 0}
    # Cost basis for closed positions — used to compute a meaningful P&L % on the dashboard.
    # Must be in dollars. bot_deployed/man_deployed are OPEN deployed capital (wrong denominator
    # when all positions are closed; causes ÷0 fallback → absurd %).
    bot_cost_basis = 0.0
    manual_cost_basis = 0.0

    # Per-module stats (bot trades only — weather, crypto, fed, other)
    module_keys = ['weather', 'crypto', 'fed', 'other']
    module_stats = {m: {
        'closed_pnl': 0.0,
        'closed_pnl_month': 0.0,
        'closed_pnl_year': 0.0,
        'trade_count': 0,
        'trade_count_month': 0,
        'trade_count_year': 0,
        'wins': 0,
    } for m in module_keys}

    from datetime import date as _date
    _today = _date.today()

    # ── Settled / manually exited positions ─────────────────────────────────
    # Use pnl field from settle/exit records directly — no API calls needed.
    for ticker, t in settled_tickers.items():
        try:
            src = t.get('source', 'bot')
            is_manual = src in ('economics', 'geo', 'manual')
            position_cost = float(t.get('size_dollars') or 0)
            if is_manual:
                manual_cost_basis += position_cost
            else:
                bot_cost_basis += position_cost

            side = t.get('side', 'no')
            cr = close_records_pnl.get((ticker, side))
            if cr and cr.get('pnl') is not None:
                pnl = round(float(cr['pnl']), 2)
            elif ticker in exit_records:
                ex = exit_records[ticker]
                pnl = ex.get('pnl')
                if pnl is None:
                    ep = ex.get('entry_price', 50)
                    xp = ex.get('exit_price', 50)
                    ct = ex.get('contracts', 0)
                    pnl = round((xp - ep) * ct / 100, 2)
                pnl = round(float(pnl), 2)
            else:
                # No settle/exit record yet — skip (settlement_checker will create one)
                continue

            closed_pnl_total += pnl
            closed_total += 1
            if pnl > 0: closed_wins += 1

            if is_manual:
                closed_by_source['manual'] += pnl
                closed_count_by_source['manual'] += 1
            else:
                closed_by_source['bot'] += pnl
                closed_count_by_source['bot'] += 1
                if pnl > 0:
                    bot_wins += 1

                _mod = classify_module(src, ticker)
                if _mod not in module_stats:
                    _mod = 'other'
                module_stats[_mod]['closed_pnl'] += pnl
                module_stats[_mod]['trade_count'] += 1
                if pnl > 0:
                    module_stats[_mod]['wins'] += 1

            # Bucket by close record timestamp or settlement date from ticker
            cr_ts = cr.get('timestamp') if cr else None
            if not cr_ts and ticker in exit_records:
                cr_ts = exit_records[ticker].get('timestamp')
            if cr_ts:
                try:
                    from datetime import datetime as _dt2
                    sdate = _dt2.fromisoformat(cr_ts.split('+')[0]).date()
                except Exception:
                    sdate = settlement_date_from_ticker(ticker)
            else:
                sdate = settlement_date_from_ticker(ticker)
            if sdate:
                if sdate == _today:
                    closed_by_period['day']   += pnl
                if sdate.year == _today.year and sdate.month == _today.month:
                    closed_by_period['month'] += pnl
                    if is_manual: closed_by_src_period['manual']['month'] += pnl
                    else:         closed_by_src_period['bot']['month']    += pnl
                    # Module period stats (bot only)
                    if not is_manual:
                        _mod2 = classify_module(src, ticker)
                        if _mod2 not in module_stats: _mod2 = 'other'
                        module_stats[_mod2]['closed_pnl_month'] += pnl
                        module_stats[_mod2]['trade_count_month'] += 1
                if sdate.year == _today.year:
                    closed_by_period['year']  += pnl
                    if is_manual: closed_by_src_period['manual']['year']  += pnl
                    else:         closed_by_src_period['bot']['year']     += pnl
                    if not is_manual:
                        _mod3 = classify_module(src, ticker)
                        if _mod3 not in module_stats: _mod3 = 'other'
                        module_stats[_mod3]['closed_pnl_year'] += pnl
                        module_stats[_mod3]['trade_count_year'] += 1
                if is_manual: closed_by_src_period['manual']['all'] += pnl
                else:         closed_by_src_period['bot']['all']    += pnl
        except Exception:
            pass

    # ── Open positions ───────────────────────────────────────────────────────
    open_pnl_total = 0.0
    open_by_source = {'bot': 0.0, 'manual': 0.0}
    open_wins = 0
    open_total = 0

    # Per-module open stats — deployed capital, trade count, and open P&L
    # open_pnl is accumulated below using live prices from Kalshi API.
    module_open_stats = {m: {'open_deployed': 0.0, 'open_trades': 0, 'open_pnl': 0.0} for m in module_keys}
    for ticker, t in open_tickers.items():
        src = t.get('source', 'bot')
        if src in ('economics', 'geo', 'manual'):
            continue
        mod = classify_module(src, ticker)
        module_open_stats[mod]['open_deployed'] += t.get('size_dollars', 0)
        module_open_stats[mod]['open_trades'] += 1

    for ticker, t in open_tickers.items():
        try:
            # WS cache only — no REST fallback
            _cached = market_cache.get_market_price(ticker, fallback_client=None)
            if _cached:
                yes_bid = _cached['yes_bid']
                yes_ask = _cached['yes_ask']
                no_bid  = _cached['no_bid']
            else:
                continue

            side      = t.get('side', 'no')
            mp        = t.get('market_prob', 0.5) or 0.5
            entry_p   = round((1 - mp) * 100) if side == 'no' else round(mp * 100)
            cost      = t.get('size_dollars', 25)
            contracts = t.get('contracts', 0) or 0
            if contracts > 0 and cost > 0:
                contracts = min(contracts, int(cost / max(entry_p, 1) * 100) + 2)

            # ── Fair value for existing position ─────────────────────────────
            # Use no_bid / yes_bid (what we'd SELL for) not ask (cost to buy more)
            # Fallback: yes_ask derived from no_bid > entry_p
            # CRITICAL: use 'is None' not 'not cur_p' — 0 is valid (full loss)
            if side == 'no':
                cur_p = no_bid
                if cur_p is None and yes_ask is not None: cur_p = 100 - yes_ask
            else:
                cur_p = yes_bid
                if cur_p is None and yes_ask is not None: cur_p = yes_ask
            if cur_p is None: cur_p = entry_p  # truly no data — hold flat
            pnl = round((cur_p - entry_p) * contracts / 100, 2)
            open_pnl_total += pnl
            open_total += 1
            if pnl > 0: open_wins += 1

            src = t.get('source', 'bot')
            if src in ('economics', 'geo', 'manual'):
                open_by_source['manual'] += pnl
            else:
                open_by_source['bot'] += pnl
                # Accumulate per-module open P&L (uses live prices from orderbook above)
                mod_open = classify_module(src, ticker)
                module_open_stats[mod_open]['open_pnl'] += pnl
        except Exception:
            pass

    total_pnl = closed_by_source['bot'] + open_by_source['bot']

    # Build chart time-series (cumulative per day) — BOT-only closed P&L
    from datetime import date as date_cls
    today = str(date_cls.today())
    points = []
    bot_closed_pnl = closed_by_source['bot']
    # Day 1: bot-only closed P&L (settled trades from prior days)
    if bot_closed_pnl != 0:
        points.append({"date": "2026-03-10", "pnl": round(bot_closed_pnl, 2)})
    # Today: total bot (closed + open)
    points.append({"date": today, "pnl": round(total_pnl, 2)})

    # Deployed costs for % calculation — exclude settled AND manually exited positions
    all_t = read_all_trades()
    exited2 = {t.get('ticker') for t in all_t if t.get('action') == 'exit'}
    seen2 = set()
    open_t = []
    for t in all_t:
        tk = t.get('ticker','')
        if not tk or tk in seen2 or tk in exited2 or t.get('action')=='exit': continue
        seen2.add(tk)
        if not is_settled_ticker(tk): open_t.append(t)
    BOT_SRC = ('bot','weather','crypto')
    MAN_SRC = ('economics','geo','manual')
    bot_dep = sum(t.get('size_dollars',0) for t in open_t if t.get('source','bot') in BOT_SRC)
    man_dep = sum(t.get('size_dollars',0) for t in open_t if t.get('source','bot') in MAN_SRC)

    # Finalise module stats: compute win rates, round values
    modules_out = {}
    for mod, ms in module_stats.items():
        wr = round(ms['wins'] / ms['trade_count'] * 100, 1) if ms['trade_count'] > 0 else None
        modules_out[mod] = {
            'closed_pnl':        round(ms['closed_pnl'], 2),
            'closed_pnl_month':  round(ms['closed_pnl_month'], 2),
            'closed_pnl_year':   round(ms['closed_pnl_year'], 2),
            'trade_count':       ms['trade_count'],
            'trade_count_month': ms['trade_count_month'],
            'trade_count_year':  ms['trade_count_year'],
            'wins':              ms['wins'],
            'win_rate':          wr,
            'open_deployed':     round(module_open_stats[mod]['open_deployed'], 2),
            'open_pnl':          round(module_open_stats[mod]['open_pnl'], 2),
            'open_trades':       module_open_stats[mod]['open_trades'],
        }

    pnl_result = {
        "open_pnl":   round(open_pnl_total, 2),
        "closed_pnl": round(closed_by_source['bot'], 2),   # BOT-only (manual excluded)
        "total_pnl":  round(total_pnl, 2),
        "bot_closed_pnl":    round(closed_by_source['bot'], 2),
        "manual_closed_pnl": round(closed_by_source['manual'], 2),
        "bot_open_pnl":      round(open_by_source['bot'], 2),
        "manual_open_pnl":   round(open_by_source['manual'], 2),
        "bot_deployed":  round(bot_dep, 2),
        "man_deployed":  round(man_dep, 2),
        "closed_pnl_day":   round(closed_by_period["day"], 2),
        "bot_closed_month":        round(closed_by_src_period["bot"]["month"], 2),
        "bot_closed_year":         round(closed_by_src_period["bot"]["year"], 2),
        "bot_closed_pnl_month":    round(closed_by_src_period["bot"]["month"], 2),
        "bot_closed_pnl_year":     round(closed_by_src_period["bot"]["year"], 2),
        "bot_closed_all":      round(closed_by_source["bot"], 2),
        "manual_closed_month": round(closed_by_src_period["manual"]["month"], 2),
        "manual_closed_year":  round(closed_by_src_period["manual"]["year"], 2),
        "manual_closed_all":   round(closed_by_source["manual"], 2),
        "closed_pnl_month": round(closed_by_period["month"], 2),
        "closed_pnl_year":  round(closed_by_period["year"], 2),
        "closed_win_rate": round(bot_wins / closed_count_by_source['bot'] * 100, 1) if closed_count_by_source['bot'] else None,  # BOT-only
        "total_trades": closed_count_by_source['bot'],   # BOT-only trade count
        "bot_trades":  closed_count_by_source['bot'],
        "man_trades":  closed_count_by_source['manual'],
        "points": points,
        "total":  round(total_pnl, 2),
        # Cost basis for closed positions (sum of original entry costs in dollars).
        # Use these as the denominator for P&L % — NOT bot_deployed/man_deployed,
        # which are OPEN position costs and become 0 when all positions are closed.
        "bot_cost_basis": round(bot_cost_basis, 2),
        "man_cost_basis": round(manual_cost_basis, 2),
        "modules": modules_out,
    }
    _pnl_cache["ts"] = time.time()
    _pnl_cache["data"] = pnl_result
    return pnl_result


# ─── /api/state — single snapshot endpoint ────────────────────────────────────


def _build_state():
    """Compute the full dashboard state in one pass.
    Uses price_cache only — no REST calls.
    """
    from datetime import date as _date

    all_trades = read_all_trades()

    try:
        STARTING_CAPITAL = get_capital()
    except Exception:
        STARTING_CAPITAL = 10000.0

    # Build exit records index
    exit_records: dict = {}
    for t in all_trades:
        if t.get('action') == 'exit':
            tk = t.get('ticker', '')
            if tk:
                exit_records[tk] = t

    # ── Build close records index: (ticker, side) -> settle/exit record ─────
    # SUM fix: accumulate pnl for duplicate (ticker, side) settle records
    _close_recs = {}
    for t in all_trades:
        if t.get('action') in ('exit', 'settle'):
            tk = t.get('ticker', '')
            sd = t.get('side', '')
            if tk:
                if (tk, sd) in _close_recs:
                    existing = _close_recs[(tk, sd)]
                    if t.get('pnl') is not None and existing.get('pnl') is not None:
                        existing['pnl'] = float(existing['pnl']) + float(t['pnl'])
                else:
                    _close_recs[(tk, sd)] = dict(t)

    # ── Split: settled/exited vs open (for P&L calculation) ──────────────────
    # A position is "closed" ONLY if it has a settle/exit record with pnl.
    # Expired tickers without a settle record are still "open" (pending settlement).
    seen: set = set()
    settled_tickers: dict = {}
    open_tickers_all: dict = {}
    for t in all_trades:
        ticker = t.get('ticker', '')
        if not ticker or ticker in seen:
            continue
        if t.get('action') in ('exit', 'settle'):
            continue
        seen.add(ticker)
        side = t.get('side', 'no')
        has_close = (ticker, side) in _close_recs or ticker in exit_records
        if has_close:
            settled_tickers[ticker] = t
        else:
            open_tickers_all[ticker] = t

    # ── Open positions list (action=open/buy, not settled/exited) ────────────
    exited: set = set(exit_records.keys())
    seen2: set = set()
    open_pos_tickers: dict = {}
    for t in all_trades:
        ticker = t.get('ticker', '')
        if not ticker or ticker in seen2 or ticker in exited:
            continue
        action = (t.get('action') or '').lower()
        if action != 'open' and not action.startswith('buy'):
            continue
        if is_settled_ticker(ticker):
            continue
        seen2.add(ticker)
        open_pos_tickers[ticker] = t

    # ── Fetch prices ONCE per open position (price_cache only — no REST) ──
    prices: dict = {}
    for ticker in open_pos_tickers:
        _cached = market_cache.get_market_price(ticker, fallback_client=None)
        if _cached:
            prices[ticker] = {
                'yes_ask': _cached['yes_ask'], 'yes_bid': _cached['yes_bid'],
                'no_ask': _cached['no_ask'], 'no_bid': _cached['no_bid'],
            }

    # ── Build positions list (reuses prices fetched above) ────────────────────
    module_keys = ['weather', 'crypto', 'fed', 'geo', 'other']
    module_open: dict = {m: {'open_deployed': 0.0, 'open_trades': 0, 'open_pnl': 0.0} for m in module_keys}

    positions = []
    open_pnl_total = 0.0
    open_cost_total = 0.0

    for ticker, t in open_pos_tickers.items():
        side      = t.get('side', 'no')
        source    = t.get('source', 'bot')
        mp        = t.get('market_prob', 0.5) or 0.5
        ep        = int((1 - mp) * 100) if side == 'no' else int(mp * 100)
        cost      = float(t.get('size_dollars') or 0)
        contracts = t.get('contracts', 0) or 0
        mod       = classify_module(source, ticker)
        if mod not in module_open:
            mod = 'other'

        lv = prices.get(ticker)
        cur_p = None
        if lv:
            if side == 'no':
                cur_p = lv.get('no_bid')
                if cur_p is None and lv.get('yes_ask') is not None:
                    cur_p = 100 - lv['yes_ask']
            else:
                cur_p = lv.get('yes_bid')
                if cur_p is None and lv.get('yes_ask') is not None:
                    cur_p = lv['yes_ask']

        pnl     = None
        pnl_pct = None
        status  = 'open'
        if cur_p is not None:
            pnl = round((cur_p - ep) * contracts / 100, 2)
            pnl_pct = round(pnl / cost * 100, 2) if cost else 0.0
            if pnl > 0.01:    status = 'WINNING'
            elif pnl < -0.01: status = 'LOSING'
            else:             status = 'EVEN'
            open_pnl_total += pnl
            open_cost_total += cost

        module_open[mod]['open_deployed'] += cost
        module_open[mod]['open_trades']   += 1
        if pnl is not None:
            module_open[mod]['open_pnl'] += pnl

        edge_val = t.get('edge')
        _raw_title = (t.get('title') or ticker).replace('**', '')
        _win_time2 = _parse_15m_window_time(ticker)
        if _win_time2:
            import re as _re3
            _raw_title = _re3.sub(r'\s+\d{4}-\d{2}-\d{2}\b', '', _raw_title).strip()
            _raw_title = f"{_raw_title} {_win_time2}"
        positions.append({
            'ticker':        ticker,
            'title':         _raw_title,
            'side':          _translate_15m_side(ticker, side),
            'source':        source,
            'module':        mod,
            'parent_module': get_parent_module(mod),
            'entry_price': ep,
            'cur_price':   cur_p,
            'pnl':         pnl,
            'pnl_pct':     pnl_pct,
            'cost':        round(cost, 2),
            'contracts':   contracts,
            'edge':        round(edge_val, 3) if edge_val else None,
            'noaa_prob':   t.get('noaa_prob'),
            'market_prob': t.get('market_prob'),
            'status':      status,
            'close_time':  t.get('close_time', ''),
        })

    # ── Closed P&L (settled/exited positions) ────────────────────────────────
    _today = _date.today()
    closed_pnl_total = 0.0
    closed_pnl_month = 0.0
    closed_pnl_year  = 0.0
    closed_pnl_day   = 0.0
    closed_wins      = 0
    closed_count     = 0

    module_closed: dict = {m: {
        'closed_pnl': 0.0,
        'closed_pnl_month': 0.0,
        'closed_pnl_year': 0.0,
        'trade_count': 0,
        'wins': 0,
    } for m in module_keys}

    # Build close records index for _build_state: (ticker, side) -> record
    # SUM fix: accumulate pnl for duplicate (ticker, side) settle records
    _close_recs_state = {}
    for t in all_trades:
        if t.get('action') in ('exit', 'settle'):
            tk = t.get('ticker', '')
            sd = t.get('side', '')
            if tk:
                if (tk, sd) in _close_recs_state:
                    existing = _close_recs_state[(tk, sd)]
                    if t.get('pnl') is not None and existing.get('pnl') is not None:
                        existing['pnl'] = float(existing['pnl']) + float(t['pnl'])
                else:
                    _close_recs_state[(tk, sd)] = dict(t)

    for ticker, t in settled_tickers.items():
        try:
            src = t.get('source', 'bot')
            is_manual = src in ('economics', 'geo', 'manual')

            side2 = t.get('side', 'no')
            cr = _close_recs_state.get((ticker, side2))
            if cr and cr.get('pnl') is not None:
                pnl_val = round(float(cr['pnl']), 2)
            elif ticker in exit_records:
                ex = exit_records[ticker]
                pnl_val = ex.get('pnl')
                if pnl_val is None:
                    ep2 = ex.get('entry_price', 50)
                    xp  = ex.get('exit_price', 50)
                    ct2 = ex.get('contracts', 0)
                    pnl_val = round((xp - ep2) * ct2 / 100, 2)
                pnl_val = round(float(pnl_val), 2)
            else:
                # No settle/exit record yet — skip
                continue

            closed_pnl_total += pnl_val
            closed_count     += 1
            if pnl_val > 0:
                closed_wins += 1

            if not is_manual:
                mod_c = classify_module(src, ticker)
                if mod_c not in module_closed:
                    mod_c = 'other'
                module_closed[mod_c]['closed_pnl']  += pnl_val
                module_closed[mod_c]['trade_count'] += 1
                if pnl_val > 0:
                    module_closed[mod_c]['wins'] += 1

            # Period bucketing
            cr_ts2 = cr.get('timestamp') if cr else None
            if not cr_ts2 and ticker in exit_records:
                cr_ts2 = exit_records[ticker].get('timestamp')
            if cr_ts2:
                try:
                    from datetime import datetime as _dt2
                    sdate = _dt2.fromisoformat(cr_ts2.split('+')[0]).date()
                except Exception:
                    sdate = settlement_date_from_ticker(ticker)
            else:
                sdate = settlement_date_from_ticker(ticker)

            if sdate:
                if sdate == _today:
                    closed_pnl_day += pnl_val
                if sdate.year == _today.year and sdate.month == _today.month:
                    closed_pnl_month += pnl_val
                    if not is_manual:
                        mod_cm = classify_module(src, ticker)
                        if mod_cm not in module_closed: mod_cm = 'other'
                        module_closed[mod_cm]['closed_pnl_month'] += pnl_val
                if sdate.year == _today.year:
                    closed_pnl_year += pnl_val
                    if not is_manual:
                        mod_cy = classify_module(src, ticker)
                        if mod_cy not in module_closed: mod_cy = 'other'
                        module_closed[mod_cy]['closed_pnl_year'] += pnl_val
        except Exception:
            pass

    # ── Finalize module stats ─────────────────────────────────────────────────
    modules_out: dict = {}
    for mod in ['weather', 'crypto', 'fed', 'geo']:
        oc = module_open.get(mod, {})
        cc = module_closed.get(mod, {})
        tc = cc.get('trade_count', 0)
        wr = round(cc['wins'] / tc * 100, 1) if tc > 0 else None
        modules_out[mod] = {
            'open_trades':      oc.get('open_trades', 0),
            'open_deployed':    round(oc.get('open_deployed', 0.0), 2),
            'open_pnl':         round(oc.get('open_pnl', 0.0), 2),
            'closed_pnl':       round(cc.get('closed_pnl', 0.0), 2),
            'closed_pnl_month': round(cc.get('closed_pnl_month', 0.0), 2),
            'closed_pnl_year':  round(cc.get('closed_pnl_year', 0.0), 2),
            'win_rate':         wr,
            'trade_count':      tc,
        }

    # ── Account ───────────────────────────────────────────────────────────────
    deployed     = round(sum(p['cost'] for p in positions), 2)
    buying_power = round(max(STARTING_CAPITAL - deployed, 0), 2)

    total_bot_trades = sum(m['trade_count'] for m in module_closed.values())
    total_bot_wins   = sum(m['wins'] for m in module_closed.values())
    win_rate = round(total_bot_wins / total_bot_trades * 100, 1) if total_bot_trades > 0 else None

    # ── Smart money (from cache) ──────────────────────────────────────────────
    smart_money = {'direction': 'neutral', 'bull_pct': 0.5, 'traders_sampled': 0}
    sm_cache = LOGS_DIR / "truth" / "crypto_smart_money.json"
    if sm_cache.exists():
        try:
            smart_money = json.loads(sm_cache.read_text(encoding='utf-8'))
        except Exception:
            pass

    # Closed P&L is now computed from settle/exit records directly.
    # No longer overriding with pnl_cache.json (which may be stale).

    return {
        'account': {
            'balance':          round(STARTING_CAPITAL, 2),
            'buying_power':     buying_power,
            'deployed':         deployed,
            'open_pnl':         round(open_pnl_total, 2),
            'open_cost':        round(open_cost_total, 2),
            'closed_pnl':       round(closed_pnl_total, 2),
            'closed_pnl_month': round(closed_pnl_month, 2),
            'closed_pnl_year':  round(closed_pnl_year, 2),
            'closed_pnl_day':   round(closed_pnl_day, 2),
            'total_pnl':        round(open_pnl_total + closed_pnl_total, 2),
            'win_rate':         win_rate,
            'total_trades':     total_bot_trades,
            'mode':             get_mode(),
        },
        'positions':   positions,
        'modules':     modules_out,
        'smart_money': smart_money,
    }


@app.get("/api/state")
def get_state():
    """Single snapshot endpoint: account, positions, module stats, smart money.
    Fetches Kalshi orderbook once per position — no duplicate network calls.
    Results cached for 30 seconds.
    """
    global _state_cache
    if _state_cache["data"] is not None and (time.time() - _state_cache["ts"]) < 30:
        return _state_cache["data"]
    result = _build_state()
    _state_cache["ts"] = time.time()
    _state_cache["data"] = result
    return result


