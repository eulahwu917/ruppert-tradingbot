import requests

tickers = [
    'KXHIGHTDC-26MAR27-B69.5',
    'KXHIGHNY-26MAR27-B62.5',
    'KXHIGHPHIL-26MAR27-T65',
    'KXHIGHAUS-26MAR27-T86',
]

BASE = 'https://api.elections.kalshi.com/trade-api/v2/markets'
for ticker in tickers:
    r = requests.get(f'{BASE}/{ticker}', timeout=5)
    if r.status_code == 200:
        m = r.json().get('market', {})
        print(ticker)
        print('  status=' + str(m.get('status')) + ' result=' + str(m.get('result')))
        print('  yes_ask=' + str(m.get('yes_ask')) + ' yes_bid=' + str(m.get('yes_bid')) + ' no_ask=' + str(m.get('no_ask')) + ' no_bid=' + str(m.get('no_bid')))
        print('  last_price=' + str(m.get('last_price')) + ' close_time=' + str(m.get('close_time')))
        print('  title=' + str(m.get('title')))
    else:
        print(ticker + ' -> HTTP ' + str(r.status_code))
    print()
