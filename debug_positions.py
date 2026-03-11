import sys, json, requests
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

# 1. Show all trade log files and their contents
LOGS = Path('logs')
print("=== TRADE LOG FILES ===")
for p in sorted(LOGS.glob('trades_*.jsonl')):
    lines = [l for l in p.read_text(encoding='utf-8', errors='ignore').splitlines() if l.strip()]
    print(f"\n{p.name} ({len(lines)} entries):")
    for line in lines:
        t = json.loads(line)
        print(f"  ticker={t.get('ticker','?')[:40]}  side={t.get('side','?')}  source={t.get('source','MISSING')}  action={t.get('action','MISSING')}  $={t.get('size_dollars',0):.2f}")

# 2. Check what read_today_trades returns
print("\n=== read_today_trades() ===")
import importlib.util, os
spec = importlib.util.spec_from_file_location("api", "dashboard/api.py")
api = importlib.util.load_from_spec(spec) if False else None

# Just read it directly
from datetime import date
today_file = LOGS / f"trades_{date.today().isoformat()}.jsonl"
print(f"Today's file: {today_file} exists={today_file.exists()}")
if today_file.exists():
    lines = [l for l in today_file.read_text(encoding='utf-8', errors='ignore').splitlines() if l.strip()]
    print(f"  {len(lines)} entries today")
else:
    print("  NO TRADES TODAY")

# 3. Check API
print("\n=== /api/positions (live API) ===")
try:
    r = requests.get('http://localhost:8765/api/positions', timeout=5)
    print(f"Status: {r.status_code}")
    print(r.text[:1000])
except Exception as e:
    print(f"Error: {e}")

print("\n=== /api/positions/active ===")
try:
    r = requests.get('http://localhost:8765/api/positions/active', timeout=5)
    print(f"Status: {r.status_code}")
    data = r.json()
    print(f"Count: {len(data) if isinstance(data, list) else 'not a list'}")
    if isinstance(data, list):
        for p in data:
            print(f"  {p.get('ticker',p)}")
except Exception as e:
    print(f"Error: {e}")
