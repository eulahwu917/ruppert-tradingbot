import requests, json, sys
sys.stdout.reconfigure(encoding='utf-8')

print("=== /api/trades ===")
trades = requests.get('http://localhost:8765/api/trades', timeout=35).json()
for t in trades:
    mp = t.get('market_prob', 0.5) or 0.5
    side = t.get('side', 'no')
    entry_p = int((1 - mp) * 100) if side == 'no' else int(mp * 100)
    print(f"  {t['ticker']} | side={side} | contracts={t.get('contracts')} | entry={entry_p}c | settled={t.get('settled_price')} | pnl={t.get('realized_pnl')}")

print()
print("=== /api/positions/active ===")
pos = requests.get('http://localhost:8765/api/positions/active', timeout=10).json()
print(f"  Count: {len(pos)}")
for p in pos:
    print(f"  {p['ticker']} | side={p['side']} | entry={p.get('entry_price')}c | cost=${p.get('cost')} | contracts={p.get('contracts')}")

print()
print("=== Account Math Check ===")
a = requests.get('http://localhost:8765/api/account', timeout=10).json()
pnl = requests.get('http://localhost:8765/api/pnl', timeout=60).json()
start = a['starting_capital']
open_pnl = pnl['open_pnl']
closed_pnl = pnl['closed_pnl']
av = start + open_pnl + closed_pnl
print(f"  Starting capital:  ${start:.2f}")
print(f"  Open P&L:         ${open_pnl:+.2f}")
print(f"  Closed P&L:       ${closed_pnl:+.2f}")
print(f"  Account Value:    ${av:.2f}  (should match dashboard)")
print(f"  Buying Power:     ${a['buying_power']:.2f}")
print(f"  Bot deployed:     ${a['bot_deployed']:.2f}")
print(f"  Manual deployed:  ${a['manual_deployed']:.2f}")
print(f"  Total deployed:   ${a['total_deployed']:.2f}")
print(f"  BP + Deployed:    ${a['buying_power'] + a['total_deployed']:.2f}  (should = ${start:.2f})")
print()
print("=== Closed P&L Breakdown ===")
print(f"  Bot closed (all): ${pnl['bot_closed_all']:+.2f}")
print(f"  Manual closed:    ${pnl['manual_closed_all']:+.2f}")
print(f"  Total closed:     ${pnl['closed_pnl']:+.2f}")
print(f"  Win rate:         {pnl['closed_win_rate']}%")
print()
print("=== Deposits check ===")
dep = requests.get('http://localhost:8765/api/deposits', timeout=5).json()
print(f"  Total deposits: ${dep.get('total', 0):.2f}  (should = starting capital ${start:.2f})")
for d in dep.get('deposits', []):
    print(f"  {d['date']}  ${d['amount']:.2f}  {d.get('note','')}")
