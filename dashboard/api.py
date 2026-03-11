"""
Ruppert Dashboard API
FastAPI backend serving live bot data.
Run with: uvicorn dashboard.api:app --reload --port 8765
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import json
from datetime import date, datetime
from pathlib import Path

app = FastAPI(title="Ruppert Trading Dashboard")
LOGS_DIR = Path(__file__).parent.parent / "logs"

# ─── Helpers ─────────────────────────────────────────────────────────────────

def read_today_trades():
    log_path = LOGS_DIR / f"trades_{date.today().isoformat()}.jsonl"
    trades = []
    if log_path.exists():
        with open(log_path) as f:
            for line in f:
                try: trades.append(json.loads(line))
                except: pass
    return trades


def read_all_trades():
    all_trades = []
    for path in sorted(LOGS_DIR.glob("trades_*.jsonl")):
        with open(path) as f:
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


def read_best_bets():
    log_path = LOGS_DIR / "best_bets.jsonl"
    entries = []
    if log_path.exists():
        with open(log_path, encoding='utf-8') as f:
            for line in f:
                try: entries.append(json.loads(line))
                except: pass
    today = str(date.today())
    return [e for e in entries if e.get('date') == today]


SPORTS_EXCLUSIONS = [
    'points scored','rebounds','assists','touchdowns','home runs','field goal',
    'three-pointer','wins by','over 1.5','over 2.5','over 3.5','lakers','celtics',
    'warriors','knicks','heat ','bulls','nets','nba','nfl','mlb','nhl','ncaa',
    'soccer','basketball game','football game','baseball game','hockey game',
    'tennis','golf tournament','mma','boxing','both teams','goals scored',
    'rushing yards','strikeouts','shots on goal','super bowl','world series',
    'nba finals','stanley cup','world cup','march madness',
]

# ─── Endpoints ────────────────────────────────────────────────────────────────



def is_settled_ticker(ticker: str) -> bool:
    """Return True if ticker contains a past date (market already settled)."""
    import re as _re
    from datetime import date, datetime
    today = date.today()
    # Match patterns like 26MAR10, 26MAR11, 26JUN12, etc.
    # Format: YY + MON + DD  (e.g. 26MAR10 = March 10, 2026)
    months = {'JAN':1,'FEB':2,'MAR':3,'APR':4,'MAY':5,'JUN':6,
              'JUL':7,'AUG':8,'SEP':9,'OCT':10,'NOV':11,'DEC':12}
    parts = ticker.upper().split('-')
    for part in parts:
        m = _re.match(r'^(\d{2})([A-Z]{3})(\d{2})$', part)
        if m:
            yy, mon, dd = m.groups()
            month_num = months.get(mon)
            if month_num:
                try:
                    mkt_date = date(2000 + int(yy), month_num, int(dd))
                    if mkt_date < today:
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
        "mode": "DRY RUN", "status": "RUNNING",
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
    # DEMO: fixed starting capital ($200 weather + $200 crypto)
    STARTING_CAPITAL = 400.00

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

    # Auto = weather + crypto (fully autonomous)
    # Manual = geo + gaming + economics (David approves)
    AUTO_SOURCES   = ('bot', 'weather', 'economics', 'crypto')
    MANUAL_SOURCES = ('geo', 'gaming', 'manual')

    bot_cost    = sum(t.get('size_dollars',0) for t in trades if t.get('source','bot') in AUTO_SOURCES)
    manual_cost = sum(t.get('size_dollars',0) for t in trades if t.get('source','bot') in MANUAL_SOURCES)
    total_deployed = bot_cost + manual_cost

    buying_power = max(STARTING_CAPITAL - total_deployed, 0)

    return {
        "starting_capital":   STARTING_CAPITAL,
        "kalshi_balance":     STARTING_CAPITAL,  # alias kept so frontend formula is unchanged
        "buying_power":       round(buying_power, 2),
        "total_deployed":     round(total_deployed, 2),
        "bot_deployed":       round(bot_cost, 2),
        "manual_deployed":    round(manual_cost, 2),
        "bot_trade_count":    len([t for t in trades if t.get('source','bot') in AUTO_SOURCES]),
        "manual_trade_count": len([t for t in trades if t.get('source','bot') in MANUAL_SOURCES]),
        "is_dry_run":         True,
    }


@app.get("/api/trades")
def get_trades():
    return read_all_trades()


@app.get("/api/trades/today")
def get_today_trades():
    return read_today_trades()


@app.get("/api/positions/active")
def get_active_positions():
    """
    All open positions across all trade log files.
    - Reads all dates (not just today)
    - Deduplicates by ticker (first entry = opening entry)
    - Skips tickers that have a corresponding action=exit entry
    - Fast: no external API calls
    """
    all_trades = read_all_trades()

    # Build set of exited tickers
    exited = {t.get('ticker') for t in all_trades if t.get('action') == 'exit'}

    # Deduplicate: keep first (earliest) entry per ticker, skip exits + dupes + settled
    seen = {}
    for t in all_trades:
        ticker = t.get('ticker','')
        if not ticker: continue
        if ticker in exited: continue
        if ticker in seen: continue  # already have opening entry
        if t.get('action') == 'exit': continue
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
            "ticker":     ticker,
            "title":      title,
            "side":       side,
            "source":     source,
            "entry_price": ep,
            "cur_price":   ep,
            "pnl":         0.0,
            "pnl_pct":     0.0,
            "cost":        round(cost, 2),
            "contracts":   contracts,
            "pos_ratio":   pos_ratio,
            "edge":        round(edge, 3) if edge else None,
            "date":        t.get('date') or t.get('_date', ''),
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
            resp = req.get(
                f'https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}',
                timeout=4
            )
            if resp.status_code == 200:
                m = resp.json().get('market',{})
                prices[ticker] = {
                    'yes_ask': m.get('yes_ask'),
                    'yes_bid': m.get('yes_bid'),
                    'no_ask':  m.get('no_ask'),
                    'no_bid':  m.get('no_bid'),
                }
        except Exception:
            pass

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


@app.get("/api/bestbets")
def get_best_bets():
    """Best Bets — non-weather, 60%+ confidence, 15%+ edge, needs David's approval."""
    return read_best_bets()


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
    # Check for cached scanner results first (written by the bot scanner)
    scan_cache = LOGS_DIR / "crypto_scan.jsonl"
    if scan_cache.exists():
        try:
            import time as _time
            # Use cache if fresher than 30 minutes
            if _time.time() - scan_cache.stat().st_mtime < 1800:
                with open(scan_cache, encoding='utf-8') as f:
                    for line in f:
                        try: result["opportunities"].append(json.loads(line))
                        except: pass
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
    with open(Path(__file__).parent / "templates" / "index.html") as f:
        return f.read()
