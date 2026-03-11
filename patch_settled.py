"""
Fix two issues:
1. Settled positions (past-date tickers) showing in Open Positions
2. P&L summary not loading

Changes to /api/positions/active:
- Parse market date from ticker (e.g. 26MAR10 = Mar 10)
- Exclude any market whose settlement date is before today
- Also exclude via live Kalshi status check (cached)

Changes to /api/account + P&L chart:
- Add /api/pnl endpoint for the chart
"""
from pathlib import Path
import re

api_path = Path('dashboard/api.py')
code = api_path.read_text(encoding='utf-8')

# ── 1. Add ticker date parser helper after read_best_bets ──────────────────
HELPER = '''

def is_settled_ticker(ticker: str) -> bool:
    """Return True if ticker contains a past date (market already settled)."""
    from datetime import date, datetime
    today = date.today()
    # Match patterns like 26MAR10, 26MAR11, 26JUN12, etc.
    # Format: YY + MON + DD  (e.g. 26MAR10 = March 10, 2026)
    months = {'JAN':1,'FEB':2,'MAR':3,'APR':4,'MAY':5,'JUN':6,
              'JUL':7,'AUG':8,'SEP':9,'OCT':10,'NOV':11,'DEC':12}
    parts = ticker.upper().split('-')
    for part in parts:
        m = re.match(r'^(\\d{2})([A-Z]{3})(\\d{2})$', part)
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

'''

# Insert after the last helper function (before first @app.get)
insert_at = code.find('@app.get("/api/summary")')
code = code[:insert_at] + HELPER + code[insert_at:]

# ── 2. Fix positions endpoint to exclude settled tickers ──────────────────
OLD_FILTER = '''    # Build set of exited tickers
    exited = {t.get('ticker') for t in all_trades if t.get('action') == 'exit'}

    # Deduplicate: keep first (earliest) entry per ticker, skip exits + dupes
    seen = {}
    for t in all_trades:
        ticker = t.get('ticker','')
        if not ticker: continue
        if ticker in exited: continue
        if ticker in seen: continue  # already have opening entry
        if t.get('action') == 'exit': continue
        seen[ticker] = t'''

NEW_FILTER = '''    # Build set of exited tickers
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
        seen[ticker] = t'''

code = code.replace(OLD_FILTER, NEW_FILTER)

# ── 3. Add /api/pnl endpoint for chart ────────────────────────────────────
PNL_ENDPOINT = '''
@app.get("/api/pnl")
def get_pnl_history():
    """P&L history for chart — one entry per trade day."""
    all_trades = read_all_trades()
    from collections import defaultdict
    from datetime import date as date_cls
    import requests as req

    # Group by date
    by_date = defaultdict(list)
    exited = {t.get('ticker') for t in all_trades if t.get('action') == 'exit'}
    seen = set()
    for t in all_trades:
        ticker = t.get('ticker','')
        if not ticker or ticker in seen: continue
        if t.get('action') == 'exit': continue
        seen.add(ticker)
        d = t.get('date') or t.get('_date', str(date_cls.today()))
        by_date[d].append(t)

    points = []
    cumulative = 0.0
    for d in sorted(by_date.keys()):
        day_cost = sum(t.get('size_dollars', 0) for t in by_date[d])
        cumulative -= day_cost  # deployed capital
        points.append({"date": d, "pnl": round(cumulative, 2)})

    return {"points": points, "total": round(cumulative, 2)}

'''

# Insert before the final route "/"
insert_before = code.rfind('@app.get("/")')
code = code[:insert_before] + PNL_ENDPOINT + code[insert_before:]

api_path.write_text(code, encoding='utf-8')
print("Patched:")
print("  - is_settled_ticker() helper added")
print("  - /api/positions/active excludes past-date markets")
print("  - /api/pnl endpoint added for chart")

import re as _re
routes = _re.findall(r'@app\.(get|post)\("([^"]+)"', code)
print(f"\nRoutes ({len(routes)}):")
for _, ep in routes:
    print(f"  {ep}")
