"""
Ruppert Dashboard API
FastAPI backend serving live bot data.
Run with: uvicorn dashboard.api:app --reload --port 8765
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
import json
from datetime import date, datetime
from pathlib import Path

app = FastAPI(title="Ruppert Trading Dashboard")
LOGS_DIR = Path(__file__).parent.parent / "logs"
MODE_FILE = Path(__file__).parent.parent / "mode.json"

def get_mode() -> str:
    """Returns 'demo' or 'live'."""
    try:
        if MODE_FILE.exists():
            return json.loads(MODE_FILE.read_text(encoding='utf-8')).get('mode', 'demo')
    except Exception:
        pass
    return 'demo'

def set_mode(mode: str):
    MODE_FILE.write_text(json.dumps({"mode": mode}, indent=2), encoding='utf-8')

# ─── Helpers ─────────────────────────────────────────────────────────────────

def read_today_trades():
    log_path = LOGS_DIR / f"trades_{date.today().isoformat()}.jsonl"
    trades = []
    if log_path.exists():
        with open(log_path, encoding='utf-8') as f:
            for line in f:
                try: trades.append(json.loads(line))
                except: pass
    return trades


def read_all_trades():
    all_trades = []
    for path in sorted(LOGS_DIR.glob("trades_*.jsonl")):
        with open(path, encoding='utf-8') as f:
            for line in f:
                try:
                    t = json.loads(line)
                    t['_date'] = path.stem.replace('trades_', '')
                    all_trades.append(t)
                except: pass
    return all_trades


def read_geo_log():
    log_path = LOGS_DIR / "geopolitical_scout.jsonl"
    entries = []
    if log_path.exists():
        with open(log_path, encoding='utf-8') as f:
            for line in f:
                try: entries.append(json.loads(line))
                except: pass
    today = str(date.today())
    return [e for e in entries if e.get('date') == today]


def read_high_conviction():
    log_path = LOGS_DIR / "best_bets.jsonl"
    entries = []
    if log_path.exists():
        with open(log_path, encoding='utf-8') as f:
            for line in f:
                try: entries.append(json.loads(line))
                except: pass

    # Load passed tickers so we can exclude them
    passed = set()
    pass_path = LOGS_DIR / "highconviction_passed.jsonl"
    if pass_path.exists():
        with open(pass_path, encoding='utf-8') as f:
            for line in f:
                try: passed.add(json.loads(line).get('ticker', ''))
                except: pass

    # Load approved tickers so we can exclude them too
    approved = set()
    approve_path = LOGS_DIR / "highconviction_approved.jsonl"
    if approve_path.exists():
        with open(approve_path, encoding='utf-8') as f:
            for line in f:
                try: approved.add(json.loads(line).get('ticker', ''))
                except: pass

    # Deduplicate by ticker (keep most recent per ticker), exclude passed/approved, exclude expired
    from datetime import datetime as _dt
    now = _dt.utcnow()
    seen_ticker = {}
    for e in entries:
        t = e.get('ticker', '')
        seen_ticker[t] = e  # last entry per ticker wins

    result = []
    for t, e in seen_ticker.items():
        if t in passed or t in approved:
            continue
        close_str = e.get('close_date', '')
        if close_str:
            try:
                close_dt = _dt.fromisoformat(close_str.replace('Z', '+00:00')).replace(tzinfo=None)
                if close_dt < now:
                    continue
            except: pass
        result.append(e)

    # Deduplicate by title — same question at multiple thresholds → keep highest edge × confidence
    seen_title = {}
    for e in result:
        title = (e.get('title') or e.get('ticker', '')).strip()
        score = (e.get('edge', 0) or 0) * (e.get('confidence', 0) or 0)
        if title not in seen_title or score > seen_title[title][1]:
            seen_title[title] = (e, score)

    result = [v[0] for v in seen_title.values()]
    # Sort by Total Confidence descending
    result.sort(key=lambda x: x.get('confidence', 0) or 0, reverse=True)
    return result


SPORTS_EXCLUSIONS = [
    'points scored','rebounds','assists','touchdowns','home runs','field goal',
    'three-pointer','wins by','over 1.5','over 2.5','over 3.5','lakers','celtics',
    'warriors','knicks','heat ','bulls','nets','nba','nfl','mlb','nhl','ncaa',
    'soccer','basketball game','football game','baseball game','hockey game',
    'tennis','golf tournament','mma','boxing','both teams','goals scored',
    'rushing yards','strikeouts','shots on goal','super bowl','world series',
    'nba finals','stanley cup','world cup','march madness',
]


def classify_module(src: str, ticker: str) -> str:
    """Classify a trade into a module bucket based on source and ticker prefix."""
    t = (ticker or '').upper()
    if (src in ('weather', 'bot')) and t.startswith('KXHIGH'):
        return 'weather'
    if src == 'crypto' or (src == 'bot' and (
        t.startswith('KXBTC') or t.startswith('KXETH') or
        t.startswith('KXXRP') or t.startswith('KXDOGE')
    )):
        return 'crypto'
    if src == 'fed' or t.startswith('KXFED') or t.startswith('KXCPI'):
        return 'fed'
    return 'other'


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

def is_settled_ticker(ticker: str) -> bool:
    """Return True if ticker contains a past date (market already settled).
    Handles both date-only (26MAR11) and date+time (26MAR1117) formats.
    """
    import re as _re
    from datetime import date, datetime
    today = date.today()
    months = {'JAN':1,'FEB':2,'MAR':3,'APR':4,'MAY':5,'JUN':6,
              'JUL':7,'AUG':8,'SEP':9,'OCT':10,'NOV':11,'DEC':12}
    parts = ticker.upper().split('-')
    for part in parts:
        # Match 26MAR11 (date only) OR 26MAR1117 (date + 2-digit hour)
        m = _re.match(r'^(\d{2})([A-Z]{3})(\d{2})(\d{2})?$', part)
        if m:
            yy, mon, dd = m.group(1), m.group(2), m.group(3)
            month_num = months.get(mon)
            if month_num:
                try:
                    mkt_date = date(2000 + int(yy), month_num, int(dd))
                    if mkt_date < today:
                        return True
                    # Same day but with hour — check if settlement time has passed
                    if mkt_date == today and m.group(4):
                        hour = int(m.group(4))
                        # W6 fix: use full EDT datetime comparison to avoid midnight
                        # crossover bug where (utc_hour - 4) % 24 wraps 0-2 and
                        # fails the >= check against settlement hours like 17.
                        from datetime import datetime as _dt, timedelta as _td
                        now_edt = _dt.utcnow() - _td(hours=4)
                        settle_edt = _dt(mkt_date.year, mkt_date.month, mkt_date.day, hour)
                        if now_edt >= settle_edt:
                            return True
                except Exception:
                    pass
    return False

@app.get("/api/summary")
def get_summary():
    trades = read_all_trades()
    today  = read_today_trades()
    return {
        "total_trades":    len(trades),
        "today_trades":    len(today),
        "total_exposure":  round(sum(t.get('size_dollars',0) for t in trades), 2),
        "today_exposure":  round(sum(t.get('size_dollars',0) for t in today), 2),
        "mode": get_mode().upper(), "status": "RUNNING",
    }


@app.get("/api/account")
def get_account():
    """Account summary.

    ── DEMO MODE (current) ───────────────────────────────────────────────────
    Starting capital is tracked locally — no Kalshi API call needed.
      Account Value  = STARTING_CAPITAL + Open P&L + Closed P&L   (frontend computes)
      Buying Power   = STARTING_CAPITAL − Deployed Capital in open trades
      Starting Capital = $200 initial + $200 crypto allocation = $400

    ── LIVE MODE (switch when David approves going live) ────────────────────
    Replace the STARTING_CAPITAL line below with a real Kalshi API call:
        from kalshi_client import KalshiClient
        balance_dollars = KalshiClient().get_balance()  # already returns dollars
    Then update frontend: remove open_pnl addition from Account Value formula —
    Kalshi balance already reflects open positions in live mode.
    ─────────────────────────────────────────────────────────────────────────
    """
    current_mode = get_mode()

    all_trades = read_all_trades()

    # Deduplicate by ticker (same logic as positions endpoint)
    # Only count each position once — ignore exit entries and duplicates
    exited = {t.get('ticker') for t in all_trades if t.get('action') == 'exit'}
    seen_tickers = set()
    trades = []
    for t in all_trades:
        ticker = t.get('ticker', '')
        if not ticker or ticker in exited or ticker in seen_tickers: continue
        if t.get('action') == 'exit': continue
        seen_tickers.add(ticker)
        trades.append(t)

    # Bot = weather + crypto (fully autonomous, Ruppert decides)
    # Manual = economics + geo (David approves)
    # Gaming removed entirely
    AUTO_SOURCES   = ('bot', 'weather', 'crypto')
    MANUAL_SOURCES = ('economics', 'geo', 'manual')

    # Only count OPEN (not-yet-settled) positions in deployed capital
    # Settled positions: their capital is gone (loss) or returned (win) — reflected in Closed P&L
    open_trades  = [t for t in trades if not is_settled_ticker(t.get('ticker', ''))]
    bot_cost     = sum(t.get('size_dollars',0) for t in open_trades if t.get('source','bot') in AUTO_SOURCES)
    manual_cost  = sum(t.get('size_dollars',0) for t in open_trades if t.get('source','bot') in MANUAL_SOURCES)
    total_deployed = bot_cost + manual_cost

    # Capital source: Live = Kalshi API balance; Demo = sum of demo deposits
    if current_mode == 'live':
        try:
            sys.path.insert(0, str(Path(__file__).parent.parent))
            from kalshi_client import KalshiClient
            STARTING_CAPITAL = KalshiClient().get_balance()
        except Exception as e:
            STARTING_CAPITAL = 400.0  # fallback if API fails
        # In live mode, Kalshi balance already reflects settled P&L
        # Buying power = balance minus currently deployed (open positions)
        buying_power = max(STARTING_CAPITAL - total_deployed, 0)
    else:
        # Demo: computed capital = deposits + realized P&L from all exit records.
        # Mirrors get_computed_capital() in logger.py — inlined here to avoid circular imports.
        # W4: replaces stale get_balance() display (~$172) with true computed capital (~$510).
        deposits_path = LOGS_DIR / "demo_deposits.jsonl"
        STARTING_CAPITAL = 0.0
        if deposits_path.exists():
            try:
                with open(deposits_path, encoding='utf-8') as f:
                    for line in f:
                        try: STARTING_CAPITAL += json.loads(line).get('amount', 0)
                        except: pass
            except Exception:
                pass
        if STARTING_CAPITAL == 0:
            STARTING_CAPITAL = 400.0  # fallback if deposits file missing or empty
        STARTING_CAPITAL = round(STARTING_CAPITAL, 2)
        # Read bot-only closed P&L from cache (written by /api/pnl, manual trades excluded).
        # buying_power = starting_capital + bot_closed_pnl - open_deployed
        # Frontend JS also computes this using window._closedPnl (bot-only after Fix 1).
        _bot_closed_cached = 0.0
        try:
            _pnl_cache_path = LOGS_DIR / "pnl_cache.json"
            if _pnl_cache_path.exists():
                _bot_closed_cached = json.loads(_pnl_cache_path.read_text(encoding='utf-8')).get('closed_pnl', 0.0)
        except Exception:
            pass
        buying_power = max(STARTING_CAPITAL + _bot_closed_cached - total_deployed, 0)

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
    body = await request.json()
    amount = float(body.get('amount', 0))
    note   = str(body.get('note', 'Manual deposit'))
    if amount <= 0:
        return {"error": "Amount must be positive"}
    entry = {"date": date.today().isoformat(), "amount": round(amount, 2), "note": note}
    deposits_path = LOGS_DIR / "demo_deposits.jsonl"
    with open(deposits_path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry) + '\n')
    return {"ok": True, "entry": entry}


@app.get("/api/trades")
def get_trades():
    """Trade history — closed positions only (settled OR manually exited).
    Computes realized_pnl from exit record (manual exits) or Kalshi API (settled markets).
    """
    all_trades = read_all_trades()

    # Pre-build exit records dict: ticker -> exit record
    exits = {}
    for t in all_trades:
        if t.get('action') == 'exit':
            ticker = t.get('ticker', '')
            if ticker:
                exits[ticker] = t

    closed = []
    seen = set()
    for t in all_trades:
        ticker = t.get('ticker', '')
        if not ticker or ticker in seen: continue
        if t.get('action') == 'exit': continue  # skip raw exit records; they inform via exits dict
        seen.add(ticker)

        is_settled       = is_settled_ticker(ticker)
        is_manually_exited = ticker in exits

        # Only show in closed if settled OR manually exited
        if not is_settled and not is_manually_exited:
            continue

        if is_manually_exited and not is_settled:
            # Compute P&L directly from exit record fields
            exit_rec  = exits[ticker]
            ep        = exit_rec.get('entry_price')
            xp        = exit_rec.get('exit_price')
            contracts = exit_rec.get('contracts')
            if ep is not None and xp is not None and contracts:
                t['realized_pnl'] = round((xp - ep) * contracts / 100, 2)
                t['exit_price']   = xp
                t['exit_type']    = exit_rec.get('exit_type', 'manual')
                t['exit_reason']  = exit_rec.get('reason', '')
            else:
                # Fallback: try market API
                try:
                    import requests as req
                    r = req.get(
                        f'https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}',
                        timeout=4
                    )
                    if r.status_code == 200:
                        m         = r.json().get('market', {})
                        result    = m.get('result')
                        lp        = m.get('last_price')
                        if lp is not None or result:
                            side      = t.get('side', 'no')
                            mp        = t.get('market_prob', 0.5) or 0.5
                            entry_p   = int((1 - mp) * 100) if side == 'no' else int(mp * 100)
                            contracts = t.get('contracts', 0) or 0
                            if result == 'yes':   settle_yes = 100
                            elif result == 'no':  settle_yes = 0
                            else:                 settle_yes = lp or 50
                            cur_p = (100 - settle_yes) if side == 'no' else settle_yes
                            t['realized_pnl'] = round((cur_p - entry_p) * contracts / 100, 2)
                            t['settled_price'] = settle_yes
                except Exception:
                    pass
        else:
            # Settled market — fetch final result from Kalshi API
            try:
                import requests as req
                r = req.get(
                    f'https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}',
                    timeout=4
                )
                if r.status_code == 200:
                    m         = r.json().get('market', {})
                    result    = m.get('result')
                    lp        = m.get('last_price')
                    if lp is not None or result:
                        side      = t.get('side', 'no')
                        mp        = t.get('market_prob', 0.5) or 0.5
                        entry_p   = int((1 - mp) * 100) if side == 'no' else int(mp * 100)
                        contracts = t.get('contracts', 0) or 0
                        if result == 'yes':   settle_yes = 100
                        elif result == 'no':  settle_yes = 0
                        else:                 settle_yes = lp or 50
                        cur_p = (100 - settle_yes) if side == 'no' else settle_yes
                        t['realized_pnl'] = round((cur_p - entry_p) * contracts / 100, 2)
                        t['settled_price'] = settle_yes
            except Exception:
                pass

        t['module'] = classify_module(t.get('source', 'bot'), ticker)
        closed.append(t)
    # Exclude manual trades from the closed trades table display
    _MANUAL_EXCL = ('manual', 'economics', 'geo')
    closed = [t for t in closed if t.get('source', 'bot') not in _MANUAL_EXCL]
    return closed


@app.post("/api/highconviction/execute")
async def execute_highconviction(req: Request):
    """Execute a High Conviction bet — logs trade (demo) or places live order."""
    import json as _json
    from datetime import datetime as _dt
    body    = await req.json()
    ticker  = body.get('ticker', '')
    side    = body.get('side', '').lower()   # 'yes' or 'no'
    price_c = int(body.get('price_cents', 50))
    max_pos = 25.0  # $25 max per trade

    contracts = max(1, int((max_pos / price_c) * 100))  # how many contracts fit in $25
    # market_prob = YES probability (what the positions table uses for entry price calc)
    market_prob = (100 - price_c) / 100.0 if side == 'no' else price_c / 100.0
    title   = body.get('title', '')

    # Always log to trades file
    today = _dt.now().strftime('%Y-%m-%d')
    log_path = LOGS_DIR / f'trades_{today}.jsonl'
    trade = {
        'ticker':       ticker,
        'title':        title,
        'side':         side,
        'contracts':    contracts,
        'size_dollars': round(contracts * price_c / 100, 2),
        'market_prob':  market_prob,
        'source':       'manual',
        'timestamp':    _dt.utcnow().isoformat(),
        'date':         today,
        'action':       'buy',
    }
    with open(log_path, 'a', encoding='utf-8') as f:
        f.write(_json.dumps(trade) + '\n')

    # Also mark as approved so it leaves the HC queue
    ap_path = LOGS_DIR / 'highconviction_approved.jsonl'
    with open(ap_path, 'a', encoding='utf-8') as f:
        f.write(_json.dumps({'ticker': ticker, 'approved_at': _dt.utcnow().isoformat(), 'status': 'executed'}) + '\n')

    # In live mode: actually place the order via KalshiClient
    is_live = False  # TODO: read from config when going live
    if is_live:
        try:
            from kalshi_client import KalshiClient
            KalshiClient().place_order(ticker, side, price_c, contracts)
        except Exception as e:
            return {'status': 'error', 'error': str(e)}

    return {'status': 'executed', 'ticker': ticker, 'side': side,
            'contracts': contracts, 'cost': trade['size_dollars'], 'demo': not is_live}

@app.post("/api/highconviction/approve")
async def approve_highconviction(req: Request):
    """Mark a best bet as approved — logs it for the next bot execution cycle."""
    import json as _json
    from datetime import datetime as _dt
    body = await req.json()
    ticker = body.get('ticker', '')
    log_path = LOGS_DIR / 'highconviction_approved.jsonl'
    with open(log_path, 'a', encoding='utf-8') as f:
        f.write(_json.dumps({'ticker': ticker, 'approved_at': _dt.utcnow().isoformat(), 'status': 'pending'}) + '\n')
    return {'status': 'approved', 'ticker': ticker}

@app.post("/api/highconviction/pass")
async def pass_highconviction(req: Request):
    """Dismiss a best bet."""
    import json as _json
    from datetime import datetime as _dt
    body = await req.json()
    ticker = body.get('ticker', '')
    log_path = LOGS_DIR / 'highconviction_passed.jsonl'
    with open(log_path, 'a', encoding='utf-8') as f:
        f.write(_json.dumps({'ticker': ticker, 'passed_at': _dt.utcnow().isoformat()}) + '\n')
    return {'status': 'passed', 'ticker': ticker}

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
    current_mode = get_mode()

    if current_mode == 'live':
        # LIVE mode: get real positions from Kalshi API
        try:
            sys.path.insert(0, str(Path(__file__).parent.parent))
            from kalshi_client import KalshiClient
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
            return positions
        except Exception:
            pass  # Fall through to log-based approach if Kalshi API fails

    # DEMO mode (or LIVE fallback): read from trade logs
    # dry_run trades are NOT real Kalshi positions — trade logs are the source of truth
    all_trades = read_all_trades()

    # Build set of exited tickers
    exited = {t.get('ticker') for t in all_trades if t.get('action') == 'exit'}

    # Deduplicate: keep first (earliest) open/buy entry per ticker
    # Only collect entries where action is 'open' or 'buy' (not exit, add-on, update, etc.)
    seen = {}
    for t in all_trades:
        ticker = t.get('ticker','')
        if not ticker: continue
        if ticker in exited: continue
        if ticker in seen: continue  # already have opening entry
        if t.get('action') not in ('open', 'buy'): continue  # only genuine open entries
        if is_settled_ticker(ticker): continue  # skip past-date markets
        seen[ticker] = t

    open_trades = list(seen.values())
    if not open_trades:
        return []

    total_cost = sum(t.get('size_dollars', 0) for t in open_trades)
    positions  = []
    for t in open_trades:
        ticker = t.get('ticker', '')
        title  = (t.get('title') or ticker).replace('**', '')
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
            "side":        side,
            "source":      source,
            "module":      classify_module(source, ticker),
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

    return positions


@app.get("/api/positions/prices")
def get_live_prices():
    """Async live prices for ALL open positions — called separately by frontend."""
    import requests as req
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
        try:
            # Use orderbook endpoint — REST /markets/{ticker} returns null for bid/ask
            ob_resp = req.get(
                f'https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}/orderbook',
                timeout=4
            )
            if ob_resp.status_code == 200:
                ob = ob_resp.json().get('orderbook_fp', {})
                no_dollars  = ob.get('no_dollars', [])
                yes_dollars = ob.get('yes_dollars', [])
                no_bid  = int(round(max((float(p) for p, _ in no_dollars),  default=0) * 100)) if no_dollars  else None
                yes_bid = int(round(max((float(p) for p, _ in yes_dollars), default=0) * 100)) if yes_dollars else None
                yes_ask = (100 - no_bid)  if no_bid  is not None else None
                no_ask  = (100 - yes_bid) if yes_bid is not None else None
                prices[ticker] = {
                    'yes_ask': yes_ask,
                    'yes_bid': yes_bid,
                    'no_ask':  no_ask,
                    'no_bid':  no_bid,
                }
            else:
                # Fallback: REST endpoint for settled markets
                rest_resp = req.get(
                    f'https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}',
                    timeout=4
                )
                if rest_resp.status_code == 200:
                    m = rest_resp.json().get('market', {})
                    prices[ticker] = {
                        'yes_ask': m.get('yes_ask'),
                        'yes_bid': m.get('yes_bid'),
                        'no_ask':  m.get('no_ask'),
                        'no_bid':  m.get('no_bid'),
                    }
        except Exception:
            pass
        import time as _time
        _time.sleep(0.05)  # rate-limit: 20 req/sec

    # Override prices for settled markets using last_price (YES settlement price)
    # e.g. last_price=99 means YES won → NO is worth 1¢
    # This prevents Kalshi's no_ask=100 artifact from inflating P&L
    for ticker, p in prices.items():
        if p.get('yes_ask') == 100 and p.get('no_ask') == 100:
            # Market looks settled — fetch status to confirm and get real settlement
            try:
                resp2 = req.get(
                    f'https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}',
                    timeout=4
                )
                if resp2.status_code == 200:
                    m2 = resp2.json().get('market', {})
                    if m2.get('status') in ('closed', 'settled'):
                        lp = m2.get('last_price')
                        if lp is not None:
                            # last_price = YES settlement (99=YES won, 1=NO won)
                            p['yes_ask'] = lp
                            p['no_ask']  = 100 - lp
                            p['settled'] = True
            except Exception:
                pass

    return prices


@app.get("/api/positions/status")
def get_position_statuses():
    """Returns market status for each open position ticker — used to exclude settled markets from P&L."""
    import requests as req
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
            resp = req.get(
                f'https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}',
                timeout=4
            )
            if resp.status_code == 200:
                m = resp.json().get('market', {})
                statuses[ticker] = {
                    'status': m.get('status', 'unknown'),
                    'result': m.get('result', ''),
                    'last_price': m.get('last_price'),
                }
        except Exception:
            pass
    return statuses


@app.get("/api/kalshi/weather")
def get_weather_markets():
    """
    Weather markets — served from scanner cache for speed.
    Background scanner (ruppert_cycle.py) writes logs/weather_scan.jsonl.
    Fallback: raw Kalshi markets with no edge calc (fast, no NOAA calls).
    """
    import requests as req

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

    # 2. Fast fallback: raw Kalshi markets, no blocking NOAA/ensemble calls
    try:
        series = ['KXHIGHNY', 'KXHIGHLA', 'KXHIGHCHI', 'KXHIGHHOU', 'KXHIGHMIA', 'KXHIGHPHX']
        markets = []
        for s in series:
            try:
                resp = req.get(
                    'https://api.elections.kalshi.com/trade-api/v2/markets',
                    params={'series_ticker': s, 'status': 'open', 'limit': 8},
                    timeout=5
                )
                if resp.status_code == 200:
                    for m in resp.json().get('markets', []):
                        m['_has_edge']  = False
                        m['_edge']      = None
                        m['_noaa_prob'] = None
                        m['kalshi_url'] = f"https://kalshi.com/markets/{m.get('ticker','')}"
                        markets.append(m)
            except Exception:
                pass
        return markets[:30]
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/scout/geo")
def get_geo_scout():
    """Geopolitical markets — includes settlement rules."""
    entries = read_geo_log()
    # Enrich with rules if missing
    for e in entries:
        if not e.get('rules') and e.get('ticker'):
            try:
                import requests as req
                resp = req.get(
                    f"https://api.elections.kalshi.com/trade-api/v2/markets/{e['ticker']}",
                    timeout=3
                )
                if resp.status_code == 200:
                    m = resp.json().get('market', {})
                    e['rules']      = m.get('rules_primary', '')
                    e['kalshi_url'] = f"https://kalshi.com/markets/{e['ticker']}"
            except Exception:
                pass
        if not e.get('kalshi_url'):
            e['kalshi_url'] = f"https://kalshi.com/markets/{e.get('ticker','')}"
    return entries


@app.get("/api/highconviction")
def get_high_conviction():
    """Best Bets — non-weather, 60%+ confidence, 15%+ edge, needs David's approval."""
    return read_high_conviction()