@app.get("/api/pnl")
def get_pnl_history():
    """
    Real P&L history for the chart.
    Open positions: (current_no_ask or yes_ask - entry_price) * contracts / 100
    Settled positions: use Kalshi last_price to determine win/loss
    """
    import requests as req
    from collections import defaultdict

    all_trades = read_all_trades()

    # Separate: settled (past-date) vs open
    settled_tickers = {}  # ticker -> trade entry
    open_tickers    = {}  # ticker -> trade entry

    seen = set()
    for t in all_trades:
        ticker = t.get('ticker', '')
        if not ticker or ticker in seen: continue
        if t.get('action') == 'exit': continue
        seen.add(ticker)
        if is_settled_ticker(ticker):
            settled_tickers[ticker] = t
        else:
            open_tickers[ticker] = t

    pnl_by_date = defaultdict(float)

    # ── Settled positions: fetch last_price from Kalshi ─────────────────────
    for ticker, t in settled_tickers.items():
        try:
            r = req.get(
                f'https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}',
                timeout=4
            )
            if r.status_code != 200: continue
            m = r.json().get('market', {})
            lp = m.get('last_price')  # YES settlement: 99=YES won, 1=NO won
            if lp is None: continue

            side      = t.get('side', 'no')
            mp        = t.get('market_prob', 0.5) or 0.5
            entry_p   = int((1 - mp) * 100) if side == 'no' else int(mp * 100)
            contracts = t.get('contracts', 0) or 0
            # Limit crazy contracts (early log bug had 500)
            cost      = t.get('size_dollars', 25)
            if contracts > 0 and cost > 0:
                contracts = min(contracts, int(cost / max(entry_p, 1) * 100) + 2)

            cur_p = (100 - lp) if side == 'no' else lp
            pnl   = round((cur_p - entry_p) * contracts / 100, 2)

            trade_date = t.get('date') or t.get('_date', '2026-03-10')
            pnl_by_date[trade_date] += pnl
        except Exception:
            pass

    # ── Open positions: fetch current market prices ──────────────────────────
    today_pnl = 0.0
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
            contracts = t.get('contracts', 0) or 0
            cost      = t.get('size_dollars', 25)
            if contracts > 0 and cost > 0:
                contracts = min(contracts, int(cost / max(entry_p, 1) * 100) + 2)

            cur_p = m.get('no_ask', entry_p) if side == 'no' else m.get('yes_ask', entry_p)
            if not cur_p: cur_p = entry_p
            pnl = round((cur_p - entry_p) * contracts / 100, 2)
            today_pnl += pnl
        except Exception:
            pass

    from datetime import date as date_cls
    today = str(date_cls.today())
    pnl_by_date[today] = pnl_by_date.get(today, 0) + today_pnl

    # Build cumulative time series
    points = []
    cumulative = 0.0
    for d in sorted(pnl_by_date.keys()):
        cumulative += pnl_by_date[d]
        points.append({"date": d, "pnl": round(cumulative, 2)})

    return {"points": points, "total": round(cumulative, 2)}

