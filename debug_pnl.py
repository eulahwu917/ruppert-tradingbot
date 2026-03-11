import requests, json, sys
sys.stdout.reconfigure(encoding='utf-8')

# Check what Kalshi actually returns for settling positions
tickers = [
    ('KXHIGHNY-26MAR11-B66.5',   'no', 0.31, 36, 25.0),
    ('KXHIGHCHI-26MAR11-B52.5',  'no', 0.19, 30, 25.0),
    ('KXHIGHCHI-26MAR11-B50.5',  'no', 0.19, 30, 25.0),
    ('KXHIGHCHI-26MAR11-B48.5',  'no', 0.19, 30, 25.0),
]

for ticker, side, mp, contracts, cost in tickers:
    r = requests.get(f'https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}', timeout=5)
    if r.status_code != 200:
        print(f'{ticker}: HTTP {r.status_code}')
        continue
    m = r.json().get('market', {})
    entry_p = int((1 - mp) * 100) if side == 'no' else int(mp * 100)
    
    # Current prices
    yes_ask = m.get('yes_ask')
    yes_bid = m.get('yes_bid')
    no_ask  = m.get('no_ask')
    no_bid  = m.get('no_bid')
    last_p  = m.get('last_price')
    status  = m.get('status')
    result  = m.get('result')
    
    print(f'{ticker}')
    print(f'  status={status} result={result} last_price={last_p}')
    print(f'  yes_ask={yes_ask} yes_bid={yes_bid} no_ask={no_ask} no_bid={no_bid}')
    print(f'  entry_p={entry_p}c side={side}')
    
    # API pnl logic (after fix)
    if side == 'no':
        cur_p = no_ask
        if cur_p is None:
            cur_p = (100 - last_p) if last_p is not None else None
    else:
        cur_p = yes_ask
        if cur_p is None:
            cur_p = last_p if last_p is not None else None
    if cur_p is None:
        cur_p = entry_p
    
    pnl = (cur_p - entry_p) * contracts / 100
    print(f'  cur_p={cur_p}c  pnl=${pnl:.2f}')
    print()

# Also check the local prices endpoint
prices = requests.get('http://localhost:8765/api/positions/prices', timeout=10).json()
for ticker in ['KXHIGHNY-26MAR11-B66.5','KXHIGHCHI-26MAR11-B52.5']:
    print(f'Prices endpoint {ticker}: {prices.get(ticker)}')
