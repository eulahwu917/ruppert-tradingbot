"""
Rewrite /api/pnl endpoint to compute ACTUAL P&L:
- For each open position: (current_market_price - entry_price) * contracts / 100
- For settled positions (past-date): use last_price from Kalshi
- Returns cumulative P&L data for the chart
"""
from pathlib import Path

api_path = Path('dashboard/api.py')
code = api_path.read_text(encoding='utf-8')

# Find and replace the /api/pnl endpoint
start = code.find('@app.get("/api/pnl")')
end   = code.find('\n@app.', start + 10)
if end == -1: end = len(code)

NEW_PNL = '''@app.get("/api/pnl")
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

'''

code = code[:start] + NEW_PNL + code[end:]
api_path.write_text(code, encoding='utf-8')
print("Patched /api/pnl with real P&L calculation")
