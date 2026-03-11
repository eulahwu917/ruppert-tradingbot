"""
Dashboard audit script — correct price calculation for NO positions.
Uses no_bid (realizable sale value) not no_ask (cost to buy more).
"""
import requests, json, sys
sys.stdout.reconfigure(encoding='utf-8')
base = 'http://localhost:8765'

acct   = requests.get(base+'/api/account', timeout=10).json()
pnl    = requests.get(base+'/api/pnl', timeout=30).json()
pos    = requests.get(base+'/api/positions/active', timeout=10).json()
prices = requests.get(base+'/api/positions/prices', timeout=10).json()
trades = requests.get(base+'/api/trades', timeout=10).json()

print('=== ACCOUNT ===')
for k, v in acct.items():
    print(f'  {k}: {v}')

print('\n=== P&L SPLIT ===')
for k, v in pnl.items():
    if k != 'points':
        print(f'  {k}: {v}')

print('\n=== ACCOUNT VALUE CHECK ===')
base_cap = 400.0
computed_av = base_cap + (pnl.get('open_pnl') or 0) + (pnl.get('closed_pnl') or 0)
print(f'  $400 base + {pnl.get("open_pnl")} open + {pnl.get("closed_pnl")} closed = ${computed_av:.2f}')

print('\n=== POSITIONS vs PRICES CROSS-CHECK ===')
# FIXED: use no_bid for NO positions (realizable value), yes_bid for YES positions
total_open_pnl = 0
for p in pos:
    ticker = p['ticker']
    lv = prices.get(ticker, {})
    side = p['side'].upper()  # normalize to uppercase for comparison
    entry = p['entry_price']
    contracts = p['contracts']
    cost = p['cost']
    if side == 'NO':
        # Use no_bid (what we'd get selling), fallback to 100-yes_ask
        cur = lv.get('no_bid')
        if cur is None and lv.get('yes_ask') is not None:
            cur = 100 - lv['yes_ask']
    else:
        cur = lv.get('yes_bid') or lv.get('yes_ask')

    if cur is not None:
        open_pnl = (cur - entry) * contracts / 100
        total_open_pnl += open_pnl
        status = 'WINNING' if cur >= 95 else ('LOSING' if cur <= 5 else '')
        print(f'  {ticker}: entry={entry}c bid={cur}c contracts={contracts} pnl=${open_pnl:.2f} {status}')
    else:
        print(f'  {ticker}: NO PRICE DATA  side={side} entry={entry}c')

print(f'\n  TOTAL OPEN P&L (cross-check): ${total_open_pnl:.2f}')
print(f'  API OPEN P&L:                 ${pnl.get("open_pnl")}')
print(f'  DIFF:                         ${total_open_pnl - (pnl.get("open_pnl") or 0):.2f}')

print('\n=== TRADES COUNT ===')
print(f'  Total trades in log: {len(trades)}')
bot_trades = [t for t in trades if t.get('source') not in ('geo','gaming','manual')]
man_trades = [t for t in trades if t.get('source') in ('geo','gaming','manual')]
print(f'  Bot trades: {len(bot_trades)}, Manual trades: {len(man_trades)}')
