import sys, requests, json
sys.stdout.reconfigure(encoding='utf-8')
BASE = 'http://localhost:8765'

pos      = requests.get(BASE+'/api/positions/active').json()
prices   = requests.get(BASE+'/api/positions/prices').json()
statuses = requests.get(BASE+'/api/positions/status').json()

print('=== POSITIONS ===')
for p in pos:
    print(f"  {p['ticker']} side={p['side']} entry={p['entry_price']}c contracts={p['contracts']} cost=${p['total_cost']}")

print('\n=== STATUSES ===')
for k, v in statuses.items():
    print(f"  {k}: status={v['status']} result={repr(v['result'])} last={v['last_price']}")

print('\n=== PRICES ===')
for k, v in prices.items():
    print(f"  {k}: yes_ask={v['yes_ask']} no_ask={v['no_ask']}")

print('\n=== COMPUTED P&L ===')
total = 0
for p in pos:
    ticker = p['ticker']
    st = statuses.get(ticker)
    lv = prices.get(ticker)
    entry = p['entry_price']
    contracts = p['contracts']
    cost = p['total_cost']
    side = p['side']

    if st and st['status'] in ('closed', 'settled'):
        result = st.get('result', '')
        won = (side == 'NO' and result == 'no') or (side == 'YES' and result == 'yes')
        pnl = cost * (100/entry - 1) if won else -cost
        tag = 'SETTLED WIN' if won else 'SETTLED LOSS'
    elif lv:
        cp = lv['no_ask'] if side == 'NO' else lv['yes_ask']
        if cp is None:
            pnl = 0
            tag = 'NO PRICE'
        else:
            pnl = (cp - entry) * contracts / 100
            tag = f'LIVE cp={cp}c'
    else:
        pnl = 0
        tag = 'NO DATA'

    total += pnl
    print(f"  {ticker}: {tag} => pnl=${pnl:.2f}")

print(f'\n  TOTAL OPEN P&L: ${total:.2f}')
