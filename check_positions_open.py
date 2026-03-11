import sys, json, requests
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

LOGS = Path('logs')
all_trades = []
for p in sorted(LOGS.glob('trades_*.jsonl')):
    for line in p.read_text(encoding='utf-8', errors='ignore').splitlines():
        try: all_trades.append(json.loads(line))
        except: pass

print(f'Total trade log entries: {len(all_trades)}')
print()

# Show all entries
for t in all_trades:
    action = t.get('action', 'buy')
    side   = t.get('side', '?')
    ticker = t.get('ticker', '?')
    date   = t.get('date', '?')
    cost   = t.get('size_dollars', 0)
    print(f'  {date}  {action:6}  {side:4}  ${cost:6.2f}  {ticker}')

print()
# Now check what /api/positions returns
try:
    r = requests.get('http://localhost:8765/api/positions', timeout=5)
    data = r.json()
    print(f'API /api/positions returns {len(data)} positions:')
    for p in data:
        print(f'  {p.get("ticker")}  pnl={p.get("pnl")}')
except Exception as e:
    print(f'API error: {e}')
