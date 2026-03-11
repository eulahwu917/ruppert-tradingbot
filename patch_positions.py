"""Patch /api/positions/active to read ALL trades (not just today), deduplicate, and respect action=exit."""
from pathlib import Path

api_path = Path('dashboard/api.py')
code = api_path.read_text(encoding='utf-8')

OLD = '''@app.get("/api/positions/active")
def get_active_positions():
    """Positions from trade log — fast, no external calls."""
    trades = read_today_trades()
    if not trades:
        return []
    total_cost = sum(t.get('size_dollars',0) for t in trades)
    positions  = []
    for t in trades:
        ticker = t.get('ticker','')
        title  = (t.get('title') or ticker).replace('**','')
        side   = t.get('side','no')
        pos_ratio = round(t.'''

# Find the full endpoint to replace it
start = code.find('@app.get("/api/positions/active")')
# Find end by looking for next @app.
end = code.find('\n@app.', start + 10)
if end == -1:
    end = len(code)

old_block = code[start:end]

NEW_BLOCK = '''@app.get("/api/positions/active")
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

    # Deduplicate: keep first (earliest) entry per ticker, skip exits + dupes
    seen = {}
    for t in all_trades:
        ticker = t.get('ticker','')
        if not ticker: continue
        if ticker in exited: continue
        if ticker in seen: continue  # already have opening entry
        if t.get('action') == 'exit': continue
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

'''

code = code[:start] + NEW_BLOCK + code[end:]
api_path.write_text(code, encoding='utf-8')
print(f"Patched: replaced {len(old_block)} chars with {len(NEW_BLOCK)} chars")
print(f"Open positions will now show all {len([t for t in __import__('json').loads('[]') or []])} entries")