# ─── Dashboard ────────────────────────────────────────────────────────────────

@app.get("/api/crypto/scan")
def get_crypto_scan():
    """Crypto markets scan — BTC/ETH/XRP price + smart money signal + opportunities.
    Uses Kraken for prices (Binance geo-blocked in US). Scanner runs with timeout guard.
    """
    import requests as req
    import concurrent.futures, time

    result = {"btc": None, "eth": None, "xrp": None, "smart_money": None, "opportunities": [], "signal": "neutral"}

    # ── Live prices from Kraken (reliable, no geo-block) ─────────────────────
    KRAKEN_PAIRS = {"btc": "XBTUSD", "eth": "ETHUSD", "xrp": "XRPUSD"}
    for key, pair in KRAKEN_PAIRS.items():
        try:
            r = req.get(f"https://api.kraken.com/0/public/Ticker?pair={pair}", timeout=5)
            if r.status_code == 200:
                data = r.json().get("result", {})
                t = list(data.values())[0] if data else {}
                price = float(t.get("c", [0])[0])
                open_p = float(t.get("o", price) or price)
                chg = ((price - open_p) / open_p * 100) if open_p else 0
                result[key] = {
                    "price": round(price, 4 if key == "xrp" else 2),
                    "change_24h_pct": round(chg, 2),
                    "high_24h": float(t.get("h", [0,0])[1]),
                    "low_24h":  float(t.get("l", [0,0])[1]),
                }
        except Exception:
            pass

    # ── Smart money signal — read from cache (written by background bot scan) ─
    # Bot scanner writes to logs/crypto_smart_money.json periodically
    sm_cache = LOGS_DIR / "crypto_smart_money.json"
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
        BASE = "https://api.elections.kalshi.com/trade-api/v2/markets"
        btc_price = result["btc"]["price"] if result["btc"] else None
        eth_price = result["eth"]["price"] if result["eth"] else None
        xrp_price = result["xrp"]["price"] if result["xrp"] else None

        PRICE_MAP = {"KXBTC": btc_price, "KXETH": eth_price, "KXXRP": xrp_price}
        for series in ["KXBTC", "KXETH", "KXXRP"]:
            try:
                r = req.get(BASE, params={"series_ticker": series, "status": "open", "limit": 8}, timeout=5)
                if r.status_code == 200:
                    markets = r.json().get("markets", [])
                    # Sort by volume desc, take top 3
                    markets.sort(key=lambda m: m.get("volume", 0), reverse=True)
                    for m in markets[:3]:
                        yes_ask = m.get("yes_ask") or 50
                        no_ask  = m.get("no_ask") or 50
                        result["opportunities"].append({
                            "ticker":      m.get("ticker"),
                            "title":       m.get("title"),
                            "market_prob": yes_ask / 100,
                            "model_prob":  None,
                            "edge":        None,
                            "direction":   "--",
                            "yes_price":   yes_ask,
                            "no_price":    no_ask,
                            "volume":      m.get("volume", 0),
                            "spot_price":  PRICE_MAP.get(series),
                            "note":        "Run bot scan for edge analysis",
                        })
            except Exception:
                pass

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
    import requests as req
    from collections import defaultdict

    all_trades = read_all_trades()

    # Build exit records index first
    exit_records = {}
    for t in all_trades:
        if t.get('action') == 'exit':
            exit_records[t.get('ticker', '')] = t

    settled_tickers = {}
    open_tickers    = {}
    seen = set()
    for t in all_trades:
        ticker = t.get('ticker', '')
        if not ticker or ticker in seen: continue
        if t.get('action') == 'exit': continue
        seen.add(ticker)
        if is_settled_ticker(ticker) or ticker in exit_records:
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
    for ticker, t in settled_tickers.items():
        try:
            # Determine source and cost basis BEFORE any API call or `continue`.
            # Bug fix: original code placed these after the if/else block, so API-path
            # failures (status!=200, no price yet) would skip via `continue` and leave
            # both bot_cost_basis and manual_cost_basis unupdated for those positions.
            src = exit_records[ticker].get('source', t.get('source', 'bot')) if ticker in exit_records else t.get('source', 'bot')
            is_manual = src in ('economics', 'geo', 'manual')
            # Accumulate cost basis for ALL closed positions — always, regardless of
            # whether the Kalshi API call succeeds.
            position_cost = float(t.get('size_dollars') or 0)
            if is_manual:
                manual_cost_basis += position_cost
            else:
                bot_cost_basis += position_cost

            # Check if this was manually exited — use exit record for P&L (no API call needed)
            if ticker in exit_records:
                ex = exit_records[ticker]
                pnl = ex.get('realized_pnl')
                if pnl is None:
                    ep = ex.get('entry_price', 50)
                    xp = ex.get('exit_price', 50)
                    ct = ex.get('contracts', 0)
                    side = ex.get('side', t.get('side', 'no'))
                    pnl = round((xp - ep) * ct / 100, 2) if side == 'no' else round((xp - ep) * ct / 100, 2)
                pnl = round(float(pnl), 2)
                side = ex.get('side', t.get('side', 'no'))
            else:
                r = req.get(
                    f'https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}',
                    timeout=4
                )
                if r.status_code != 200: continue
                m = r.json().get('market', {})
                lp     = m.get('last_price')
                result = m.get('result')
                if lp is None and not result: continue
                # Use actual settlement result for finalized markets
                if result == 'yes':   lp = 100
                elif result == 'no':  lp = 0

                side      = t.get('side', 'no')
                mp        = t.get('market_prob', 0.5) or 0.5
                entry_p   = int((1 - mp) * 100) if side == 'no' else int(mp * 100)
                cost      = t.get('size_dollars', 25)
                contracts = t.get('contracts', 0) or 0
                if contracts > 0 and cost > 0:
                    contracts = min(contracts, int(cost / max(entry_p, 1) * 100) + 2)

                cur_p = (100 - lp) if side == 'no' else lp
                pnl   = round((cur_p - entry_p) * contracts / 100, 2)
            closed_pnl_total += pnl
            closed_total += 1
            if pnl > 0: closed_wins += 1

            # is_manual already determined above — accumulate by source
            if is_manual:
                closed_by_source['manual'] += pnl
                closed_count_by_source['manual'] += 1
            else:
                closed_by_source['bot'] += pnl
                closed_count_by_source['bot'] += 1
                if pnl > 0:
                    bot_wins += 1

            # Bucket by exit date (for manual exits) or settlement date
            # Using exit date ensures P&L is counted in the month it was realized
            if ticker in exit_records and exit_records[ticker].get('timestamp'):
                try:
                    from datetime import datetime as _dt2
                    sdate = _dt2.fromisoformat(exit_records[ticker]['timestamp']).date()
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
                if sdate.year == _today.year:
                    closed_by_period['year']  += pnl
                    if is_manual: closed_by_src_period['manual']['year']  += pnl
                    else:         closed_by_src_period['bot']['year']     += pnl
                if is_manual: closed_by_src_period['manual']['all'] += pnl
                else:         closed_by_src_period['bot']['all']    += pnl
        except Exception:
            pass

    # ── Per-module closed P&L — sourced from get_trades() for exact parity with table ──
    # Calling get_trades() ensures module card numbers are computed identically to
    # the closed positions table: BUY records from trade logs + Kalshi API settlement
    # result for each ticker. This covers both actively-exited positions (95¢ wins)
    # AND naturally settled losses that have no exit record in the logs.
    # get_trades() already excludes manual trades (source in manual/economics/geo).
    # Note: account-level closed_pnl (top of response) still comes from pnl_cache /
    # Kalshi settled positions above. A small gap between the two is expected and
    # acceptable (Kalshi P&L not captured in trade logs).
    try:
        _closed_trades = get_trades()
        from datetime import date as _date_cls2
        for _ct in _closed_trades:
            _mod = _ct.get('module', 'other')
            if _mod not in module_stats:
                _mod = 'other'
            _rpnl = float(_ct.get('realized_pnl') or 0.0)
            _ms = module_stats[_mod]
            _ms['closed_pnl'] += _rpnl
            _ms['trade_count'] += 1
            if _rpnl > 0:
                _ms['wins'] += 1
            # _date is set by read_all_trades() from the trade log filename (entry date)
            _date_str = (_ct.get('_date') or _ct.get('date', ''))[:10]
            _rdate = None
            if _date_str:
                try:
                    _rdate = _date_cls2.fromisoformat(_date_str)
                except Exception:
                    pass
            if _rdate:
                if _rdate.year == _today.year and _rdate.month == _today.month:
                    _ms['closed_pnl_month'] += _rpnl
                    _ms['trade_count_month'] += 1
                if _rdate.year == _today.year:
                    _ms['closed_pnl_year'] += _rpnl
                    _ms['trade_count_year'] += 1
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
            r = req.get(
                f'https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}',
                timeout=4
            )
            if r.status_code != 200: continue
            m = r.json().get('market', {})

            side      = t.get('side', 'no')
            mp        = t.get('market_prob', 0.5) or 0.5
            entry_p   = int((1 - mp) * 100) if side == 'no' else int(mp * 100)
            cost      = t.get('size_dollars', 25)
            contracts = t.get('contracts', 0) or 0
            if contracts > 0 and cost > 0:
                contracts = min(contracts, int(cost / max(entry_p, 1) * 100) + 2)

            # ── Fair value for existing position ─────────────────────────────
            # Use no_bid / yes_bid (what we'd SELL for) not ask (cost to buy more)
            # Fallback: 100-yes_ask (implied NO value) > last_price > entry_p
            # CRITICAL: use 'is None' not 'not cur_p' — 0 is valid (full loss)
            if side == 'no':
                cur_p = m.get('no_bid')
                if cur_p is None:
                    ya = m.get('yes_ask')
                    if ya is not None: cur_p = 100 - ya
                if cur_p is None:
                    lp = m.get('last_price')
                    if lp is not None: cur_p = 100 - lp
            else:
                cur_p = m.get('yes_bid')
                if cur_p is None:
                    cur_p = m.get('yes_ask')
                if cur_p is None:
                    lp = m.get('last_price')
                    if lp is not None: cur_p = lp
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
                # Accumulate per-module open P&L (uses live prices from Kalshi API above)
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
    # Write bot-only closed_pnl to cache so bot can read correct capital without duplicate API calls
    try:
        pnl_cache = LOGS_DIR / "pnl_cache.json"
        with open(pnl_cache, 'w', encoding='utf-8') as _f:
            json.dump({"closed_pnl": round(closed_by_source['bot'], 2)}, _f)
    except Exception:
        pass
    return pnl_result


